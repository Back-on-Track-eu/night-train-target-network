"""Find the junctions OSM is missing, and propose connectors for them.

Promotion changes tags, not topology, and topology is the half that usually
breaks. A promoted line that shares no node with the live network becomes its
own component, falls below `prepare.min_network_size`, and GraphHopper deletes
it at import — silently, at every layer. `diff` shows the symptom (promoted
track landing in `pruned` rather than `network`); this finds the cause.

A **gap** is a pair of dangling track ends that

  * sit within `--gap-distance` metres of each other,
  * belong to **different** components, and
  * **point at each other**.

The last test is what makes the output usable. Two parallel sidings ending
abreast are ~4 m apart — standard European track spacing — and are not a
missing junction. The bearing check removes them.

Buffer stops and yard stubs are dangling too, but they connect to *their own*
component, so the different-component filter removes those.

Ranked by `orphan_km`: how much track the gap strands. That is the number that
decides which welds are worth a human's attention.

One deliberate difference from the tool this replaces, which deduplicated to
one row per *component pair*: a corridor severed at three separate junctions
only ever revealed its closest one, so each fix needed another full pipeline
run to discover the next. Rows here are deduplicated per junction, so one run
shows every weld a corridor needs.
"""

from __future__ import annotations

import array
from dataclasses import dataclass

import numpy as np
import osmium
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

from osm_pipe.geo import EARTH_R, haversine_m

from .topology import Routable


@dataclass
class Gap:
    node_a: int
    node_b: int
    component_a: int
    component_b: int
    distance_m: float
    bearing_error: float
    km_a: float
    km_b: float
    lat_a: float
    lon_a: float
    lat_b: float
    lon_b: float

    @property
    def orphan_km(self) -> float:
        """Track stranded by this gap — the smaller side."""
        return min(self.km_a, self.km_b)

    @property
    def osm_url(self) -> str:
        return (
            f"https://www.openstreetmap.org/?mlat={self.lat_a:.6f}"
            f"&mlon={self.lon_a:.6f}#map=19/{self.lat_a:.6f}/{self.lon_a:.6f}"
        )


def _bearing(lat1, lon1, lat2, lon2) -> float:
    """Compass bearing from point 1 to point 2, degrees."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dl = np.radians(lon2 - lon1)
    y = np.sin(dl) * np.cos(p2)
    x = np.cos(p1) * np.sin(p2) - np.sin(p1) * np.cos(p2) * np.cos(dl)
    return float(np.degrees(np.arctan2(y, x)) % 360.0)


def _angle_diff(a, b):
    d = np.abs(a - b) % 360.0
    return np.minimum(d, 360.0 - d)


class _RefPass(osmium.SimpleHandler):
    """Pass 1 — routable node refs only. No locations, so it stays cheap."""

    def __init__(self, routable: Routable):
        super().__init__()
        self.routable = routable
        self.refs = array.array("q")
        self.offsets = array.array("q", [0])

    def way(self, w):
        tags = {t.k: t.v for t in w.tags}
        if not self.routable.is_routable(tags):
            return
        refs = [n.ref for n in w.nodes]
        if len(refs) < 2:
            return
        self.refs.extend(refs)
        self.offsets.append(len(self.refs))


class _GeometryPass(osmium.SimpleHandler):
    """Pass 2 — endpoint coordinates and bearings, and component lengths.

    Both in one pass because both need node locations, and the location index
    is by far the expensive part of reading a rail extract.
    """

    def __init__(
        self,
        endpoints: set[int],
        routable: Routable,
        node_ids: np.ndarray,
        labels: np.ndarray,
    ):
        super().__init__()
        self.routable = routable
        self.endpoints = endpoints
        self.node_ids = node_ids
        self.labels = labels
        self.coord: dict[int, tuple[float, float]] = {}
        self.bearing: dict[int, float] = {}
        self.component_m = np.zeros(int(labels.max()) + 1, dtype=np.float64)

    def _component_of(self, node_id: int) -> int:
        pos = int(np.searchsorted(self.node_ids, node_id))
        if pos >= self.node_ids.size or self.node_ids[pos] != node_id:
            return -1
        return int(self.labels[pos])

    def way(self, w):
        tags = {t.k: t.v for t in w.tags}
        if not self.routable.is_routable(tags):
            return
        points = [
            (n.ref, n.location.lat, n.location.lon)
            for n in w.nodes
            if n.location.valid()
        ]
        if len(points) < 2:
            return

        component = self._component_of(points[0][0])
        if component >= 0:
            self.component_m[component] += sum(
                haversine_m(points[i][1:], points[i + 1][1:])
                for i in range(len(points) - 1)
            )

        # The direction the track points as it terminates: second-to-last
        # vertex to last. A straight line between a way's two ends would be
        # wrong on any curved approach.
        first, second = points[0], points[1]
        if first[0] in self.endpoints:
            self.coord[first[0]] = (first[1], first[2])
            self.bearing[first[0]] = _bearing(second[1], second[2], first[1], first[2])
        last, penult = points[-1], points[-2]
        if last[0] in self.endpoints:
            self.coord[last[0]] = (last[1], last[2])
            self.bearing[last[0]] = _bearing(penult[1], penult[2], last[1], last[2])


def find_gaps(
    pbf,
    *,
    routable: Routable | None = None,
    max_distance_m: float = 50.0,
    max_bearing_error: float = 45.0,
) -> list[Gap]:
    routable = routable or Routable()

    first = _RefPass(routable)
    print(f"[gaps] pass 1 — routable topology from {pbf}")
    first.apply_file(str(pbf))

    refs = np.frombuffer(first.refs, dtype=np.int64).copy()
    offsets = np.frombuffer(first.offsets, dtype=np.int64).copy()
    if refs.size == 0:
        raise RuntimeError(f"no routable track found in {pbf}")

    node_ids = np.unique(refs)
    idx = np.searchsorted(node_ids, refs).astype(np.int64)
    keep = np.ones(idx.size - 1, dtype=bool)
    bounds = offsets[1:-1] - 1
    keep[bounds[bounds >= 0]] = False
    src, dst = idx[:-1][keep], idx[1:][keep]

    graph = coo_matrix(
        (np.ones(src.size, dtype=np.int8), (src, dst)),
        shape=(node_ids.size, node_ids.size),
    )
    n_comp, labels = connected_components(graph, directed=False)
    labels = labels.astype(np.int32)

    degree = np.bincount(src, minlength=node_ids.size) + np.bincount(
        dst, minlength=node_ids.size
    )
    endpoint_ids = node_ids[degree == 1]
    print(f"[gaps] {n_comp:,} components, {endpoint_ids.size:,} dangling ends")

    second = _GeometryPass(set(endpoint_ids.tolist()), routable, node_ids, labels)
    print("[gaps] pass 2 — endpoint geometry and component lengths")
    second.apply_file(str(pbf), locations=True, idx="flex_mem")
    km = second.component_m / 1000.0

    usable = np.array(
        [n for n in endpoint_ids.tolist() if n in second.coord and n in second.bearing],
        dtype=np.int64,
    )
    if usable.size < 2:
        return []

    lat = np.array([second.coord[n][0] for n in usable])
    lon = np.array([second.coord[n][1] for n in usable])
    bearing = np.array([second.bearing[n] for n in usable])
    comp = labels[np.searchsorted(node_ids, usable)]

    # Local equirectangular metric — accurate far past the tens of metres here.
    x = np.radians(lon) * EARTH_R * np.cos(np.radians(lat))
    y = np.radians(lat) * EARTH_R
    pairs = cKDTree(np.column_stack([x, y])).query_pairs(
        r=max_distance_m, output_type="ndarray"
    )
    if pairs.size == 0:
        return []

    a, b = pairs[:, 0], pairs[:, 1]
    different = comp[a] != comp[b]
    a, b = a[different], b[different]
    if a.size == 0:
        return []

    # Do the two ends point at each other, or merely lie near each other? The
    # worse of the two errors is used, so both ends have to agree.
    ab = np.degrees(np.arctan2(x[b] - x[a], y[b] - y[a])) % 360.0
    error = np.maximum(
        _angle_diff(bearing[a], ab), _angle_diff(bearing[b], (ab + 180.0) % 360.0)
    )
    aligned = error <= max_bearing_error
    rejected = int((~aligned).sum())
    a, b, error = a[aligned], b[aligned], error[aligned]
    if rejected:
        print(
            f"[gaps] {rejected:,} near pairs rejected as parallel track ends "
            "rather than junctions"
        )
    if a.size == 0:
        return []

    distance = np.hypot(x[b] - x[a], y[b] - y[a])

    gaps = [
        Gap(
            node_a=int(usable[ia]),
            node_b=int(usable[ib]),
            component_a=int(comp[ia]),
            component_b=int(comp[ib]),
            distance_m=float(d),
            bearing_error=float(e),
            km_a=float(km[comp[ia]]),
            km_b=float(km[comp[ib]]),
            lat_a=float(lat[ia]),
            lon_a=float(lon[ia]),
            lat_b=float(lat[ib]),
            lon_b=float(lon[ib]),
        )
        for ia, ib, d, e in zip(a, b, distance, error)
    ]
    gaps.sort(key=lambda g: (-g.orphan_km, g.distance_m))
    return _dedupe(gaps)


def _dedupe(gaps: list[Gap]) -> list[Gap]:
    """One row per track end, greedily taking the best gap for each.

    Without this a double-track junction produces four rows: two dangling ends
    on each side, every pair within the radius and every pair pointing at its
    opposite. Four near-identical entries for one place is the fastest way to
    make a review list unreadable.

    Claiming each node once is exactly right rather than merely tidy. A
    double-track junction genuinely needs two connectors — one per track — and
    this yields two, not one and not four. The tool this replaces went the
    other way and deduplicated per *component pair*, which collapsed a corridor
    severed at three junctions down to its closest one, so each weld needed
    another full pipeline run to reveal the next.

    Greedy over a list already sorted by stranded track then distance, so the
    gap kept for a node is the most valuable one it appears in.
    """
    used: set[int] = set()
    out: list[Gap] = []
    for gap in gaps:
        if gap.node_a in used or gap.node_b in used:
            continue
        used.add(gap.node_a)
        used.add(gap.node_b)
        out.append(gap)
    return out


def report(gaps: list[Gap], *, limit: int = 40, project: str = "") -> None:
    """Print connector entries to review and paste."""
    if not gaps:
        print("[gaps] no candidate gaps found")
        return

    print()
    print(f"# {len(gaps)} candidate gap(s); showing {min(limit, len(gaps))}.")
    print("# Each asserts nothing — it says two dangling ends are close and")
    print("# point at each other. Open the link, look at the track, and keep")
    print("# only the ones that are genuinely one junction drawn twice.")
    print("#")
    print("# Then paste into connectors/<name>.yml and replace the reason.")
    print()
    print("connectors:")
    for gap in gaps[:limit]:
        print(f"  # {gap.osm_url}")
        print(
            f"  # {gap.distance_m:.1f} m apart, bearings agree to "
            f"{gap.bearing_error:.0f}°, strands ~{gap.orphan_km:,.1f} km"
        )
        print(f"  - id: review-{gap.node_a}-{gap.node_b}")
        if project:
            print(f"    project: {project}")
        print("    reason: >-")
        print("      TODO — say why these two ends are the same junction.")
        print('      "the gap list said so" is not a reason.')
        print(f"    a: {gap.node_a}")
        print(f"    b: {gap.node_b}")
        print()
