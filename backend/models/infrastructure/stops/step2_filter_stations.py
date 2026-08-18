"""Extract railway-related objects from an OSM extract into smaller, filtered PBFs.

Only the `station` filter feeds the stop classification pipeline (step 2 in the
README) — its output contains every station object *with all its tags*, which is
everything the classification notebook needs. The other filters match their tag
on ANY object in the input (tram tracks, stop positions, route relations, ...),
not just on stations: they exist purely for exploratory QGIS analysis of tag
coverage across Europe and are not pipeline inputs.

Each selected filter runs in a single shared pass over the input file —
selecting several filters (or "all") does not re-read the file once per filter,
since the input is a multi-hour continent-sized extract.

Usage:
    uv run python step2_filter_stations.py data/raw/europe-latest.osm.pbf -o data/step2_output_eu_stations
    uv run python step2_filter_stations.py data/raw/europe-latest.osm.pbf --filters all -o data/eu_stations
"""

import argparse
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import osmium
import psutil
from tqdm import tqdm

PROGRESS_UPDATE_EVERY = 50_000  # objects between progress bar refreshes
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

# Each predicate receives an osmium TagList and returns whether the object matches.
FILTER_PREDICATES: dict[str, Callable[[osmium.osm.TagList], bool]] = {
    "station": lambda tags: (
        tags.get("railway") in ("station", "halt")
        or tags.get("public_transport") == "station"
    ),
    "light_rail": lambda tags: tags.get("station") == "light_rail",
    "subway": lambda tags: (
        tags.get("subway") == "yes" or tags.get("station") == "subway"
    ),
    "tram": lambda tags: tags.get("tram") == "yes",
    "train_yes": lambda tags: tags.get("train") == "yes",
    "uic_name": lambda tags: bool(tags.get("uic_name")),
    "uic_ref": lambda tags: bool(tags.get("uic_ref")),
}


def current_rss_mb() -> float:
    """Current resident memory of this process, in MB."""
    return psutil.Process().memory_info().rss / 1_000_000


@dataclass
class FilterRun:
    """Tracks one filter's writer, predicate, and per-type match counts."""

    name: str
    predicate: Callable[[osmium.osm.TagList], bool]
    output_path: Path
    writer: osmium.SimpleWriter = field(init=False)
    matched_nodes: int = 0
    matched_ways: int = 0
    matched_relations: int = 0

    def __post_init__(self):
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.writer = osmium.SimpleWriter(str(self.output_path))

    @property
    def matched_total(self) -> int:
        return self.matched_nodes + self.matched_ways + self.matched_relations


class MultiFilterHandler(osmium.SimpleHandler):
    """Applies every active FilterRun's predicate to each object in one pass."""

    def __init__(self, runs: list[FilterRun], progress: tqdm):
        super().__init__()
        self.runs = runs
        self.progress = progress
        self.processed = 0

    def node(self, n):
        for run in self.runs:
            if run.predicate(n.tags):
                run.writer.add_node(n)
                run.matched_nodes += 1
        self._tick()

    def way(self, w):
        for run in self.runs:
            if run.predicate(w.tags):
                run.writer.add_way(w)
                run.matched_ways += 1
        self._tick()

    def relation(self, r):
        for run in self.runs:
            if run.predicate(r.tags):
                run.writer.add_relation(r)
                run.matched_relations += 1
        self._tick()

    def _tick(self):
        self.processed += 1
        if self.processed % PROGRESS_UPDATE_EVERY == 0:
            self.progress.update(PROGRESS_UPDATE_EVERY)
            total_matched = sum(run.matched_total for run in self.runs)
            self.progress.set_postfix(
                matched=total_matched, ram=f"{current_rss_mb():,.0f}MB"
            )


def input_stem(input_path: Path) -> str:
    """Input filename without a trailing .osm.pbf, for building default output names."""
    name = input_path.name
    return (
        name[: -len(".osm.pbf")]
        if name.lower().endswith(".osm.pbf")
        else input_path.stem
    )


def filter_stations(
    input_path: Path, filter_names: list[str], output_prefix: Path
) -> None:
    # A single-filter run (the pipeline default) writes the prefix as-is, e.g.
    # `-o data/step2_output_eu_stations` -> `step2_output_eu_stations.osm.pbf`.
    # Multiple filters in one run still need the per-filter suffix so their
    # outputs don't collide.
    single_filter = len(filter_names) == 1

    def output_path_for(name: str) -> Path:
        if single_filter:
            return output_prefix.with_suffix(".osm.pbf")
        return output_prefix.parent / f"{output_prefix.name}_{name}.osm.pbf"

    runs = [
        FilterRun(
            name=name,
            predicate=FILTER_PREDICATES[name],
            output_path=output_path_for(name),
        )
        for name in filter_names
    ]

    start_time = datetime.now()
    print(f"Started {start_time.strftime(TIMESTAMP_FORMAT)} — reading {input_path}")
    print(f"Filters: {', '.join(filter_names)}")

    # No location index: every predicate here only reads an object's own tags,
    # never a resolved lat/lon. Requesting one forces pyosmium to size its
    # index by the highest node ID in the file — not by how many nodes the
    # extract actually has — which for a continent-sized extract can exceed
    # available RAM and stall the run in swap.
    with tqdm(desc=input_path.name, unit=" obj", unit_scale=True) as progress:
        handler = MultiFilterHandler(runs, progress)
        handler.apply_file(str(input_path))
        progress.update(handler.processed % PROGRESS_UPDATE_EVERY)
        total_matched = sum(run.matched_total for run in runs)
        progress.set_postfix(matched=total_matched, ram=f"{current_rss_mb():,.0f}MB")
        for run in runs:
            run.writer.close()

    finish_time = datetime.now()
    print(
        f"Finished {finish_time.strftime(TIMESTAMP_FORMAT)} (took {finish_time - start_time})"
    )
    for run in runs:
        print(
            f"  [{run.name}] {run.matched_total:,} objects -> {run.output_path} "
            f"({run.matched_nodes:,} nodes, {run.matched_ways:,} ways, "
            f"{run.matched_relations:,} relations)"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_file", type=Path, help="Source .osm.pbf extract")
    parser.add_argument(
        "-f",
        "--filters",
        nargs="+",
        choices=[*FILTER_PREDICATES, "all"],
        default=["station"],
        help=(
            "Filter(s) to run in this pass, or 'all' for every filter at once. "
            "Default is 'station' — the only filter the pipeline needs."
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help=(
            "Output prefix. For a single filter (the pipeline default), the file "
            "is written as exactly <prefix>.osm.pbf — pass the full desired name, "
            "e.g. data/step2_output_eu_stations. For multiple filters, each writes "
            "<prefix>_<filter>.osm.pbf instead, to keep their outputs apart. "
            "Default prefix: <input dir>/<input name>."
        ),
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    selected_filters = (
        list(FILTER_PREDICATES)
        if "all" in args.filters
        else list(dict.fromkeys(args.filters))
    )
    prefix = args.output or args.input_file.parent / input_stem(args.input_file)
    filter_stations(args.input_file, selected_filters, prefix)
