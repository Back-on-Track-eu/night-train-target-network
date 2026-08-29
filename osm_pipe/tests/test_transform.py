"""The rule engine, and the change expansion that feeds it.

No OSM file is touched: `apply_rules` is a pure function on a tag dict, which
is the whole reason the engine is worth keeping small.
"""

from __future__ import annotations

import datetime as dt

import pytest

from osm_pipe.changes import MARKER_PROJECT, Scope, expand, parse_changes
from osm_pipe.config import Rule
from osm_pipe.geo import BBox
from osm_pipe.transform import apply_rules, matches

OPENING = dt.date(2031, 12, 31)


# -- matcher semantics -----------------------------------------------------


def test_matcher_forms():
    tags = {"railway": "construction", "construction": "rail"}
    assert matches(tags, {"railway": "construction"})  # equals
    assert matches(tags, {"railway": ["rail", "construction"]})  # one of
    assert matches(tags, {"construction": True})  # key present
    assert matches(tags, {"service": False})  # key absent
    assert not matches(tags, {"railway": "rail"})
    assert not matches(tags, {"service": True})


def test_matcher_compares_as_string():
    # YAML turns an unquoted `maxspeed: 160` into an int.
    assert matches({"maxspeed": "160"}, {"maxspeed": 160})


# -- op order --------------------------------------------------------------


def test_default_loses_to_mapped_data():
    """The single most important property: real data always wins."""
    rule = Rule(
        types=("w",),
        when={"railway": "construction"},
        rename={"construction:gauge": "gauge"},
        default={"gauge": "1435"},
    )
    out = apply_rules(
        {"railway": "construction", "construction:gauge": "1000"}, (rule,), "w"
    )
    assert out["gauge"] == "1000", "the lift must beat the default"


def test_default_fills_only_when_absent():
    rule = Rule(
        types=("w",), when={"railway": "construction"}, default={"gauge": "1435"}
    )
    out = apply_rules({"railway": "construction"}, (rule,), "w")
    assert out["gauge"] == "1435"


def test_set_overwrites():
    rule = Rule(types=("w",), when={"railway": "construction"}, set={"usage": "main"})
    out = apply_rules({"railway": "construction", "usage": "branch"}, (rule,), "w")
    assert out["usage"] == "main"


def test_rules_chain():
    # Rule 2 matches on what rule 1 wrote. `drop_oneway` depends on this.
    promote = Rule(
        types=("w",),
        when={"railway": "construction"},
        set={"railway": "rail", "ntn:project": "p"},
    )
    drop = Rule(
        types=("w",), when={"ntn:project": "p", "oneway": "yes"}, unset=("oneway",)
    )
    out = apply_rules(
        {"railway": "construction", "oneway": "yes"}, (promote, drop), "w"
    )
    assert out["railway"] == "rail"
    assert "oneway" not in out


def test_input_is_not_mutated():
    tags = {"railway": "construction"}
    rule = Rule(types=("w",), when={"railway": "construction"}, set={"railway": "rail"})
    apply_rules(tags, (rule,), "w")
    assert tags == {"railway": "construction"}


# -- scoping ---------------------------------------------------------------


def test_way_scope_excludes_other_ways():
    rule = Rule(
        types=("w",),
        when={"railway": "construction"},
        set={"railway": "rail"},
        ways=frozenset({111}),
    )
    tags = {"railway": "construction"}
    assert apply_rules(tags, (rule,), "w", obj_id=111)["railway"] == "rail"
    assert apply_rules(tags, (rule,), "w", obj_id=222)["railway"] == "construction"


def test_bbox_scope_needs_points():
    rule = Rule(
        types=("w",),
        when={"railway": "construction"},
        set={"railway": "rail"},
        within=(BBox(54.0, 10.0, 55.0, 12.0),),
    )
    tags = {"railway": "construction"}
    inside = apply_rules(tags, (rule,), "w", points=[(54.5, 11.0)])
    outside = apply_rules(tags, (rule,), "w", points=[(48.0, 9.0)])
    assert inside["railway"] == "rail"
    assert outside["railway"] == "construction"


def test_way_scope_needs_no_location_index():
    rule = Rule(types=("w",), when={}, ways=frozenset({1}))
    assert not rule.scoped_by_location


def test_type_gate():
    rule = Rule(types=("w",), when={"railway": "construction"}, set={"railway": "rail"})
    out = apply_rules({"railway": "construction"}, (rule,), "n")
    assert out["railway"] == "construction"


# -- change expansion ------------------------------------------------------


def _expand(changes, scope=None):
    specs = parse_changes(changes, project_id="p")
    return expand(
        project_id="p",
        specs=specs,
        scope=scope or Scope(ways=frozenset({1})),
        opening=OPENING,
    )


def test_promote_handles_all_three_spellings():
    rules = _expand([{"promote": {"lifecycle": "construction", "untyped": True}}])
    assert len(rules) == 3

    prefixed = {
        "railway": "construction",
        "construction:railway": "rail",
        "construction:gauge": "1435",
    }
    short = {"railway": "construction", "construction": "rail"}
    untyped = {"railway": "construction"}
    for tags in (prefixed, short, untyped):
        out = apply_rules(tags, tuple(rules), "w", obj_id=1)
        assert out["railway"] == "rail", tags


def test_promote_lifts_the_namespace():
    rules = _expand([{"promote": "construction"}])
    out = apply_rules(
        {
            "railway": "construction",
            "construction:railway": "rail",
            "construction:gauge": "1435",
            "construction:electrified": "contact_line",
            "construction:voltage": "25000",
        },
        tuple(rules),
        "w",
        obj_id=1,
    )
    # Without the lift the edge has no gauge and no electrification: it
    # survives the profile by luck and reads as diesel to the energy model.
    assert out["electrified"] == "contact_line"
    assert out["voltage"] == "25000"
    assert "construction:gauge" not in out


def test_promote_writes_audit_markers():
    rules = _expand([{"promote": "construction"}])
    out = apply_rules(
        {"railway": "construction", "construction:railway": "rail"},
        tuple(rules),
        "w",
        obj_id=1,
    )
    assert out[MARKER_PROJECT] == "p"
    assert out["ntn:opening"] == "2031-12-31"
    assert out["ntn:change"] == "promote:construction"


def test_promote_refuses_light_rail():
    rules = _expand([{"promote": "construction"}])
    out = apply_rules(
        {"railway": "construction", "construction:railway": "light_rail"},
        tuple(rules),
        "w",
        obj_id=1,
    )
    # Promoting it would produce a value in neither the routable set nor the
    # planned set, so the way would vanish from the map entirely.
    assert out["railway"] == "construction"


def test_reopening_lifecycles_refuse_to_run_unscoped():
    with pytest.raises(ValueError, match="needs a scope"):
        _expand([{"promote": "disused"}], scope=Scope())


def test_construction_may_run_unscoped():
    rules = _expand([{"promote": "construction"}], scope=Scope())
    assert rules


def test_reopening_skips_service_track():
    rules = _expand([{"promote": "disused"}])
    yard = {"railway": "disused", "disused:railway": "rail", "service": "yard"}
    out = apply_rules(yard, tuple(rules), "w", obj_id=1)
    assert out["railway"] == "disused", "yards and sidings must stay out"


def test_drop_oneway_runs_after_promote_whatever_the_order():
    # Written in the wrong order on purpose: the phase order is fixed in code
    # so that a project author cannot silently produce a rule matching nothing.
    rules = _expand(["drop_oneway", {"promote": "construction"}])
    out = apply_rules(
        {"railway": "construction", "construction:railway": "rail", "oneway": "yes"},
        tuple(rules),
        "w",
        obj_id=1,
    )
    assert "oneway" not in out
    assert out["ntn:oneway-dropped"] == "yes"


def test_drop_oneway_only_touches_this_project():
    rules = _expand([{"promote": "construction"}, "drop_oneway"])
    other = {"railway": "rail", "oneway": "yes", MARKER_PROJECT: "somebody-else"}
    out = apply_rules(other, tuple(rules), "w", obj_id=1)
    assert out["oneway"] == "yes"


def test_unknown_change_is_an_error():
    with pytest.raises(ValueError, match="unknown change"):
        parse_changes(["teleport"], project_id="p")


def test_unknown_lifecycle_is_an_error():
    with pytest.raises(ValueError, match="cannot promote"):
        parse_changes([{"promote": "planned"}], project_id="p")
