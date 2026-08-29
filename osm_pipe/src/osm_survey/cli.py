"""Read OSM and work out what the catalogue should say.

    osm-survey corridors <dataset> [--bbox S,W,N,E]   lifecycle chains -> scope.ways
    osm-survey project   <target> <project-id>        the same, scoped to a project
    osm-survey audit     <target>                     classify the network
    osm-survey diff      <target> [--baseline-as-of]  where did promoted track go?
    osm-survey connectors <target>                    missing junctions -> connectors

Runs entirely separately from `osm-pipe`. It prints YAML fragments for review;
it never writes a file the pipeline reads. Which ways belong to a named
construction project is a claim about the world, and it belongs in a diff
someone read.
"""

from __future__ import annotations

import argparse
import sys

from osm_pipe.config import ensure_dirs, load_dataset, load_target
from osm_pipe.dates import parse_as_of, today
from osm_pipe.geo import BBox
from osm_pipe.rules import load_target_catalogue

from . import gaps, network
from .corridors import report, survey
from .topology import Routable


def _parse_bbox(text: str) -> BBox | None:
    if not text:
        return None
    parts = [p.strip() for p in text.replace(";", ",").split(",")]
    if len(parts) != 4:
        raise SystemExit(
            f"--bbox expects four numbers S,W,N,E — got {text!r}. "
            "Note the order is south,west,north,east, the same as every bbox "
            "in the catalogue."
        )
    return BBox.parse([float(p) for p in parts], context="--bbox")


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--min-km",
        type=float,
        default=0.5,
        help="ignore chains shorter than this (default 0.5) — most are yard "
        "stubs and station rebuilds, not corridors",
    )
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--max-ways", type=int, default=200)
    parser.add_argument(
        "--min-network-size",
        type=int,
        default=200,
        help="mirrors prepare.min_network_size in the routing config",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="osm-survey",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("corridors", help="lifecycle chains -> catalogue scope.ways")
    p.add_argument("dataset")
    p.add_argument("--bbox", default="", metavar="S,W,N,E")
    _add_common(p)

    p = sub.add_parser("project", help="survey inside one catalogue project's bbox")
    p.add_argument("target")
    p.add_argument("project_id")
    p.add_argument("-d", "--dataset", default=None)
    _add_common(p)

    p = sub.add_parser("audit", help="classify the network of a built target")
    p.add_argument("target")
    p.add_argument("-d", "--dataset", default=None)
    p.add_argument("--as-of", default="", metavar="DATE")
    p.add_argument("--min-network-size", type=int, default=200)

    p = sub.add_parser("diff", help="where did the promoted track go?")
    p.add_argument("target")
    p.add_argument("-d", "--dataset", default=None)
    p.add_argument("--as-of", default="", metavar="DATE")
    p.add_argument(
        "--baseline-as-of",
        default="",
        metavar="DATE",
        help="the date to compare against (default: today)",
    )
    p.add_argument("--min-network-size", type=int, default=200)

    p = sub.add_parser(
        "connectors", help="propose connector entries from the ranked gap list"
    )
    p.add_argument("target")
    p.add_argument("-d", "--dataset", default=None)
    p.add_argument("--as-of", default="", metavar="DATE")
    p.add_argument("--project", default="", help="stamp entries with this project id")
    p.add_argument(
        "--gap-distance",
        type=float,
        default=50.0,
        metavar="M",
        help="max metres between two dangling ends to report as a gap",
    )
    p.add_argument(
        "--bearing-error",
        type=float,
        default=45.0,
        metavar="DEG",
        help="max angle before two ends count as parallel, not a junction",
    )
    p.add_argument("--limit", type=int, default=40)
    p.add_argument("--min-network-size", type=int, default=200)

    return parser


def _resolve(args):
    target = load_target(args.target, args.dataset)
    if getattr(args, "as_of", ""):
        target = target.with_as_of(parse_as_of(args.as_of))
    return target


def _audit_target(target, routable) -> dict:
    """Audit a target, reusing a previous run's summary if there is one."""
    try:
        return network.read(target.out_dir, target.pbf)
    except FileNotFoundError as exc:
        if "stale" in str(exc):
            print(f"[audit] {exc} — re-auditing")
    if not target.pbf.exists():
        raise SystemExit(
            f"target extract missing: {target.pbf}\n"
            f"Run `osm-pipe build {target.command} --skip-graph` first."
        )
    result = network.audit(target.pbf, routable)
    record = result.to_dict(
        target=target.name,
        dataset=target.dataset.name,
        as_of=target.as_of.isoformat(),
        source=network.source_fingerprint(target.pbf),
    )
    network.write(record, target.out_dir)
    return record


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ensure_dirs()
    routable = Routable(min_network_size=args.min_network_size)

    match args.command:
        case "corridors":
            dataset = load_dataset(args.dataset)
            if not dataset.rail.exists():
                raise SystemExit(
                    f"rail extract missing: {dataset.rail}\n"
                    f"Run `osm-pipe extract {dataset.name}` first."
                )
            found = survey(
                dataset.rail,
                box=_parse_bbox(args.bbox),
                min_km=args.min_km,
                limit=args.limit,
                routable=routable,
            )
            report(found, max_ways=args.max_ways)

        case "project":
            target = load_target(args.target, args.dataset)
            catalogue = load_target_catalogue(target)
            project = catalogue.get(args.project_id)
            if project.scope.bbox is None:
                raise SystemExit(
                    f"project {project.id!r} has no scope.bbox to search in. "
                    "Give it one, or use `osm-survey corridors` with an "
                    "explicit --bbox."
                )
            if not target.dataset.rail.exists():
                raise SystemExit(
                    f"rail extract missing: {target.dataset.rail}\n"
                    f"Run `osm-pipe extract {target.dataset.name}` first."
                )
            print(f"[survey] {project.id} — {project.name}")
            print(f"[survey] searching {project.scope.bbox.as_list()}")
            found = survey(
                target.dataset.rail,
                box=project.scope.bbox,
                min_km=args.min_km,
                limit=args.limit,
                routable=routable,
            )
            report(found, max_ways=args.max_ways)

        case "audit":
            _audit_target(_resolve(args), routable)

        case "diff":
            target = _resolve(args)
            baseline_date = (
                parse_as_of(args.baseline_as_of) if args.baseline_as_of else today()
            )
            baseline = target.with_as_of(baseline_date)
            print(f"[diff] baseline {baseline.slug} @ {baseline.as_of}")
            print(f"[diff] target   {target.slug} @ {target.as_of}")
            print()
            network.diff(
                _audit_target(baseline, routable),
                _audit_target(target, routable),
            )

        case "connectors":
            target = _resolve(args)
            if not target.pbf.exists():
                raise SystemExit(
                    f"target extract missing: {target.pbf}\n"
                    f"Run `osm-pipe build {target.command} --skip-graph` first."
                )
            found = gaps.find_gaps(
                target.pbf,
                routable=routable,
                max_distance_m=args.gap_distance,
                max_bearing_error=args.bearing_error,
            )
            gaps.report(found, limit=args.limit, project=args.project)

    return 0


if __name__ == "__main__":
    sys.exit(main())
