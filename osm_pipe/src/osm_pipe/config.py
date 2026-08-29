"""Paths, the tag-rewrite `Rule`, and the `Dataset` / `Target` files.

Three kinds of file describe a build, and they are separate because they change
for different reasons and are reviewed by different people:

    datasets/<name>.yml   which Geofabrik regions to download and merge
    catalogue/<name>.yml  every construction project we know of, with sources
    targets/<name>.yml    a date, a dataset, and the judgement calls

A *target* is thin on purpose. The network it produces is decided by its
`as_of` date against the catalogue's opening dates — not by a hand-maintained
list of rules — so the only opinions a target carries are the ones a date
cannot express.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .dates import parse_as_of
from .geo import BBox

# osm_pipe/src/osm_pipe/config.py -> osm_pipe/
ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = ROOT.parent

DATA = ROOT / "data"
RAW = DATA / "raw"
INTERIM = DATA / "interim"
OUT = DATA / "out"
GRAPH_CACHES = DATA / "graph-caches"

DATASET_DIR = ROOT / "datasets"
CATALOGUE_DIR = ROOT / "catalogue"
TARGET_DIR = ROOT / "targets"
CONNECTOR_DIR = ROOT / "connectors"
CHANGE_DIR = ROOT / "changes"

# The OpenRailRouting docker context the backend maintains. Import configs are
# generated from its config.yml so profiles and encoded values stay defined in
# exactly one place and the caches we build are interchangeable with the app's.
ORR_DOCKER = REPO_ROOT / "backend" / "models" / "route" / "routing" / "docker"
ORR_BASE_CONFIG = ORR_DOCKER / "config.yml"
ORR_IMAGE = "docker-openrailrouting"
# Where the app's compose file mounts a graph cache from. Hardcoded there
# (backend/docker/docker-compose.yml), so hardcoded here too.
APP_GRAPH_CACHE = ORR_DOCKER / "graph-cache"

GEOFABRIK = "https://download.geofabrik.de"

# Marker the routing container's entrypoint checks before deciding to download
# a prebuilt cache. Its presence in a directory is the whole test.
CACHE_MARKER = "properties.txt"

MANIFEST_NAME = "network.json"


# --------------------------------------------------------------------------
# tag rewrite rules
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Rule:
    """One tag-rewrite rule.

    `when` selects objects; the remaining fields mutate their tags, applied in
    a fixed order: rename, unset, set, default. `default` is last so that data
    actually mapped in OSM always beats an assumption we are filling in.

    Scope is `ways` and/or `within`, and the difference in cost between them is
    large enough to matter. A way-id set is a hash lookup against an id the
    reader already has. A bbox needs the object's coordinates, which forces the
    whole pass to carry a node-location index. So a project scoped by way ids
    is cheaper than an unscoped run, and one scoped by bbox is dearer.

    Empty scope means global, which is what `all-planned` uses.
    """

    when: dict[str, Any] = field(default_factory=dict)
    rename: dict[str, str] = field(default_factory=dict)
    unset: tuple[str, ...] = ()
    set: dict[str, str] = field(default_factory=dict)
    default: dict[str, str] = field(default_factory=dict)
    types: tuple[str, ...] = ("n", "w", "r")
    ways: frozenset[int] = frozenset()
    within: tuple[BBox, ...] = ()
    stop: bool = False
    name: str = ""
    # Which catalogue project this rule came from, for reporting and markers.
    project: str = ""

    @property
    def scoped_by_location(self) -> bool:
        """True if applying this rule needs node coordinates."""
        return bool(self.within)


RULE_KEYS = {
    "when",
    "rename",
    "unset",
    "set",
    "default",
    "types",
    "ways",
    "within",
    "stop",
    "name",
}


def parse_rule(raw: dict[str, Any], index: int, *, project: str = "") -> Rule:
    """Parse a raw rule dict — the `extra_rules:` escape hatch on a target."""
    unknown = set(raw) - RULE_KEYS
    if unknown:
        raise ValueError(f"rule {index}: unknown key(s) {sorted(unknown)}")
    within = raw.get("within") or []
    # Accept both `within: [s, w, n, e]` and `within: [[s, w, n, e], ...]`.
    if len(within) == 4 and all(isinstance(v, (int, float)) for v in within):
        within = [within]
    return Rule(
        when=raw.get("when") or {},
        rename=raw.get("rename") or {},
        unset=tuple(raw.get("unset") or ()),
        set=raw.get("set") or {},
        default=raw.get("default") or {},
        types=tuple(raw.get("types") or ("n", "w", "r")),
        ways=frozenset(int(w) for w in raw.get("ways") or ()),
        within=tuple(BBox.parse(b, context=f"rule {index}") for b in within),
        stop=bool(raw.get("stop", False)),
        name=raw.get("name") or f"rule[{index}]",
        project=project,
    )


# --------------------------------------------------------------------------
# datasets
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Dataset:
    """One or more Geofabrik regions, merged into a single working extract.

    A single-region dataset is the common case (`europe`). Several regions
    exist because a corridor test wants the countries either side of a border
    and nothing else — the Fehmarn test set is Denmark plus Schleswig-Holstein
    plus Hamburg, which is ~1 GB against Europe's 30.
    """

    name: str
    description: str = ""
    regions: tuple[str, ...] = ()
    clip: BBox | None = None

    @property
    def is_composite(self) -> bool:
        return len(self.regions) > 1 or self.clip is not None

    @property
    def raw(self) -> Path:
        """The dataset's working extract — merged and clipped if it needs it."""
        return RAW / f"{self.name}-latest.osm.pbf"

    def region_file(self, region: str) -> Path:
        """Where one downloaded Geofabrik region lands."""
        return RAW / f"{region.rsplit('/', 1)[-1]}-latest.osm.pbf"

    def region_url(self, region: str) -> str:
        return f"{GEOFABRIK}/{region}-latest.osm.pbf"

    @property
    def rail(self) -> Path:
        """Rail-only extract (stage 2 output)."""
        return INTERIM / f"rail-{self.name}.osm.pbf"

    @property
    def provenance(self) -> Path:
        return RAW / f"{self.name}.provenance.json"


def load_dataset(name: str) -> Dataset:
    path = DATASET_DIR / f"{name}.yml"
    if not path.exists():
        available = sorted(p.stem for p in DATASET_DIR.glob("*.yml"))
        raise FileNotFoundError(
            f"dataset {name!r} not found at {path}. "
            f"Available: {', '.join(available) or '(none)'}"
        )
    raw = yaml.safe_load(path.read_text()) or {}
    regions = tuple(str(r) for r in raw.get("regions") or ())
    if not regions:
        raise ValueError(f"dataset {name!r}: needs at least one entry under `regions`")
    clip = raw.get("clip")
    return Dataset(
        name=str(raw.get("name", path.stem)),
        description=str(raw.get("description", "")),
        regions=regions,
        clip=BBox.parse(clip, context=f"dataset {name} clip") if clip else None,
    )


# --------------------------------------------------------------------------
# targets
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Override:
    id: str
    reason: str


@dataclass(frozen=True)
class Target:
    """A network to build: a date, a dataset, and the judgement calls.

    `as_of` is the selector. Everything else on this object exists because a
    date alone cannot express it.
    """

    name: str
    as_of: dt.date
    dataset: Dataset
    # The file this came from. `name` gains an `@<date>` suffix under
    # `--as-of` so two horizons cannot overwrite each other's cache, which
    # makes it useless in a "run this command" hint — there is no
    # targets/2032@2026-08-29.yml to load.
    source_name: str = ""
    catalogue_name: str = "europe"
    description: str = ""
    # Which of a project's two dates to believe. `latest` is the pessimistic
    # one and the default, because megaprojects slip late and rarely early.
    date_basis: str = "latest"
    force_in: tuple[Override, ...] = ()
    force_out: tuple[Override, ...] = ()
    # Ignore dates entirely and apply every project in the catalogue. This is
    # the `all-planned` upper bound, not a network anyone should publish from.
    all_projects: bool = False
    connectors: str = ""
    extra_rules: tuple[Rule, ...] = ()
    gh_xmx: str = "6g"
    gh_config_overrides: dict[str, Any] = field(default_factory=dict)

    @property
    def slug(self) -> str:
        return f"{self.name}.{self.dataset.name}"

    @property
    def command(self) -> str:
        """How to name this exact target on a command line."""
        return (
            f"{self.source_name or self.name} -d {self.dataset.name} "
            f"--as-of {self.as_of}"
        )

    @property
    def transformed(self) -> Path:
        """Stage 3 output — tags rewritten, topology still untouched."""
        return INTERIM / f"{self.slug}.transformed.osm.pbf"

    @property
    def pbf(self) -> Path:
        """What everything downstream reads: transformed *and* stitched.

        Stage 4 always writes it, even with nothing to stitch, so no later
        stage has to work out which file is current.
        """
        return INTERIM / f"{self.slug}.osm.pbf"

    @property
    def connector_file(self) -> Path | None:
        return CONNECTOR_DIR / f"{self.connectors}.yml" if self.connectors else None

    @property
    def out_dir(self) -> Path:
        return OUT / self.slug

    @property
    def graph_cache(self) -> Path:
        return GRAPH_CACHES / self.slug

    def with_as_of(self, as_of: dt.date, *, name: str | None = None) -> "Target":
        """The same target at a different date — what `--as-of` produces.

        The name changes with the date, so two horizons off one target file
        cannot overwrite each other's extract or graph cache.

        Derived from `source_name`, not from `name`, because this is applied
        twice in a row on any two-date command: `diff --as-of X
        --baseline-as-of Y` shifts the target and then shifts that result
        again. Compounding would give `2032@X@Y`, naming a file no stage ever
        wrote.
        """
        base = name or self.source_name or self.name
        if as_of == self.as_of and name is None:
            # Asking for the date it already has. Returning a differently
            # named twin would build the identical graph cache twice under two
            # slugs, which is worse than useless — it invites comparing a
            # target against itself and concluding nothing changed.
            return self
        return replace_target(self, as_of=as_of, name=name or f"{base}@{as_of}")


def replace_target(target: Target, **changes: Any) -> Target:
    from dataclasses import replace

    return replace(target, **changes)


def _overrides(raw: Any, field_name: str) -> tuple[Override, ...]:
    out: list[Override] = []
    for item in raw or []:
        if isinstance(item, str):
            raise ValueError(
                f"{field_name}: {item!r} needs a reason. Overriding a dated, "
                "sourced catalogue entry is a modelling decision, and the "
                "reason is the only record of it.\n"
                f"  {field_name}:\n    - id: {item}\n      reason: >-\n        ..."
            )
        reason = str(item.get("reason", "")).strip()
        if not reason:
            raise ValueError(f"{field_name}: {item.get('id')!r} needs a reason")
        out.append(Override(id=str(item["id"]), reason=reason))
    return tuple(out)


def load_target(name_or_path: str, dataset: str | None = None) -> Target:
    """Load a target by name (`targets/<name>.yml`) or by explicit path."""
    path = Path(name_or_path)
    if not path.suffix:
        path = TARGET_DIR / f"{name_or_path}.yml"
    if not path.exists():
        available = sorted(p.stem for p in TARGET_DIR.glob("*.yml"))
        raise FileNotFoundError(
            f"target {name_or_path!r} not found at {path}. "
            f"Available: {', '.join(available) or '(none)'}"
        )
    raw = yaml.safe_load(path.read_text()) or {}

    basis = str(raw.get("date_basis", "latest"))
    if basis not in ("official", "latest"):
        raise ValueError(
            f"target {path.stem}: date_basis must be 'official' or 'latest', "
            f"got {basis!r}"
        )

    gh = raw.get("graphhopper") or {}
    return Target(
        name=str(raw.get("name", path.stem)),
        as_of=parse_as_of(raw.get("as_of") or "1970"),
        dataset=load_dataset(dataset or str(raw.get("dataset", "europe"))),
        source_name=path.stem,
        catalogue_name=str(raw.get("catalogue", "europe")),
        description=str(raw.get("description", "")),
        date_basis=basis,
        force_in=_overrides(raw.get("force_in"), "force_in"),
        force_out=_overrides(raw.get("force_out"), "force_out"),
        all_projects=bool(raw.get("all_projects", False)),
        connectors=str(raw.get("connectors", "")),
        extra_rules=tuple(
            parse_rule(r, i) for i, r in enumerate(raw.get("extra_rules") or [])
        ),
        gh_xmx=str(gh.get("xmx", "6g")),
        gh_config_overrides=gh.get("config") or {},
    )


def ensure_dirs() -> None:
    for d in (RAW, INTERIM, OUT, GRAPH_CACHES):
        d.mkdir(parents=True, exist_ok=True)
