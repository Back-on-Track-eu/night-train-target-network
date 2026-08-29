"""Turn lifecycle-tagged track into catalogue `scope:` fragments.

The piece the previous tool had no equivalent of, and the answer to "how is
that YAML file supposed to get written". A project's `scope.bbox` is coarse —
Rail Baltica's spans five degrees of latitude and sweeps in a great deal of
unrelated planned track, and any single node inside it puts a whole way in
scope. `scope.ways` is exact. This is what produces it.

Given an extract and a box to look in, it groups lifecycle-tagged ways into
connected chains, measures each one, and prints a fragment ready to paste. It
prints and never writes: which ways belong to a named construction project is a
claim about the world, and it belongs in a diff someone read.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

import numpy as np
import osmium

from osm_pipe.geo import BBox, haversine_m

from .tags import attributes, lifecycle_of, lifecycle_kind, spelling
from .topology import Corridors, Routable, build_corridors


@dataclass
class CorridorInfo:
    key: int
    ways: list[int] = field(default_factory=list)
    length_m: float = 0.0
    south: float = 90.0
    west: float = 180.0
    north: float = -90.0
    east: float = -180.0
    stages: Counter = field(default_factory=Counter)
    spellings: Counter = field(default_factory=Counter)
    kinds: Counter = field(default_factory=Counter)
    tags: dict[str, Counter] = field(default_factory=dict)
    attached_nodes: int = 0

    @property
    def bbox(self) -> BBox:
        return BBox(self.south, self.west, self.north, self.east)

    @property
    def km(self) -> float:
        return self.length_m / 1000.0

    def note(self, key: str, value: str) -> None:
        self.tags.setdefault(key, Counter())[value] += 1

    def summary(self, key: str) -> str:
        counter = self.tags.get(key)
        if not counter:
            return ""
        value, count = counter.most_common(1)[0]
        total = sum(counter.values())
        return value if count == total else f"{value} (+{len(counter) - 1} more)"


class _GeometryPass(osmium.SimpleHandler):
    """Second pass, with node locations — length, bbox and tags per corridor."""

    def __init__(self, topo: Corridors, infos: dict[int, CorridorInfo]):
        super().__init__()
        self.infos = infos
        order = np.argsort(topo.way_ids, kind="stable")
        self._sorted_ids = topo.way_ids[order]
        self._sorted_corridor = topo.way_corridor[order]

    def _corridor_of(self, way_id: int) -> int:
        pos = int(np.searchsorted(self._sorted_ids, way_id))
        if pos >= self._sorted_ids.size or self._sorted_ids[pos] != way_id:
            return -1
        return int(self._sorted_corridor[pos])

    def way(self, w):
        tags = {t.k: t.v for t in w.tags}
        stage = lifecycle_of(tags)
        if not stage:
            return
        corridor = self._corridor_of(w.id)
        info = self.infos.get(corridor)
        if info is None:
            return

        points = [
            (n.location.lat, n.location.lon) for n in w.nodes if n.location.valid()
        ]
        if len(points) < 2:
            return

        info.ways.append(w.id)
        info.length_m += sum(
            haversine_m(points[i], points[i + 1]) for i in range(len(points) - 1)
        )
        lats = [p[0] for p in points]
        lons = [p[1] for p in points]
        info.south = min(info.south, *lats)
        info.north = max(info.north, *lats)
        info.west = min(info.west, *lons)
        info.east = max(info.east, *lons)

        info.stages[stage] += 1
        info.spellings[spelling(tags, stage)] += 1
        info.kinds[lifecycle_kind(tags, stage) or "(untyped)"] += 1
        for key, value in attributes(tags, stage).items():
            info.note(key, value)


def survey(
    pbf,
    *,
    box: BBox | None = None,
    min_km: float = 0.5,
    limit: int = 25,
    routable: Routable | None = None,
) -> list[CorridorInfo]:
    """Find lifecycle corridors, measured and ranked by length."""
    topo = build_corridors(pbf, routable)

    infos = {
        int(c): CorridorInfo(key=int(topo.corridor_key[c]))
        for c in range(topo.n_corridors)
    }
    for c, info in infos.items():
        info.attached_nodes = int(topo.corridor_attached[c])

    print("[survey] second pass — geometry and tags")
    handler = _GeometryPass(topo, infos)
    handler.apply_file(str(pbf), locations=True, idx="flex_mem")

    found = [i for i in infos.values() if i.ways]
    if box is not None:
        # A corridor is in scope when its own box overlaps the one asked for.
        # Overlap rather than containment: a corridor that leaves the box at
        # one end is still the corridor being looked for, and dropping it is
        # the failure mode that makes a survey quietly incomplete.
        found = [i for i in found if _overlaps(i.bbox, box)]
    found = [i for i in found if i.km >= min_km]
    found.sort(key=lambda i: -i.length_m)
    return found[:limit]


# A chain this long is almost never one construction project. Connectivity
# over-groups: any disused branch line sharing a single node with the corridor
# joins it, and on the Fehmarn corridor that turns an 88 km rebuild into a
# 287 km chain carrying 249 disused ways.
LONG_CORRIDOR_KM = 60.0

# Words that mark a former railway converted to something else. Promoting one
# invents track where there is now a cycle path.
_TRAIL_WORDS = ("stien", "stig", "trail", "weg", "path", "radweg", "bahntrasse")


def _warnings(info: "CorridorInfo") -> list[str]:
    """Things a reviewer should look at before pasting these way ids."""
    out: list[str] = []

    if info.km > LONG_CORRIDOR_KM:
        out.append(
            f"{info.km:,.0f} km is long for one project. Connectivity "
            "over-groups — a branch line sharing one node joins the chain. "
            "Tighten --bbox and re-run before treating this as one scope."
        )

    stages = set(info.stages)
    if len(stages) > 2:
        out.append(
            f"mixes {len(stages)} lifecycle stages ({', '.join(sorted(stages))}) "
            "— likely several different things joined by shared nodes. A "
            "project promoting only some of them will SEVER this chain: list "
            "every stage you mean to open, or the gap is silent."
        )

    # The single most expensive thing to overlook. A chain is only continuous
    # in the graph if every spelling in it was promoted, and `untyped` is the
    # one that is opt-in — so a corridor can be 94% promoted and still route
    # nowhere. Cost us two debugging sessions before this line existed.
    untyped = info.spellings.get("untyped", 0)
    if untyped:
        total = sum(info.spellings.values())
        out.append(
            f"{untyped} of {total} ways use the bare `railway=<stage>` "
            "spelling with no sub-tag. `promote:` SKIPS those unless you write "
            "`- promote: {lifecycle: <stage>, untyped: true}` — and skipping "
            "them mid-corridor breaks it."
        )

    dead = {"abandoned", "razed"} & stages
    if dead and not info.attached_nodes:
        out.append(
            f"{'/'.join(sorted(dead))} and attached to nothing — this reads "
            "like a line that is gone, not one being rebuilt. Promoting it "
            "would invent track."
        )

    name = (info.summary("name") or "").lower()
    if any(word in name for word in _TRAIL_WORDS):
        out.append(
            f"the name {info.summary('name')!r} looks like a rail trail — a "
            "former railway now a path. Check before promoting."
        )

    service = info.summary("service")
    if service:
        out.append(
            f"carries service={service} on some ways — the profile blocks "
            "service=yard and spur outright, so those will promote and then "
            "be excluded anyway"
        )
    if info.summary("usage") == "yard":
        out.append(
            "usage=yard. Note the profile's rule is on `service`, NOT `usage`, "
            "so this would promote to routable track."
        )

    return out


def _overlaps(a: BBox, b: BBox) -> bool:
    return not (
        a.north < b.south or a.south > b.north or a.east < b.west or a.west > b.east
    )


def _fmt_ways(ways: list[int], per_line: int = 6, indent: str = "        ") -> str:
    ordered = sorted(ways)
    lines = []
    for start in range(0, len(ordered), per_line):
        chunk = ordered[start : start + per_line]
        lines.append(indent + ", ".join(str(w) for w in chunk) + ",")
    return "\n".join(lines)


def report(found: list[CorridorInfo], *, max_ways: int = 200) -> None:
    """Print each corridor as a reviewable catalogue fragment."""
    if not found:
        print("[survey] no corridors matched. Widen --bbox or lower --min-km.")
        return

    print()
    print(f"# {len(found)} corridor(s), longest first.")
    print("# Read each one, decide which belong to the project you are")
    print("# describing, and paste its `ways:` into that project's `scope:`.")
    print("# A corridor is a chain of ways sharing node ids — it is NOT")
    print("# evidence that they are the same construction project.")
    print()

    for info in found:
        stages = ", ".join(f"{k}x{v}" for k, v in info.stages.most_common())
        kinds = ", ".join(f"{k}x{v}" for k, v in info.kinds.most_common())
        spell = ", ".join(f"{k}x{v}" for k, v in info.spellings.most_common())
        attach = (
            f"attached at {info.attached_nodes} node(s)"
            if info.attached_nodes
            else "NOT attached to routable track — will be pruned at import"
        )
        name = info.summary("name") or info.summary("ref") or "(unnamed)"

        print(f"# --- corridor {info.key} ---------------------------------")
        print(f"#   {name}")
        print(f"#   {info.km:,.1f} km over {len(info.ways)} way(s); {attach}")
        print(f"#   stage: {stages};  becomes: {kinds};  tagging: {spell}")
        for warning in _warnings(info):
            print(f"#   ! {warning}")
        for key in ("operator", "usage", "maxspeed", "gauge", "electrified"):
            value = info.summary(key)
            if value:
                print(f"#   {key}: {value}")
        if info.summary("opening_date"):
            print(f"#   opening_date: {info.summary('opening_date')}")
        if info.summary("oneway"):
            print(
                f"#   oneway: {info.summary('oneway')} "
                "— add `- drop_oneway` to the project's changes"
            )
        box = info.bbox
        print(
            f"#   bbox: [{box.south:.4f}, {box.west:.4f}, "
            f"{box.north:.4f}, {box.east:.4f}]"
        )
        print(f"#   https://www.openstreetmap.org/way/{info.key}")
        print("    scope:")
        if len(info.ways) > max_ways:
            print(
                f"      # {len(info.ways)} ways — over the {max_ways} printed "
                "here. Re-run with a tighter --bbox to split this corridor, or "
                "raise --max-ways if it really is one project."
            )
        print("      ways:")
        print(_fmt_ways(info.ways[:max_ways]))
        print()
