"""The project catalogue — every construction project we know of, with dates.

One file holds them all, at every horizon. Which of them are in a given network
is decided by comparing an opening date against the target's `as_of`, so the
same catalogue produces a 2032 network and a 2040 one with no edit. That is why
there is no `in_horizon` flag here: a hand-set boolean that nothing checks
against the dates beside it is a second source of truth waiting to disagree
with the first.

Scope rule, for what belongs in this file at all: a project is here if it
changes what a *router* sees — graph topology (a new link, a new alignment, a
reopened corridor) or a tag the night_train profile reads (gauge, maxspeed,
service). Four-tracking a corridor alongside an existing route adds capacity and
changes no path. Resignalling changes no path. A station rebuild changes no path
unless it moves a junction, which is why Stuttgart 21 is here and most station
work is not.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .changes import ChangeSpec, Scope, parse_changes
from .dates import parse_date
from .geo import BBox

PROJECT_KEYS = {
    "id",
    "name",
    "corridor",
    "countries",
    "impact",
    "opening",
    "scope",
    "changes",
    "osm",
    "probe",
    "sources",
}


@dataclass(frozen=True)
class Endpoint:
    name: str
    lat: float
    lon: float


@dataclass(frozen=True)
class Probe:
    """A routing question whose answer changes when the project opens.

    `via_bbox` is what makes it a test rather than a timing: a route can get
    faster for unrelated reasons, but it can only pass *through* the new
    corridor if the corridor is in the graph.
    """

    origin: Endpoint
    destination: Endpoint
    via: BBox
    baseline: str = ""


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    opening: dt.date
    opening_official: dt.date
    opening_latest: dt.date
    corridor: str = ""
    countries: tuple[str, ...] = ()
    impact: str = ""
    opening_note: str = ""
    scope: Scope = field(default_factory=Scope)
    changes: tuple[ChangeSpec, ...] = ()
    lifecycle: tuple[str, ...] = ()
    failure_modes: tuple[str, ...] = ()
    verified: str = ""
    osm_note: str = ""
    probe: Probe | None = None
    sources: tuple[tuple[str, str], ...] = ()

    def opening_on(self, basis: str) -> dt.date:
        return self.opening_latest if basis == "latest" else self.opening_official

    def is_open_at(self, as_of: dt.date, basis: str) -> bool:
        return self.opening_on(basis) <= as_of

    @property
    def dates(self) -> str:
        """Both dates, when they differ — the honest one-line summary."""
        if self.opening_latest != self.opening_official:
            return f"{self.opening_official} (latest: {self.opening_latest})"
        return str(self.opening_official)


@dataclass(frozen=True)
class Irrelevant:
    """A project deliberately not modelled, at any date.

    Not the same as "not open yet", and the difference matters. A line opening
    in 2035 belongs in `projects:` with a 2035 date — it is simply out at 2032
    and in at 2040. This list is for work that changes no route at any horizon:
    a commuter tunnel that leaves long-distance paths untouched, or
    electrification, which does not gate a profile whose traction has a diesel
    fallback. "Why isn't X here" is the first question every reader asks, so
    the reason is recorded rather than left implicit.
    """

    id: str
    name: str
    reason: str
    source: str = ""


@dataclass(frozen=True)
class Selection:
    """What a date selects, and why — the answer `osm-pipe projects` prints."""

    as_of: dt.date
    date_basis: str
    included: tuple[Project, ...] = ()
    excluded: tuple[tuple[Project, str], ...] = ()

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(p.id for p in self.included)


@dataclass(frozen=True)
class Catalogue:
    name: str
    description: str = ""
    projects: tuple[Project, ...] = ()
    irrelevant: tuple[Irrelevant, ...] = ()
    path: Path | None = None
    _by_id: dict[str, Project] = field(default_factory=dict, repr=False)

    def get(self, project_id: str) -> Project:
        try:
            return self._by_id[project_id]
        except KeyError:
            known = ", ".join(sorted(self._by_id))
            raise KeyError(
                f"unknown project {project_id!r} in catalogue {self.name!r}. "
                f"Known: {known}"
            ) from None

    def select(
        self,
        *,
        as_of: dt.date,
        date_basis: str = "latest",
        force_in: dict[str, str] | None = None,
        force_out: dict[str, str] | None = None,
        all_projects: bool = False,
    ) -> Selection:
        """Which projects are in the network at `as_of`, and why.

        `force_out` is unconditional — excluding a project can only make a
        network more conservative, never wrong.

        `force_in` is **not** unconditional, and deliberately so. It means
        "believe this project's optimistic date", so a project is pulled in
        only when its *official* date has passed even though the pessimistic
        `latest` one has not. An unconditional include would put a 2032 tunnel
        into a 2026 baseline the moment someone ran `--as-of` today, which is
        the one thing that must never happen: the baseline is what every other
        date is measured against. A project you want in ahead of both its own
        dates is a project whose catalogue dates are wrong — fix them there,
        where the sources are.
        """
        force_in = force_in or {}
        force_out = force_out or {}
        for pid in (*force_in, *force_out):
            self.get(pid)  # raises with the known ids if it is a typo

        included: list[Project] = []
        excluded: list[tuple[Project, str]] = []
        for project in self.projects:
            opens = project.opening_on(date_basis)
            if project.id in force_out:
                excluded.append((project, f"force_out: {force_out[project.id]}"))
            elif all_projects:
                included.append(project)
            elif opens <= as_of:
                included.append(project)
            elif project.id in force_in and project.opening_official <= as_of:
                included.append(project)
            else:
                extra = ""
                if project.id in force_in:
                    extra = (
                        f"; force_in ignored, even the official date "
                        f"({project.opening_official}) is later"
                    )
                excluded.append((project, f"opens {opens}, after {as_of}{extra}"))
        return Selection(
            as_of=as_of,
            date_basis=date_basis,
            included=tuple(included),
            excluded=tuple(excluded),
        )


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------


def _endpoint(raw: dict[str, Any] | None, which: str, project_id: str) -> Endpoint:
    if not raw:
        raise ValueError(f"project {project_id!r}: probe is missing its {which} point")
    try:
        return Endpoint(
            name=str(raw.get("name", which)),
            lat=float(raw["lat"]),
            lon=float(raw["lon"]),
        )
    except KeyError as exc:
        raise ValueError(
            f"project {project_id!r}: probe {which} point needs {exc} "
            "— a lat/lon pair, not a station name"
        ) from None


def _parse_probe(raw: dict[str, Any] | None, project_id: str) -> Probe | None:
    if not raw:
        return None
    via = raw.get("via_bbox")
    if not via:
        raise ValueError(
            f"project {project_id!r}: a probe needs via_bbox — the box the new "
            "path must pass through. Timing alone is not a test: a route can "
            "get faster for reasons unrelated to the project, but it can only "
            "pass through the new corridor if the corridor is in the graph. "
            "If the project has no corridor to pass through (electrification, "
            "say), drop the probe instead."
        )
    return Probe(
        origin=_endpoint(raw.get("from"), "from", project_id),
        destination=_endpoint(raw.get("to"), "to", project_id),
        via=BBox.parse(via, context=f"project {project_id} via_bbox"),
        baseline=str(raw.get("baseline", "")),
    )


def _parse_sources(raw: Any) -> tuple[tuple[str, str], ...]:
    out: list[tuple[str, str]] = []
    for item in raw or []:
        if isinstance(item, str):
            out.append(("", item))
        else:
            out.append((str(item.get("title", "")), str(item.get("url", ""))))
    return tuple(out)


def _parse_project(raw: dict[str, Any]) -> Project:
    try:
        project_id = str(raw["id"])
    except KeyError:
        raise ValueError(f"catalogue entry has no `id`: {raw!r}") from None

    unknown = set(raw) - PROJECT_KEYS
    if unknown:
        raise ValueError(f"project {project_id!r}: unknown key(s) {sorted(unknown)}")

    opening = raw.get("opening") or {}
    if "official" not in opening:
        raise ValueError(
            f"project {project_id!r}: needs `opening.official` — the operator's "
            "own target date. It is what decides whether this project is in a "
            "given network."
        )
    official = parse_date(opening["official"], context=f"{project_id} opening.official")
    latest = (
        parse_date(opening["latest"], context=f"{project_id} opening.latest")
        if opening.get("latest") is not None
        else official
    )

    osm = raw.get("osm") or {}
    scope = Scope.parse(raw.get("scope"), context=f"project {project_id} scope")

    if "changes" not in raw:
        raise ValueError(
            f"project {project_id!r}: needs a `changes:` key.\n"
            "Write `changes: []` if the project genuinely needs no rewrite — a "
            "corridor already tagged railway=rail because it has opened. Those "
            "entries are worth keeping: they carry a probe, which makes them "
            "control cases that must route at every date, so a failure points "
            "at a stale extract or a broken import rather than at the tagging."
        )

    return Project(
        id=project_id,
        name=str(raw.get("name", project_id)),
        opening=latest,
        opening_official=official,
        opening_latest=latest,
        corridor=str(raw.get("corridor", "")),
        countries=tuple(str(c) for c in raw.get("countries") or ()),
        impact=str(raw.get("impact", "")),
        opening_note=str(opening.get("note", "")).strip(),
        scope=scope,
        changes=parse_changes(raw.get("changes"), project_id=project_id),
        lifecycle=tuple(str(v) for v in osm.get("lifecycle") or ()),
        failure_modes=tuple(str(v) for v in osm.get("failure_modes") or ()),
        verified=str(osm.get("verified", "")),
        osm_note=str(osm.get("note", "")).strip(),
        probe=_parse_probe(raw.get("probe"), project_id),
        sources=_parse_sources(raw.get("sources")),
    )


def load_catalogue(path: Path) -> Catalogue:
    """Read one catalogue YAML. Raises on an unknown or malformed file."""
    if not path.exists():
        available = sorted(p.stem for p in path.parent.glob("*.yml"))
        raise FileNotFoundError(
            f"project catalogue not found: {path}. "
            f"Available: {', '.join(available) or '(none)'}"
        )
    raw = yaml.safe_load(path.read_text()) or {}
    projects = tuple(_parse_project(p) for p in raw.get("projects") or [])

    seen: dict[str, int] = {}
    for project in projects:
        seen[project.id] = seen.get(project.id, 0) + 1
    duplicates = sorted(pid for pid, n in seen.items() if n > 1)
    if duplicates:
        raise ValueError(f"duplicate project id(s) in {path}: {duplicates}")

    return Catalogue(
        name=str(raw.get("name", path.stem)),
        description=str(raw.get("description", "")),
        projects=projects,
        irrelevant=tuple(
            Irrelevant(
                id=str(e["id"]),
                name=str(e.get("name", e["id"])),
                reason=str(e.get("reason", "")).strip(),
                source=str(e.get("source", "")),
            )
            for e in raw.get("irrelevant") or []
        ),
        path=path,
        _by_id={p.id: p for p in projects},
    )
