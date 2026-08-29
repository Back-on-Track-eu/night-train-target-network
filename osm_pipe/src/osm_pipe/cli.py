"""Build a graph cache for the rail network as of a future date.

    osm-pipe download  <dataset>          fetch + merge the Geofabrik regions
    osm-pipe extract   <dataset>          filter it down to railway objects
    osm-pipe transform <target>           apply the selected projects' changes
    osm-pipe stitch    <target>           weld in the hand-authored connectors
    osm-pipe import    <target>           build the GraphHopper graph cache
    osm-pipe build     <target>           all of the above, in order

    osm-pipe serve     <target> -p 8992   serve routing on that cache
    osm-pipe stop      <target>           stop it
    osm-pipe status                       which servers are up, what is installed
    osm-pipe verify    <target>           route the project probes: PASS or SAME

    osm-pipe projects  <target>           what this date selects, and why
    osm-pipe targets                      what exists, and what is built
    osm-pipe datasets                     what can be downloaded
    osm-pipe install   <target>           mount this cache for the app

`--as-of DATE` overrides the target's own date, so one target file and one
catalogue produce as many networks as you have dates. The baseline is not a
special target: it is `--as-of` today, where no project has opened yet.
"""

from __future__ import annotations

import argparse
import sys

from . import install as install_mod
from . import manifest
from .catalogue import Catalogue
from .config import CACHE_MARKER, CATALOGUE_DIR, DATASET_DIR, TARGET_DIR, Target
from .config import ensure_dirs, load_dataset, load_target
from .dates import parse_as_of, today
from .download import download
from .extract import extract_rail
from .ghimport import gh_import, gh_serve, gh_stop, load_registry
from .rules import load_target_catalogue, rules_for, select
from .stitch import load_connectors, stitch_pbf
from .transform import transform_pbf
from .verify import verify


# --------------------------------------------------------------------------
# argument helpers
# --------------------------------------------------------------------------


def _add_target_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("target")
    parser.add_argument(
        "-d",
        "--dataset",
        default=None,
        help="override the target's dataset, e.g. fehmarn, austria",
    )
    parser.add_argument(
        "--as-of",
        default="",
        metavar="DATE",
        help="override the target's horizon (YYYY, YYYY-MM or YYYY-MM-DD). "
        "Use today's date for the baseline.",
    )


def _add_machine_args(parser: argparse.ArgumentParser) -> None:
    """Overrides that belong to one machine, not to the model.

    A target's `xmx: 6g` describes the hardware it was developed on. Importing
    the same target on a laptop, or through a Docker Desktop VM with its own
    limit, needs a different number for an identical graph — so it is a flag,
    not an edit to a checked-in file.
    """
    parser.add_argument(
        "--xmx",
        default="",
        metavar="SIZE",
        help="JVM heap, e.g. 6g — overrides the target's graphhopper.xmx",
    )
    parser.add_argument(
        "--gh-set",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="override one GraphHopper config key; repeatable. "
        "e.g. --gh-set graph.dataaccess.default_type=MMAP",
    )


def _gh_overrides(pairs: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key.strip():
            raise SystemExit(f"--gh-set expects KEY=VALUE, got {pair!r}")
        out[key.strip()] = value.strip()
    return out


def _target(args) -> Target:
    target = load_target(args.target, getattr(args, "dataset", None))
    as_of = getattr(args, "as_of", "")
    if as_of:
        target = target.with_as_of(parse_as_of(as_of))
    return target


def _connectors(target: Target, catalogue: Catalogue):
    path = target.connector_file
    if path is None or not path.exists():
        return ()
    return load_connectors(path, known_projects={p.id for p in catalogue.projects})


# --------------------------------------------------------------------------
# stages
# --------------------------------------------------------------------------


def _do_transform(target: Target, *, overwrite: bool) -> Catalogue:
    catalogue = load_target_catalogue(target)
    selection, rules = rules_for(target, catalogue)
    print(
        f"[plan] {target.name} @ {target.as_of} "
        f"({target.date_basis} dates): {len(selection.included)} project(s) "
        f"of {len(catalogue.projects)}, {len(rules)} rule(s)"
    )
    with_rules = {r.project for r in rules}
    for project in selection.included:
        # A selected project that produces no rules is doing nothing at all.
        # That is legitimate — `changes: []` marks a corridor already tagged
        # railway=rail, or a known gap — but it never reaches the transform
        # report, so without this line it is invisible in the one place
        # someone looks to see what a date actually did.
        note = "" if project.id in with_rules else "   (no changes — nothing applied)"
        print(
            f"[plan]   {project.id:<26} opens "
            f"{project.opening_on(target.date_basis)}{note}"
        )
    transform_pbf(target.dataset.rail, target.transformed, rules, overwrite=overwrite)
    return catalogue


def _do_build(args) -> int:
    target = _target(args)
    dataset = target.dataset
    ensure_dirs()

    if not dataset.raw.exists():
        download(dataset)
    extract_rail(dataset.raw, dataset.rail, overwrite=args.overwrite)
    catalogue = _do_transform(target, overwrite=args.overwrite)
    connectors = _connectors(target, catalogue)
    stitch_pbf(target.transformed, target.pbf, connectors, overwrite=args.overwrite)

    if args.skip_graph:
        print("[build] --skip-graph: stopping before the GraphHopper import")
        return 0

    gh_import(
        target,
        overwrite=args.overwrite,
        xmx=args.xmx,
        config_overrides=_gh_overrides(args.gh_set),
    )

    selection, rules = rules_for(target, catalogue)
    record = manifest.build(
        target,
        selection,
        catalogue_path=CATALOGUE_DIR / f"{target.catalogue_name}.yml",
        rule_count=len(rules),
        connector_count=len(connectors),
    )
    path = manifest.write(record, target.graph_cache)
    print(f"[build] {path}")
    print(f"[build] {manifest.describe(record)}")
    return 0


def _print_projects(target: Target) -> None:
    catalogue = load_target_catalogue(target)
    selection = select(target, catalogue)
    print(
        f"{catalogue.name} — as of {selection.as_of} using {selection.date_basis} dates"
    )
    print(f"{len(selection.included)} of {len(catalogue.projects)} projects in\n")

    for project in selection.included:
        print(f"  IN   {project.id:<26} {project.dates:<28} {project.impact}")
        print(f"       {project.name} — {project.corridor}")
        scope = (
            f"{len(project.scope.ways)} way ids"
            if project.scope.ways
            else ("bbox" if project.scope.bbox else "GLOBAL")
        )
        changes = ", ".join(c.label for c in project.changes) or (
            "none — documented only, nothing is rewritten"
        )
        print(f"       scope: {scope};  changes: {changes}")
        if project.probe is None:
            print("       no probe — nothing will notice if this fails to import")
        print()

    if selection.excluded:
        print(f"out ({len(selection.excluded)}):")
        for project, reason in selection.excluded:
            print(f"  out  {project.id:<26} {reason}")
        print()

    if catalogue.irrelevant:
        print(f"not modelled at any date ({len(catalogue.irrelevant)}):")
        for item in catalogue.irrelevant:
            print(f"       {item.id:<26} {' '.join(item.reason.split())}")


def _status() -> None:
    registry = load_registry()
    if not registry:
        print("no routing servers running")
    for slug, entry in sorted(registry.items()):
        print(f"{slug:<34} :{entry['port']:<6} {entry['container']}")
    print()
    print(f"app mount: {install_mod.current()}")


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="osm-pipe",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("download", help="fetch and merge a dataset's regions")
    p.add_argument("dataset")
    p.add_argument("--overwrite", action="store_true")

    p = sub.add_parser("extract", help="filter a dataset down to railway objects")
    p.add_argument("dataset")
    p.add_argument("--overwrite", action="store_true")

    p = sub.add_parser("transform", help="apply the selected projects' changes")
    _add_target_args(p)
    p.add_argument("--overwrite", action="store_true")

    p = sub.add_parser("stitch", help="weld the connectors into the extract")
    _add_target_args(p)
    p.add_argument("--overwrite", action="store_true")

    p = sub.add_parser("import", help="build the GraphHopper graph cache")
    _add_target_args(p)
    p.add_argument("--overwrite", action="store_true")
    _add_machine_args(p)

    p = sub.add_parser(
        "build", help="download -> extract -> transform -> stitch -> import"
    )
    _add_target_args(p)
    p.add_argument("--overwrite", action="store_true")
    p.add_argument(
        "--skip-graph", action="store_true", help="stop before the GraphHopper import"
    )
    _add_machine_args(p)

    p = sub.add_parser("serve", help="serve routing on a target's graph cache")
    _add_target_args(p)
    p.add_argument("-p", "--port", type=int, default=8992)
    _add_machine_args(p)

    p = sub.add_parser("stop", help="stop a target's routing server")
    _add_target_args(p)

    sub.add_parser("status", help="running servers, and what the app has mounted")

    p = sub.add_parser("verify", help="route the project probes against two dates")
    _add_target_args(p)
    p.add_argument(
        "--baseline-as-of",
        default="",
        metavar="DATE",
        help="the date to compare against (default: today)",
    )
    p.add_argument("--project", default="", help="restrict to one project id")
    p.add_argument("--profile", default="night_train")
    p.add_argument("--timeout", type=float, default=120.0)
    p.add_argument(
        "--allow-same",
        action="store_true",
        help="do not fail on SAME — for a run where no path is expected to move",
    )

    p = sub.add_parser("projects", help="what this date selects, and why")
    _add_target_args(p)

    p = sub.add_parser("install", help="mount a target's cache for the app")
    p.add_argument("target", nargs="?", default="")
    p.add_argument("-d", "--dataset", default=None)
    p.add_argument("--as-of", default="", metavar="DATE")
    p.add_argument("--restore", action="store_true", help="put the stock cache back")

    sub.add_parser("targets", help="list targets, and whether they are built")
    sub.add_parser("datasets", help="list datasets, and whether they are downloaded")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ensure_dirs()

    match args.command:
        case "download":
            download(load_dataset(args.dataset), overwrite=args.overwrite)
        case "extract":
            dataset = load_dataset(args.dataset)
            extract_rail(dataset.raw, dataset.rail, overwrite=args.overwrite)
        case "transform":
            _do_transform(_target(args), overwrite=args.overwrite)
        case "stitch":
            target = _target(args)
            catalogue = load_target_catalogue(target)
            stitch_pbf(
                target.transformed,
                target.pbf,
                _connectors(target, catalogue),
                overwrite=args.overwrite,
            )
        case "import":
            gh_import(
                _target(args),
                overwrite=args.overwrite,
                xmx=args.xmx,
                config_overrides=_gh_overrides(args.gh_set),
            )
        case "build":
            return _do_build(args)
        case "serve":
            gh_serve(
                _target(args),
                port=args.port,
                xmx=args.xmx,
                config_overrides=_gh_overrides(args.gh_set),
            )
        case "stop":
            gh_stop(_target(args))
        case "status":
            _status()
        case "verify":
            target = _target(args)
            baseline_date = (
                parse_as_of(args.baseline_as_of) if args.baseline_as_of else today()
            )
            baseline = target.with_as_of(baseline_date)
            catalogue = load_target_catalogue(target)
            selection = select(target, catalogue)
            return verify(
                target,
                baseline,
                selection.included,
                profile=args.profile,
                project_id=args.project,
                timeout=args.timeout,
                allow_same=args.allow_same,
            )
        case "projects":
            _print_projects(_target(args))
        case "install":
            if args.restore:
                install_mod.restore()
            elif not args.target:
                print(install_mod.current())
            else:
                install_mod.install(_target(args))
        case "targets":
            for path in sorted(TARGET_DIR.glob("*.yml")):
                target = load_target(str(path))
                built = (
                    "built"
                    if target.graph_cache.joinpath(CACHE_MARKER).exists()
                    else "-"
                )
                print(
                    f"{path.stem:<16} {str(target.as_of):<12} "
                    f"{target.dataset.name:<12} {built:<6} {target.description}"
                )
        case "datasets":
            for path in sorted(DATASET_DIR.glob("*.yml")):
                dataset = load_dataset(path.stem)
                state = "downloaded" if dataset.raw.exists() else "-"
                regions = ", ".join(dataset.regions)
                print(f"{path.stem:<16} {state:<12} {regions}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
