"""Gap deduplication.

Both failure modes here were observed on real data, in opposite directions:
too little dedup drowns the review list, too much hides welds a corridor needs.
"""

from __future__ import annotations

from osm_survey.gaps import Gap, _dedupe


def _gap(a: int, b: int, *, km: float = 1.0, m: float = 20.0) -> Gap:
    return Gap(
        node_a=a,
        node_b=b,
        component_a=1,
        component_b=2,
        distance_m=m,
        bearing_error=5.0,
        km_a=km,
        km_b=km,
        lat_a=48.0,
        lon_a=16.0,
        lat_b=48.0,
        lon_b=16.0,
    )


def test_double_track_junction_yields_two_connectors_not_four():
    # Observed on -d austria: nodes 4912912760/61 face 4912912764/65, every
    # pair within the radius and pointing at its opposite, so the raw output
    # was the 2x2 cross product of one place.
    raw = [
        _gap(61, 65, m=25.3),
        _gap(60, 65, m=25.4),
        _gap(61, 64, m=25.5),
        _gap(60, 64, m=26.1),
    ]
    out = _dedupe(raw)
    assert len(out) == 2, "a double-track junction needs one connector per track"
    assert {(g.node_a, g.node_b) for g in out} == {(61, 65), (60, 64)}


def test_a_corridor_severed_twice_reveals_both_welds():
    # The opposite failure, and the one the previous tool had: deduplicating
    # per component pair collapsed these to the closest, so fixing one weld
    # took another full pipeline run to reveal the next.
    raw = [_gap(1, 2, km=50.0, m=10.0), _gap(3, 4, km=50.0, m=40.0)]
    assert len(_dedupe(raw)) == 2


def test_the_best_gap_for_a_node_wins():
    # Input arrives sorted by stranded track, then distance. The first entry
    # claiming a node is therefore the most valuable one it appears in.
    raw = [_gap(1, 2, km=50.0), _gap(1, 3, km=0.2)]
    out = _dedupe(raw)
    assert len(out) == 1
    assert out[0].node_b == 2


def test_orphan_km_is_the_smaller_side():
    # Ranking by how much track the gap strands, which is the side that gets
    # cut off — not the mainline it fails to reach.
    gap = Gap(
        node_a=1,
        node_b=2,
        component_a=1,
        component_b=2,
        distance_m=10.0,
        bearing_error=1.0,
        km_a=5000.0,
        km_b=12.2,
        lat_a=48.0,
        lon_a=16.0,
        lat_b=48.0,
        lon_b=16.0,
    )
    assert gap.orphan_km == 12.2
