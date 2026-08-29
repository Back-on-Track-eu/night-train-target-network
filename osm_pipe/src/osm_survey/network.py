"""Classify every way by what GraphHopper could actually route on.

Connectivity alone is the wrong question. The right one is stricter: the
`night_train` profile zeroes non-1435 gauge and yard/spur service track, and
`prepare.min_network_size: 200` makes GraphHopper **delete** subnetworks below
that many edges. Track can be perfectly connected in OSM and still be
unroutable, so every way lands in one of five classes:

    network   the main routable component — *the* network
    island    routable track, not reachable from the main network
    pruned    routable, but below min_network_size — GraphHopper drops it
    planned   drawn, never routable: still lifecycle-tagged after the transform
    excluded  blocked by the profile before connectivity matters

Edge counts are ours, not GraphHopper's internal ones, so components near the
threshold should be read as "probably pruned".

This is what answers the question a target run actually raises: the promotion
worked, so where did the promoted track *go*? `diff` reads two of these and
reports how much moved into `network` versus fell into `island` or `pruned`.
"""

from __future__ import annotations

import array
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import osmium
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

from osm_pipe.geo import haversine_m

from .tags import lifecycle_of
from .topology import Routable

CLASSES = ("network", "island", "pruned", "planned", "excluded")
CLASS_CODE = {name: i for i, name in enumerate(CLASSES)}

# Written by the transform onto every way a project changed.
MARKER_PROJECT = "ntn:project"


class _Collector(osmium.SimpleHandler):
    """One pass with locations: refs, length and markers per track way."""

    def __init__(self, routable: Routable):
        super().__init__()
        self.routable = routable
        self.way_ids = array.array("q")
        self.kind = array.array("b")  # 0 routable, 1 planned, 2 excluded
        self.length_m = array.array("d")
        self.project: list[str] = []
        self.refs = array.array("q")
        self.offsets = array.array("q", [0])

    def way(self, w):
        tags = {t.k: t.v for t in w.tags}
        railway = tags.get("railway")
        stage = lifecycle_of(tags)
        if railway is None and not stage:
            return

        points = [
            (n.location.lat, n.location.lon) for n in w.nodes if n.location.valid()
        ]
        if len(points) < 2:
            return
        length = sum(
            haversine_m(points[i], points[i + 1]) for i in range(len(points) - 1)
        )

        if self.routable.is_routable(tags):
            refs = [n.ref for n in w.nodes]
            if len(refs) < 2:
                return
            self.way_ids.append(w.id)
            self.kind.append(0)
            self.length_m.append(length)
            self.project.append(tags.get(MARKER_PROJECT, ""))
            self.refs.extend(refs)
            self.offsets.append(len(self.refs))
            return

        # Not routable: still worth measuring, because the interesting number
        # is how much track moved *between* these buckets.
        self.way_ids.append(w.id)
        self.kind.append(1 if stage else 2)
        self.length_m.append(length)
        self.project.append(tags.get(MARKER_PROJECT, ""))


@dataclass
class Audit:
    class_km: dict[str, float]
    total_km: float
    n_components: int
    n_ways: int
    project_km: dict[str, dict[str, float]]
    min_network_size: int

    def to_dict(self, **extra) -> dict:
        return {
            **extra,
            "total_km": round(self.total_km, 3),
            "class_km": {k: round(v, 3) for k, v in self.class_km.items()},
            "n_components": self.n_components,
            "n_ways": self.n_ways,
            "min_network_size": self.min_network_size,
            "project_km": {
                project: {k: round(v, 3) for k, v in classes.items()}
                for project, classes in sorted(self.project_km.items())
            },
        }


def audit(pbf: Path, routable: Routable | None = None) -> Audit:
    routable = routable or Routable()
    collector = _Collector(routable)
    print(f"[audit] reading {pbf}")
    collector.apply_file(str(pbf), locations=True, idx="flex_mem")

    way_ids = np.frombuffer(collector.way_ids, dtype=np.int64).copy()
    if way_ids.size == 0:
        raise RuntimeError(f"no track ways found in {pbf}")
    kind = np.frombuffer(collector.kind, dtype=np.int8).copy()
    length_km = np.frombuffer(collector.length_m, dtype=np.float64).copy() / 1000.0
    projects = np.array(collector.project, dtype=object)
    refs = np.frombuffer(collector.refs, dtype=np.int64).copy()
    offsets = np.frombuffer(collector.offsets, dtype=np.int64).copy()

    is_routable = kind == 0
    if not is_routable.any():
        raise RuntimeError("no routable track found — check the Routable settings")

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

    way_component = labels[idx[offsets[:-1]]]
    component_nodes = np.bincount(labels, minlength=n_comp)
    component_edges = np.bincount(labels[src], minlength=n_comp)
    main = int(np.argmax(component_nodes))

    component_class = np.where(
        component_edges < routable.min_network_size,
        CLASS_CODE["pruned"],
        CLASS_CODE["island"],
    ).astype(np.int8)
    component_class[main] = CLASS_CODE["network"]

    way_class = np.where(
        kind == 1, CLASS_CODE["planned"], CLASS_CODE["excluded"]
    ).astype(np.int8)
    way_class[is_routable] = component_class[way_component]

    class_km = {
        name: float(length_km[way_class == code].sum())
        for name, code in CLASS_CODE.items()
    }

    project_km: dict[str, dict[str, float]] = {}
    touched = projects != ""
    for project in sorted(set(projects[touched])):
        mask = projects == project
        project_km[str(project)] = {
            name: float(length_km[mask & (way_class == code)].sum())
            for name, code in CLASS_CODE.items()
            if float(length_km[mask & (way_class == code)].sum()) > 0.0005
        }

    print(
        f"[audit] {way_ids.size:,} track ways, {n_comp:,} routable components, "
        f"{class_km['network']:,.1f} km network"
    )
    return Audit(
        class_km=class_km,
        total_km=float(length_km.sum()),
        n_components=n_comp,
        n_ways=int(way_ids.size),
        project_km=project_km,
        min_network_size=routable.min_network_size,
    )


def write(record: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "summary.json"
    path.write_text(json.dumps(record, indent=2) + "\n")
    print(f"[audit] {path}")
    return path


def source_fingerprint(pbf: Path) -> dict:
    """Enough to notice the extract changed under a cached audit."""
    stat = pbf.stat()
    return {"bytes": stat.st_size, "mtime": int(stat.st_mtime)}


def read(out_dir: Path, pbf: Path | None = None) -> dict:
    """A previous audit, but only if it still describes `pbf`.

    Re-auditing costs a location-index pass, so the result is cached — but a
    cache that answers after its input changed is worse than no cache. Rebuild
    a target and the old summary would otherwise be handed straight back, and
    a `diff` against it would report that nothing moved. That is
    indistinguishable from a target that genuinely did nothing, which is the
    one wrong answer this whole pipeline is built to avoid.
    """
    path = out_dir / "summary.json"
    if not path.exists():
        raise FileNotFoundError(
            f"no audit at {path} — run `osm-survey audit` for that target first"
        )
    record = json.loads(path.read_text())
    if pbf is not None and pbf.exists():
        if record.get("source") != source_fingerprint(pbf):
            raise FileNotFoundError(
                f"audit at {path} is stale — {pbf.name} has changed since"
            )
    return record


def diff(base: dict, other: dict) -> None:
    """Where did the promoted track go?

    The first number to look at when a target changes no route. Promotion moves
    track out of `planned`; the question is whether it landed in `network`
    (joined the routable graph) or in `island`/`pruned` (stranded by a missing
    junction, and deleted at import).
    """
    a, b = base["class_km"], other["class_km"]
    print(f"{'':12} {'baseline':>12} {'target':>12} {'delta':>12}")
    for name in CLASSES:
        va, vb = a.get(name, 0.0), b.get(name, 0.0)
        print(f"{name:<12} {va:>12,.1f} {vb:>12,.1f} {vb - va:>+12,.1f}")
    ta, tb = base["total_km"], other["total_km"]
    print(f"{'total':<12} {ta:>12,.1f} {tb:>12,.1f} {tb - ta:>+12,.1f}")
    print()

    promoted = a.get("planned", 0.0) - b.get("planned", 0.0)
    joined = b.get("network", 0.0) - a.get("network", 0.0)
    islanded = b.get("island", 0.0) - a.get("island", 0.0)
    stranded = b.get("pruned", 0.0) - a.get("pruned", 0.0)
    blocked = b.get("excluded", 0.0) - a.get("excluded", 0.0)
    print(f"promoted out of `planned`      {promoted:>12,.1f} km")
    print(f"  ...joined the network        {joined:>12,.1f} km")
    print(f"  ...became an island          {islanded:>12,.1f} km")
    print(f"  ...below min_network_size    {stranded:>12,.1f} km")
    if abs(blocked) > 0.05:
        # Promoted to railway=rail and then blocked by the profile anyway —
        # non-1435 gauge, or service=yard/spur. Usually a lifted attribute
        # doing its job rather than a mistake.
        print(f"  ...promoted but unroutable   {blocked:>12,.1f} km")
    lost = promoted - joined - islanded - stranded - blocked
    if abs(lost) > 0.05:
        print(
            f"  ...left the map entirely     {lost:>12,.1f} km  <-- a rule "
            "promoted to a value that is neither routable nor planned"
        )
    print()

    if promoted > 0.05 and joined / promoted < 0.5:
        print(
            "More than half the promoted track did not join the routable "
            "network. That is the missing-junction failure: run\n"
            "  osm-survey connectors <target>\n"
            "and weld the real ones. Until then those corridors are deleted "
            "at import and no route will change."
        )

    per_project = other.get("project_km") or {}
    if per_project:
        print(f"{'project':<28} {'network':>10} {'island':>10} {'pruned':>10}")
        for project, classes in per_project.items():
            print(
                f"{project:<28} {classes.get('network', 0.0):>10,.1f} "
                f"{classes.get('island', 0.0):>10,.1f} "
                f"{classes.get('pruned', 0.0):>10,.1f}"
            )
