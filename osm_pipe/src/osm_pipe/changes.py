"""Expand a project's opted-in changes into tag-rewrite rules.

This is where the two halves meet. `catalogue/<name>.yml` says which projects
are being built and, per project, which named changes apply and over what
scope. `changes/library.yml` says what each named change mechanically does.
This module turns the pair into `Rule` objects for the transform stage.

Order is fixed here rather than taken from the file: promote, then drop_oneway,
then set, then default. `drop_oneway` keys off the marker the promotions leave
behind, so it has to run after them, and requiring the author to remember that
would be a footgun with a silent failure — the rule would simply match nothing.

Every generated rule carries three markers:

    ntn:project=<id>              which project put this way in the graph
    ntn:change=<change>           what was done to it
    ntn:opening=<YYYY-MM-DD>      the date that decision was based on

so a computed route can be audited back to the projects it depends on, and a
route through track opening in 2031 can be told apart from one that only needs
what is already built.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import yaml

from .config import CHANGE_DIR, Rule
from .geo import BBox

MARKER_PROJECT = "ntn:project"
MARKER_CHANGE = "ntn:change"
MARKER_OPENING = "ntn:opening"
MARKER_ONEWAY_DROPPED = "ntn:oneway-dropped"

# Applied in this order regardless of how the project lists them.
PHASES = ("promote", "drop_oneway", "set", "default")


@dataclass(frozen=True)
class Scope:
    """Where a change applies.

    Way ids are precise and cheap — a hash lookup on an id the reader already
    has. A bbox is coarse and dear: it needs the object's coordinates, which
    forces the whole transform pass to carry a node-location index, and *any*
    single node inside the box puts the whole way in scope, so a 200 km way
    clipping a corner is fully rewritten.

    When both are given, way ids win and the bbox is documentation. Neither
    means global, which only the unscoped lifecycles may do.
    """

    ways: frozenset[int] = frozenset()
    bbox: BBox | None = None

    @property
    def is_empty(self) -> bool:
        return not self.ways and self.bbox is None

    def as_rule_kwargs(self) -> dict[str, Any]:
        if self.ways:
            return {"ways": self.ways}
        if self.bbox is not None:
            return {"within": (self.bbox,)}
        return {}

    @classmethod
    def parse(cls, raw: Any, *, context: str) -> "Scope":
        if not raw:
            return cls()
        ways = frozenset(int(w) for w in raw.get("ways") or ())
        bbox = raw.get("bbox")
        return cls(
            ways=ways,
            bbox=BBox.parse(bbox, context=context) if bbox else None,
        )


@lru_cache(maxsize=1)
def load_library(path_str: str = "") -> dict[str, Any]:
    path = CHANGE_DIR / "library.yml" if not path_str else CHANGE_DIR / path_str
    if not path.exists():
        raise FileNotFoundError(f"change library not found: {path}")
    raw = yaml.safe_load(path.read_text()) or {}
    library = raw.get("changes") or {}
    if "promote" not in library:
        raise ValueError(f"{path}: change library has no `promote` entry")
    return library


# --------------------------------------------------------------------------
# parsing a project's `changes:` list
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ChangeSpec:
    """One entry from a project's `changes:` list, already normalised."""

    kind: str  # promote | drop_oneway | set | default
    lifecycle: str = ""
    untyped: bool = False
    tags: dict[str, str] = None  # type: ignore[assignment]
    scope: Scope | None = None  # overrides the project's own scope

    @property
    def label(self) -> str:
        return f"{self.kind}:{self.lifecycle}" if self.lifecycle else self.kind


def parse_changes(raw: Any, *, project_id: str) -> tuple[ChangeSpec, ...]:
    """Normalise a project's `changes:` list.

    Accepts `- drop_oneway`, `- promote: construction`,
    `- promote: {lifecycle: disused, untyped: true, scope: {...}}`,
    `- default: {maxspeed: "200"}`.
    """
    library = load_library()
    specs: list[ChangeSpec] = []
    for index, item in enumerate(raw or []):
        where = f"project {project_id!r}, changes[{index}]"

        if isinstance(item, str):
            kind, body = item, None
        elif isinstance(item, dict) and len(item) == 1:
            kind, body = next(iter(item.items()))
        else:
            raise ValueError(
                f"{where}: expected `- <change>` or `- <change>: <value>`, got {item!r}"
            )

        if kind not in library:
            raise ValueError(
                f"{where}: unknown change {kind!r}. Known: {', '.join(sorted(library))}"
            )

        if kind == "promote":
            specs.append(_parse_promote(body, where=where, library=library))
        elif kind == "drop_oneway":
            if body:
                raise ValueError(f"{where}: drop_oneway takes no value")
            specs.append(ChangeSpec(kind=kind, tags={}))
        elif kind in ("set", "default"):
            if not isinstance(body, dict) or not body:
                raise ValueError(f"{where}: {kind} needs a mapping of tags")
            specs.append(
                ChangeSpec(kind=kind, tags={str(k): str(v) for k, v in body.items()})
            )
        else:
            raise ValueError(f"{where}: change {kind!r} is documented but not built")

    return tuple(specs)


def _parse_promote(body: Any, *, where: str, library: dict) -> ChangeSpec:
    lifecycles = library["promote"]["lifecycles"]
    if isinstance(body, str):
        lifecycle, untyped, scope_raw = body, False, None
    elif isinstance(body, dict):
        lifecycle = str(body.get("lifecycle", ""))
        untyped = bool(body.get("untyped", False))
        scope_raw = body.get("scope")
    else:
        raise ValueError(f"{where}: promote needs a lifecycle value")

    if lifecycle not in lifecycles:
        raise ValueError(
            f"{where}: cannot promote {lifecycle!r}. "
            f"Known lifecycles: {', '.join(sorted(lifecycles))}"
        )
    return ChangeSpec(
        kind="promote",
        lifecycle=lifecycle,
        untyped=untyped,
        tags={},
        scope=Scope.parse(scope_raw, context=where) if scope_raw else None,
    )


# --------------------------------------------------------------------------
# expansion
# --------------------------------------------------------------------------


def expand(
    *,
    project_id: str,
    specs: tuple[ChangeSpec, ...],
    scope: Scope,
    opening: dt.date,
) -> list[Rule]:
    """Turn one project's changes into rules, in the fixed phase order."""
    library = load_library()
    markers = {
        MARKER_PROJECT: project_id,
        MARKER_OPENING: opening.isoformat(),
    }
    promotes = any(s.kind == "promote" for s in specs)
    rules: list[Rule] = []
    for phase in PHASES:
        for spec in specs:
            if spec.kind != phase:
                continue
            active = spec.scope if spec.scope is not None else scope
            rules.extend(
                _expand_one(
                    spec,
                    project_id=project_id,
                    scope=active,
                    markers=markers,
                    library=library,
                    promotes=promotes,
                )
            )
    return rules


def _expand_one(
    spec: ChangeSpec,
    *,
    project_id: str,
    scope: Scope,
    markers: dict[str, str],
    library: dict,
    promotes: bool,
) -> list[Rule]:
    if spec.kind == "promote":
        return _expand_promote(
            spec,
            project_id=project_id,
            scope=scope,
            markers=markers,
            library=library,
        )

    if spec.kind == "drop_oneway":
        if not promotes:
            raise ValueError(
                f"project {project_id!r}: `drop_oneway` needs a `promote:` "
                "alongside it.\n"
                "It drops `oneway` from track *this project promoted*, keyed "
                "on the marker a promotion writes. With nothing promoted it "
                "would match nothing and say nothing about it. If you mean to "
                "drop oneway from track that is already railway=rail, say so "
                "explicitly with `- unset: [oneway]` — which does not exist "
                "yet, because no project has needed it."
            )
        return [
            Rule(
                types=("w",),
                project=project_id,
                # `"yes"` is a literal value match, so only ways that actually
                # carried the tag get the marker — the count of dropped
                # oneways is then a real number rather than the count of
                # everything this project promoted.
                when={MARKER_PROJECT: project_id, "oneway": "yes"},
                name=f"{project_id}/drop_oneway",
                unset=("oneway",),
                set={MARKER_ONEWAY_DROPPED: "yes"},
            )
        ]

    if promotes:
        # Key off the marker the promotions left behind: this touches only
        # track this project actually changed, so it cannot catch a
        # neighbouring project's ways that happen to share a bbox. The marker
        # is already on those ways, so nothing more to stamp.
        base = {
            "types": ("w",),
            "when": {MARKER_PROJECT: project_id},
            "project": project_id,
        }
        stamp: dict[str, str] = {}
    else:
        # No promotion to key off — an attribute-only project, such as
        # electrifying a corridor that is already railway=rail. Fall back to
        # the project's own scope, and stamp the markers here since nothing
        # else will. Without this the rule matches nothing and says nothing
        # about it, which is the silent no-op this pipeline exists to avoid.
        if scope.is_empty:
            raise ValueError(
                f"project {project_id!r}: `{spec.kind}:` with no `promote:` "
                "needs a scope.\n"
                "There is no promotion to key off, so the only thing "
                "restricting this change is the project's own scope — and "
                "without one it would rewrite every way in the extract. Give "
                "the project `scope: {ways: [...]}` (run `osm-survey "
                "corridors`) or `scope: {bbox: [s, w, n, e]}`."
            )
        base = {
            "types": ("w",),
            "when": {"railway": "rail"},
            "project": project_id,
            **scope.as_rule_kwargs(),
        }
        stamp = {**markers, MARKER_CHANGE: spec.label}

    if spec.kind == "set":
        return [
            Rule(
                **base,
                name=f"{project_id}/set",
                set={**stamp, **spec.tags},
            )
        ]
    if spec.kind == "default":
        return [
            Rule(
                **base,
                name=f"{project_id}/default",
                # The markers go in `set` even here: an audit marker that only
                # lands when the key happens to be absent would be worse than
                # none, because a route could depend on this project's track
                # and carry no trace of it.
                set=dict(stamp),
                default=dict(spec.tags),
            )
        ]
    raise AssertionError(f"unreachable change kind {spec.kind!r}")


def _expand_promote(
    spec: ChangeSpec,
    *,
    project_id: str,
    scope: Scope,
    markers: dict[str, str],
    library: dict,
) -> list[Rule]:
    promote = library["promote"]
    lifecycle = spec.lifecycle
    settings = promote["lifecycles"][lifecycle] or {}
    lift: list[str] = list(promote["lift"])
    accept: list[str] = list(promote["accept"])
    defaults: dict[str, str] = {
        k: str(v) for k, v in (promote["default"] or {}).items()
    }

    if settings.get("require_scope") and scope.is_empty:
        raise ValueError(
            f"project {project_id!r}: `promote: {lifecycle}` needs a scope.\n"
            f"Europe-wide, railway={lifecycle} is overwhelmingly track nobody "
            "is rebuilding — promoting all of it would invent a network. "
            "Inside a project's scope it means the corridor is shut *because* "
            "it is being rebuilt, which is a claim this project is making.\n"
            "Give the project `scope: {ways: [...]}` (run `osm-survey "
            "corridors` to find them) or `scope: {bbox: [s, w, n, e]}`."
        )

    scope_kwargs = scope.as_rule_kwargs()
    common: dict[str, Any] = {
        "types": ("w",),
        "project": project_id,
        **scope_kwargs,
    }
    # Renames for the attributes hiding under the lifecycle prefix. Absent
    # keys are skipped by the engine, so listing them all is free.
    lifted = {f"{lifecycle}:{key}": key for key in lift}
    marker_set = {**markers, MARKER_CHANGE: spec.label}
    service_gate = {"service": False} if settings.get("exclude_service") else {}

    rules: list[Rule] = []

    # Form 1 — the prefixed spelling: railway=construction + construction:railway=rail
    rules.append(
        Rule(
            **common,
            name=f"{project_id}/promote:{lifecycle}",
            when={
                "railway": lifecycle,
                f"{lifecycle}:railway": accept,
                **service_gate,
            },
            rename={f"{lifecycle}:railway": "railway", **lifted},
            set=dict(marker_set),
            default=dict(defaults),
        )
    )

    # Form 2 — the short spelling: railway=construction + construction=rail.
    # Both are in use across Europe; the Fehmarn Belt ways carry both.
    rules.append(
        Rule(
            **common,
            name=f"{project_id}/promote:{lifecycle}-short",
            when={
                "railway": lifecycle,
                lifecycle: accept,
                f"{lifecycle}:railway": False,
                **service_gate,
            },
            rename=dict(lifted),
            set={"railway": "rail", **marker_set},
            default=dict(defaults),
        )
    )

    # Form 3 — railway=construction and nothing else. The mapper recorded that
    # something is planned here without recording what, so this is a weaker
    # claim than the two above and is opted into separately.
    if spec.untyped:
        rules.append(
            Rule(
                **common,
                name=f"{project_id}/promote:{lifecycle}-untyped",
                when={
                    "railway": lifecycle,
                    f"{lifecycle}:railway": False,
                    lifecycle: False,
                    **service_gate,
                },
                rename=dict(lifted),
                set={"railway": "rail", **marker_set},
                default=dict(defaults),
            )
        )

    return rules
