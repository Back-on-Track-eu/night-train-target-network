"""Group ways into connected chains by shared OSM node.

Two ways are connected when they share a node id. Ways that merely cross
geometrically are not — which is the property that makes this useful: every
boundary is either a real gap in the network or a gap in the OSM data.

The kernel is generic. Point it at routable track and the components are the
routing network; point it at lifecycle-tagged track and the components are
*corridors*, which is what `corridors` needs to author a project's `scope.ways`
and what the previous tool could not do at all — it collected node refs for
routable ways only, so every planned way had component -1 and no chain could be
formed.

Everything is vectorised: node refs go into flat arrays, get mapped to dense
indices, and scipy labels the components. Full-Europe rail (~2 M ways, ~30 M
node refs) runs in minutes and a few GB.
"""

from __future__ import annotations

import array
from dataclasses import dataclass

import numpy as np
import osmium
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

from .tags import lifecycle_of


@dataclass(frozen=True)
class Routable:
    """What GraphHopper can actually route on.

    Mirrors the profile the backend serves: `custom_models/night_train.json`
    zeroes non-1435 gauge and yard/spur service track, and `config.yml` sets
    `prepare.min_network_size`, which makes GraphHopper *delete* subnetworks
    below that many edges. Track can be perfectly connected in OSM and still be
    unroutable, so the analysis has to model these rules to answer "one network
    that GraphHopper can route".
    """

    railway_values: tuple[str, ...] = ("rail",)
    gauges: tuple[str, ...] = ("1435",)
    # OSM leaves gauge untagged on most mainline; treat unknown as compatible.
    # This mirrors the profile's `gauge != 0 && gauge != 1435` rule, where an
    # absent gauge encodes as 0 and is therefore allowed.
    allow_untagged_gauge: bool = True
    blocked_services: tuple[str, ...] = ("yard", "spur")
    min_network_size: int = 200

    def is_routable(self, tags) -> bool:
        if tags.get("railway") not in self.railway_values:
            return False
        if tags.get("service") in self.blocked_services:
            return False
        gauge = tags.get("gauge")
        if gauge is None:
            return self.allow_untagged_gauge
        return gauge in self.gauges


class _Collector(osmium.SimpleHandler):
    """One pass, no geometry: node refs for routable and lifecycle ways.

    Both sets are collected together because the interesting question about a
    corridor is whether it *touches* the live network, and answering that needs
    the routable node set anyway.
    """

    def __init__(self, routable: Routable):
        super().__init__()
        self.routable = routable
        # Lifecycle ways — these get grouped into corridors.
        self.way_ids = array.array("q")
        self.stage_code = array.array("b")
        self.refs = array.array("q")
        self.offsets = array.array("q", [0])
        self.stages: list[str] = []
        self._stage_index: dict[str, int] = {}
        # Every node touched by routable track, for the attachment test.
        self.routable_nodes = array.array("q")
        self.n_routable_ways = 0

    def way(self, w):
        tags = {t.k: t.v for t in w.tags}

        if self.routable.is_routable(tags):
            self.n_routable_ways += 1
            self.routable_nodes.extend(n.ref for n in w.nodes)
            return

        stage = lifecycle_of(tags)
        if not stage:
            return
        refs = [n.ref for n in w.nodes]
        if len(refs) < 2:
            return
        code = self._stage_index.get(stage)
        if code is None:
            code = len(self.stages)
            self._stage_index[stage] = code
            self.stages.append(stage)
        self.way_ids.append(w.id)
        self.stage_code.append(code)
        self.refs.extend(refs)
        self.offsets.append(len(self.refs))


@dataclass
class Corridors:
    """Lifecycle ways, grouped into connected chains."""

    way_ids: np.ndarray  # int64, collection order
    way_corridor: np.ndarray  # int32 — which chain each way belongs to
    way_stage: np.ndarray  # int8 — index into `stages`
    stages: tuple[str, ...]
    # Per corridor
    corridor_ways: np.ndarray  # int64
    corridor_key: np.ndarray  # int64 — smallest way id, a stable id
    corridor_attached: np.ndarray  # int64 — nodes shared with routable track
    n_routable_ways: int

    @property
    def n_corridors(self) -> int:
        return int(self.corridor_ways.size)


def build_corridors(pbf, routable: Routable | None = None) -> Corridors:
    routable = routable or Routable()
    collector = _Collector(routable)
    print(f"[survey] reading {pbf}")
    collector.apply_file(str(pbf))

    way_ids = np.frombuffer(collector.way_ids, dtype=np.int64).copy()
    if way_ids.size == 0:
        raise RuntimeError(
            "no lifecycle-tagged railway ways found in this extract.\n"
            "Either the region genuinely has none, or the extract was filtered "
            "without the construction:/proposed:/disused: expressions — check "
            "osm_pipe/src/osm_pipe/extract.py::FILTER_EXPRESSIONS."
        )
    way_stage = np.frombuffer(collector.stage_code, dtype=np.int8).copy()
    refs = np.frombuffer(collector.refs, dtype=np.int64).copy()
    offsets = np.frombuffer(collector.offsets, dtype=np.int64).copy()

    print(
        f"[survey] {way_ids.size:,} lifecycle ways, "
        f"{collector.n_routable_ways:,} routable ways"
    )

    node_ids = np.unique(refs)
    idx = np.searchsorted(node_ids, refs).astype(np.int64)
    n_nodes = node_ids.size

    # Consecutive refs within a way are edges; drop the pairs that straddle a
    # way boundary, which would join two unrelated ways end to end.
    keep = np.ones(idx.size - 1, dtype=bool)
    bounds = offsets[1:-1] - 1
    keep[bounds[bounds >= 0]] = False
    src = idx[:-1][keep]
    dst = idx[1:][keep]

    graph = coo_matrix(
        (np.ones(src.size, dtype=np.int8), (src, dst)),
        shape=(n_nodes, n_nodes),
    )
    n_comp, labels = connected_components(graph, directed=False)
    labels = labels.astype(np.int32)

    way_corridor = labels[idx[offsets[:-1]]]
    corridor_ways = np.bincount(way_corridor, minlength=n_comp).astype(np.int64)

    # A stable id: the smallest way id in the chain. Unlike the component index
    # it survives re-runs and OSM updates, so two surveys can be diffed.
    corridor_key = np.full(n_comp, np.iinfo(np.int64).max, dtype=np.int64)
    np.minimum.at(corridor_key, way_corridor, way_ids)

    # Does this corridor touch track a train can already use? A corridor that
    # does not is the `unconnected` failure mode, and after promotion it
    # becomes an isolated component that GraphHopper deletes outright.
    routable_nodes = np.unique(np.frombuffer(collector.routable_nodes, dtype=np.int64))
    shared = np.isin(node_ids, routable_nodes, assume_unique=True)
    corridor_attached = np.bincount(
        labels[shared], minlength=n_comp, weights=None
    ).astype(np.int64)

    print(
        f"[survey] {n_comp:,} corridors — "
        f"{int((corridor_attached > 0).sum()):,} touch routable track, "
        f"{int((corridor_attached == 0).sum()):,} do not"
    )

    return Corridors(
        way_ids=way_ids,
        way_corridor=way_corridor,
        way_stage=way_stage,
        stages=tuple(collector.stages),
        corridor_ways=corridor_ways,
        corridor_key=corridor_key,
        corridor_attached=corridor_attached,
        n_routable_ways=collector.n_routable_ways,
    )
