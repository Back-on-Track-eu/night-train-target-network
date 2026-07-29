"""Extract railway=station/halt objects from an OSM extract into a smaller PBF.

Usage:
    uv run python filter_stations.py data/raw/europe-latest.osm.pbf
    uv run python filter_stations.py data/raw/europe-latest.osm.pbf -o data/raw/stations_eu.osm.pbf
"""

class StationFilter(osm.SimpleHandler):
    def __init__(self):
        super(StationFilter, self).__init__()
        self.writer = osm.SimpleWriter("data/raw/all_stations_europe.osm.pbf")
import argparse
from datetime import datetime
from pathlib import Path

import osmium
import psutil
from tqdm import tqdm

STATION_RAILWAY_VALUES = {"station", "halt"}
PROGRESS_UPDATE_EVERY = 50_000  # objects between progress bar refreshes
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


def current_rss_mb() -> float:
    """Current resident memory of this process, in MB."""
    return psutil.Process().memory_info().rss / 1_000_000


class StationFilter(osmium.SimpleHandler):
    """Writes every railway=station/halt node, way, and relation to a new PBF."""

    def __init__(self, output_path: Path, progress: tqdm):
        super().__init__()
        self.writer = osmium.SimpleWriter(str(output_path))
        self.progress = progress
        self.processed = 0
        self.matched_nodes = 0
        self.matched_ways = 0
        self.matched_relations = 0

    @property
    def matched_total(self) -> int:
        return self.matched_nodes + self.matched_ways + self.matched_relations

    def node(self, n):
        if self._is_station(n):
            self.writer.add_node(n)
            self.matched_nodes += 1
        self._tick()

    def way(self, w):
        if self._is_station(w):
            self.writer.add_way(w)
            self.matched_ways += 1
        self._tick()

    def relation(self, r):
        if self._is_station(r):
            self.writer.add_relation(r)
            self.matched_relations += 1
        self._tick()

    @staticmethod
    def _is_station(obj) -> bool:
        return obj.tags.get("railway") in STATION_RAILWAY_VALUES

    def _is_station(self, o):
        tags = o.tags
        return (
            tags.get("railway") in ("station", "halt")
            or tags.get("public_transport") == "station"
        )
    def _tick(self):
        self.processed += 1
        if self.processed % PROGRESS_UPDATE_EVERY == 0:
            self.progress.update(PROGRESS_UPDATE_EVERY)
            self.progress.set_postfix(
                stations=self.matched_total, ram=f"{current_rss_mb():,.0f}MB"
            )


def filter_stations(input_path: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    start_time = datetime.now()
    print(f"Started {start_time.strftime(TIMESTAMP_FORMAT)} — reading {input_path}")

    # PBF headers don't carry a reliable entity count, so the bar tracks
    # objects processed rather than a percentage — still enough to confirm
    # the run is progressing and roughly how fast.
    #
    # No location index here: the filter only reads each object's own tags,
    # never a resolved lat/lon. Requesting one (as the original script did)
    # forces pyosmium to size its index by the highest node ID in the file —
    # not by how many nodes the extract actually has — which for a
    # continent-sized extract can far exceed available RAM and stall the
    # run in swap.
    with tqdm(desc=input_path.name, unit=" obj", unit_scale=True) as progress:
        handler = StationFilter(output_path, progress)
        handler.apply_file(str(input_path))
        progress.update(handler.processed % PROGRESS_UPDATE_EVERY)
        progress.set_postfix(
            stations=handler.matched_total, ram=f"{current_rss_mb():,.0f}MB"
        )
        handler.writer.close()

    finish_time = datetime.now()
    print(
        f"Finished {finish_time.strftime(TIMESTAMP_FORMAT)} (took {finish_time - start_time})"
    )
    print(
        f"Wrote {handler.matched_total:,} station objects to {output_path} "
        f"({handler.matched_nodes:,} nodes, {handler.matched_ways:,} ways, "
        f"{handler.matched_relations:,} relations)"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_file", type=Path, help="Source .osm.pbf extract")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Destination .osm.pbf (default: <input dir>/stations_europe.osm.pbf)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    output_file = args.output or args.input_file.parent / "stations_europe.osm.pbf"
    filter_stations(args.input_file, output_file)