"""Fetch center coordinates for station ways/relations via the Overpass API.

Why this exists: `step2_filter_stations.py` writes only the matched objects
themselves. Station *nodes* carry their own lat/lon, but station *ways* and
*relations* only reference member node IDs — and those member nodes are not in
the filtered file, so their coordinates cannot be resolved locally. Rather than
re-reading the ~32 GB `europe-latest.osm.pbf` (hours), this script asks the
Overpass API for the center point of each way/relation ID (minutes).

Caveats:
- Overpass reflects current OSM, which may be slightly newer than the extract.
  Objects deleted since the extract date return no center and are reported at
  the end — expect a small handful, review manually if more.
- The public Overpass instance occasionally answers a batch with 504/502/503
  (overloaded) or 429 (rate limited). Those are retried — 429 waits however
  long the server's own `Retry-After` header says, everything else backs off
  exponentially. If a batch still fails after all retries, its IDs are skipped
  and written to `<output>.failed_ids.csv` instead of aborting the whole run —
  the CSV is still written with everything resolved so far.

Resuming: just re-run the script. Overpass is stateless per request, so a
second pass over the same IDs is exactly as cheap as the first — no special
resume flag needed.

Usage:
    uv run python step3a_fetch_missing_centers.py
    uv run python step3a_fetch_missing_centers.py --input data/step2_output_eu_stations.osm.pbf
"""

import argparse
import csv
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import osmium
from tqdm import tqdm

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
BATCH_SIZE = (
    500  # IDs per Overpass request — smaller batches load the shared instance less
)
REQUEST_PAUSE_S = 4.0  # politeness pause between successful requests
REQUEST_TIMEOUT_S = 300
RETRYABLE_HTTP_CODES = {429, 502, 503, 504}  # rate limit / overloaded — worth retrying
MAX_ATTEMPTS = 4
RETRY_BACKOFF_S = 15.0  # fallback if the server gives no Retry-After: 15s, 30s, 60s
# Overpass's usage policy requires clients to identify themselves; requests without
# a User-Agent are rejected with HTTP 406 by its front-end before the query even runs.
REQUEST_HEADERS = {
    "User-Agent": "night-train-target-network/stop-classification (Back-on-Track-eu)"
}


class WayRelationIdCollector(osmium.SimpleHandler):
    """Collects the IDs of all ways and relations in the filtered extract."""

    def __init__(self):
        super().__init__()
        self.way_ids: list[int] = []
        self.relation_ids: list[int] = []

    def way(self, w) -> None:
        self.way_ids.append(w.id)

    def relation(self, r) -> None:
        self.relation_ids.append(r.id)


def fetch_centers(osm_type: str, ids: list[int]) -> dict[int, tuple[float, float]]:
    """Query Overpass for the center lat/lon of the given way or relation IDs.

    Retries with exponential backoff on transient server errors (overloaded
    or rate-limited) — the public instance returns these fairly often under
    load. Raises after MAX_ATTEMPTS so the caller can skip the batch.
    """
    id_list = ",".join(str(i) for i in ids)
    query = f"[out:csv(::id, ::lat, ::lon; false)];{osm_type}(id:{id_list});out center;"
    body = urllib.parse.urlencode({"data": query}).encode()
    request = urllib.request.Request(OVERPASS_URL, data=body, headers=REQUEST_HEADERS)

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
                text = response.read().decode()
            break
        except urllib.error.HTTPError as e:
            if e.code not in RETRYABLE_HTTP_CODES or attempt == MAX_ATTEMPTS:
                raise
            # Overpass sends Retry-After on 429s — that's the server telling us
            # exactly how long its rate limiter is blocking us for; trust it over
            # our own guess. Fall back to exponential backoff if it's absent
            # (usually the case for 502/503/504, which aren't rate-limit signals).
            retry_after = e.headers.get("Retry-After") if e.headers else None
            if retry_after and retry_after.isdigit():
                wait_s = float(retry_after)
            else:
                wait_s = RETRY_BACKOFF_S * (2 ** (attempt - 1))
            tqdm.write(
                f"  HTTP {e.code} on this batch (attempt {attempt}/{MAX_ATTEMPTS}) "
                f"— retrying in {wait_s:.0f}s"
            )
            time.sleep(wait_s)

    centers = {}
    for line in text.strip().splitlines():
        osm_id, lat, lon = line.split("\t")
        if lat and lon:  # deleted objects come back without coordinates
            centers[int(osm_id)] = (float(lat), float(lon))
    return centers


def write_centers_csv(
    output_path: Path, resolved: dict[tuple[str, int], tuple[float, float]]
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["osm_type", "osm_id", "lat", "lon"])
        for (osm_type, osm_id), (lat, lon) in sorted(resolved.items()):
            writer.writerow([osm_type, osm_id, lat, lon])


def write_failed_ids_csv(
    output_path: Path, failed: list[tuple[str, int]]
) -> Path | None:
    if not failed:
        return None
    failed_path = output_path.with_name(output_path.stem + ".failed_ids.csv")
    with open(failed_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["osm_type", "osm_id"])
        writer.writerows(sorted(failed))
    return failed_path


def main(input_path: Path, output_path: Path) -> None:
    collector = WayRelationIdCollector()
    collector.apply_file(str(input_path))
    print(
        f"{input_path}: {len(collector.way_ids):,} ways, "
        f"{len(collector.relation_ids):,} relations to resolve"
    )

    resolved: dict[tuple[str, int], tuple[float, float]] = {}
    failed_ids: list[tuple[str, int]] = []
    jobs = [("way", collector.way_ids), ("relation", collector.relation_ids)]

    # Written in a `finally` (not just at the end) so a late-batch failure never
    # discards work already fetched — re-running only needs to catch up on
    # whatever is still missing.
    try:
        for osm_type, ids in jobs:
            batches = [ids[i : i + BATCH_SIZE] for i in range(0, len(ids), BATCH_SIZE)]
            for batch in tqdm(batches, desc=f"{osm_type}s", unit=" batch"):
                try:
                    for osm_id, center in fetch_centers(osm_type, batch).items():
                        resolved[(osm_type, osm_id)] = center
                except urllib.error.HTTPError as e:
                    tqdm.write(
                        f"  Batch of {len(batch)} {osm_type}s failed after "
                        f"{MAX_ATTEMPTS} attempts ({e}) — skipping, will list in "
                        f"the failed-ids report"
                    )
                    failed_ids.extend((osm_type, i) for i in batch)
                time.sleep(REQUEST_PAUSE_S)
    finally:
        write_centers_csv(output_path, resolved)

    total_requested = len(collector.way_ids) + len(collector.relation_ids)
    deleted_in_osm = total_requested - len(resolved) - len(failed_ids)
    print(f"Wrote {len(resolved):,} centers to {output_path}")
    if deleted_in_osm:
        print(
            f"WARNING: {deleted_in_osm:,} objects returned no center "
            f"(deleted in current OSM?)"
        )
    if failed_ids:
        failed_path = write_failed_ids_csv(output_path, failed_ids)
        print(
            f"WARNING: {len(failed_ids):,} objects skipped after repeated server "
            f"errors — listed in {failed_path}. Re-run the script to retry them "
            f"(cheap: Overpass is stateless per request)."
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-i",
        "--input",
        type=Path,
        default=Path("data/step2_output_eu_stations.osm.pbf"),
        help="Filtered station extract from step 2",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("data/step3a_output_way_relation_centers.csv"),
        help="Output CSV: osm_type, osm_id, lat, lon",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    main(args.input, args.output)
