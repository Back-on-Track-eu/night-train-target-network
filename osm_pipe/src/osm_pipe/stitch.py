"""Stage 4 — weld in the hand-authored junctions OSM does not have.

Promoting a tag changes tags, not topology, and topology is the half that
usually breaks. Mappers draw a planned alignment as a standalone way whose
endpoint sits *on top of* an existing junction without being the same node.
GraphHopper joins ways that share a node id and nothing else, so the promoted
line becomes its own component, falls below `prepare.min_network_size`, and is
deleted at import — with no error anywhere.

A connector is the minimal repair: one way referencing two node ids that
already exist in the extract. Because both ends are real nodes, the new way is
welded to whatever ways those nodes belong to. No snapping, no coordinate
matching, no ambiguity — and no way to get it subtly wrong, which is why the
two refusals below are hard errors rather than warnings.

`osm-survey connectors` proposes entries from the ranked gap list; it prints
and never writes. Every entry here asserts that two pieces of railway will
physically be joined, which is a claim about the world and belongs in a diff
someone read.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import osmium
import osmium.osm.mutable
import yaml

from .geo import haversine_m

# A connector longer than this is not a missing junction — it is a piece of
# invented railway. Still allowed, since a target may legitimately need one,
# but it gets said out loud.
LONG_CONNECTOR_M = 500.0

# Tags every connector gets unless it overrides them. `railway=rail` is what
# makes it routable at all; the gauge and speed defaults exist so the way does
# not inherit a profile default silently.
CONNECTOR_DEFAULTS = {
    "railway": "rail",
    "gauge": "1435",
    "maxspeed": "100",
    "usage": "main",
}

CONNECTOR_KEYS = {"id", "a", "b", "via", "tags", "project", "reason"}

MARKER_CONNECTOR = "ntn:connector"
MARKER_PROJECT = "ntn:project"


@dataclass(frozen=True)
class Connector:
    id: str
    a: int
    b: int
    via: tuple[tuple[float, float], ...] = ()
    tags: dict[str, str] = field(default_factory=dict)
    project: str = ""
    reason: str = ""

    def resolved_tags(self) -> dict[str, str]:
        tags = dict(CONNECTOR_DEFAULTS)
        tags.update({k: str(v) for k, v in self.tags.items()})
        # Written last so they cannot be overridden: a connector that does not
        # say it is a connector defeats the point of auditing a route for
        # invented track.
        tags[MARKER_CONNECTOR] = self.id
        if self.project:
            tags[MARKER_PROJECT] = self.project
        return tags


def load_connectors(path: Path, *, known_projects: set[str] | None = None):
    """Read a connector file, validating everything cheap to validate."""
    if not path.exists():
        raise FileNotFoundError(f"connector file not found: {path}")
    raw = yaml.safe_load(path.read_text()) or {}
    out: list[Connector] = []
    for index, item in enumerate(raw.get("connectors") or []):
        where = f"connector {index} in {path}"
        if not isinstance(item, dict):
            raise ValueError(f"{where}: expected a mapping, got {item!r}")
        unknown = set(item) - CONNECTOR_KEYS
        if unknown:
            raise ValueError(f"{where}: unknown key(s) {sorted(unknown)}")
        try:
            connector = Connector(
                id=str(item.get("id") or f"connector[{index}]"),
                a=int(item["a"]),
                b=int(item["b"]),
                via=tuple(
                    (float(lat), float(lon)) for lat, lon in item.get("via") or []
                ),
                tags=dict(item.get("tags") or {}),
                project=str(item.get("project", "")),
                reason=str(item.get("reason", "")).strip(),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"{where}: {exc}") from exc

        if connector.a == connector.b:
            raise ValueError(
                f"{where}: `a` and `b` are the same node ({connector.a}). "
                "That is a zero-length way joining nothing to itself."
            )
        if known_projects is not None and connector.project:
            if connector.project not in known_projects:
                known = ", ".join(sorted(known_projects))
                raise ValueError(
                    f"{where}: unknown project {connector.project!r}. Known: {known}"
                )
        out.append(connector)

    ids = [c.id for c in out]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ValueError(f"duplicate connector id(s) in {path}: {duplicates}")
    return tuple(out)


class _Stitcher(osmium.SimpleHandler):
    """Copy the extract through, injecting connectors at the type boundaries.

    A PBF is written nodes, then ways, then relations, each ascending by id.
    Synthetic ids are allocated above the highest real one, so emitting the new
    nodes when the first way arrives and the new ways when the first relation
    arrives keeps the output correctly ordered without a second pass.
    """

    def __init__(self, writer: osmium.SimpleWriter, connectors: tuple[Connector, ...]):
        super().__init__()
        self.writer = writer
        self.connectors = connectors
        self.wanted = {n for c in connectors for n in (c.a, c.b)}
        self.found: dict[int, tuple[float, float]] = {}
        self.max_node_id = 0
        self.max_way_id = 0
        self.nodes_done = False
        self.ways_done = False
        self.refs: dict[str, list[int]] = {}
        self.lengths: dict[str, float] = {}

    # -- copy -------------------------------------------------------------

    def node(self, n):
        if n.id > self.max_node_id:
            self.max_node_id = n.id
        if n.id in self.wanted and n.location.valid():
            self.found[n.id] = (n.location.lat, n.location.lon)
        self.writer.add_node(n)

    def way(self, w):
        self._finish_nodes()
        if w.id > self.max_way_id:
            self.max_way_id = w.id
        self.writer.add_way(w)

    def relation(self, r):
        # A file with no ways at all still needs the node flush first.
        self._finish_nodes()
        self._finish_ways()
        self.writer.add_relation(r)

    def finish(self) -> None:
        self._finish_nodes()
        self._finish_ways()

    # -- injection --------------------------------------------------------

    def _finish_nodes(self) -> None:
        if self.nodes_done:
            return
        self.nodes_done = True

        missing = sorted(self.wanted - set(self.found))
        if missing:
            raise ValueError(
                "connector endpoints are not in the extract: "
                + ", ".join(str(m) for m in missing)
                + "\nA connector must reference node ids that exist in the OSM "
                "data — that shared id is the whole mechanism. A missing id "
                "would produce a dangling reference that joins nothing while "
                "looking perfectly correct on a map, so this aborts instead. "
                "Check the id on openstreetmap.org, and check it belongs to a "
                "railway way (the rail extract keeps nothing else)."
            )

        next_id = self.max_node_id + 1
        for connector in self.connectors:
            refs = [connector.a]
            points = [self.found[connector.a]]
            for lat, lon in connector.via:
                self.writer.add_node(
                    osmium.osm.mutable.Node(
                        id=next_id,
                        # NOTE: Location takes (lon, lat) — the opposite order
                        # to the (lat, lon) pairs used everywhere else here.
                        location=osmium.osm.Location(lon, lat),
                        tags={MARKER_CONNECTOR: connector.id},
                    )
                )
                refs.append(next_id)
                points.append((lat, lon))
                next_id += 1
            refs.append(connector.b)
            points.append(self.found[connector.b])
            self.refs[connector.id] = refs
            self.lengths[connector.id] = sum(
                haversine_m(points[i], points[i + 1]) for i in range(len(points) - 1)
            )

    def _finish_ways(self) -> None:
        if self.ways_done:
            return
        self.ways_done = True
        next_id = self.max_way_id + 1
        for connector in self.connectors:
            self.writer.add_way(
                osmium.osm.mutable.Way(
                    id=next_id,
                    nodes=self.refs[connector.id],
                    tags=connector.resolved_tags(),
                )
            )
            next_id += 1


def _link(src: Path, dst: Path) -> None:
    """Hardlink, falling back to a relative symlink.

    Relative matters: the routing container bind-mounts data/interim at
    /app/data, so an absolute host path would not resolve inside it.
    """
    try:
        dst.hardlink_to(src)
    except OSError:
        dst.symlink_to(src.name)


def stitch_pbf(
    src: Path,
    dst: Path,
    connectors: tuple[Connector, ...],
    *,
    overwrite: bool = False,
) -> Path:
    """Write `dst` from `src` plus the connector ways.

    Always writes `dst`, even with nothing to stitch, so no later stage has to
    work out which of the two files is current.
    """
    if dst.exists() and not overwrite:
        print(f"[stitch] {dst} exists — skipping (use --overwrite to rebuild)")
        return dst
    if not src.exists():
        raise FileNotFoundError(
            f"transformed extract missing: {src} — run `osm-pipe transform` first"
        )
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()

    if not connectors:
        print(f"[stitch] no connectors — linking {src.name} -> {dst.name}")
        _link(src, dst)
        return dst

    writer = osmium.SimpleWriter(str(dst))
    handler = _Stitcher(writer, connectors)
    try:
        handler.apply_file(str(src))
        handler.finish()
    except BaseException:
        # A half-written pbf is worse than none — see extract.py. Bad node ids
        # abort here, so this path is live rather than defensive.
        writer.close()
        dst.unlink(missing_ok=True)
        raise
    writer.close()

    print(f"[stitch] {len(connectors)} connector(s) welded into {dst}")
    for connector in connectors:
        length = handler.lengths[connector.id]
        flag = "  <-- long, this is invented track" if length > LONG_CONNECTOR_M else ""
        label = connector.id
        if connector.project:
            label = f"{label} ({connector.project})"
        print(f"[stitch]   {label}: {length:,.0f} m{flag}")
        if connector.reason:
            print(f"[stitch]     {connector.reason}")
    return dst
