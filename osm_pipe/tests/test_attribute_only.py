"""A project that changes attributes without promoting anything.

Electrifying a corridor that is already `railway=rail` is the real case. It has
no promotion to key off, so the `set`/`default` rules cannot match on the
`ntn:project` marker the way they normally do — they have to fall back to the
project's own scope, and refuse to run without one.

Without that fallback the rules match nothing and say nothing about it, which
is exactly the silent no-op this pipeline exists to avoid.
"""

from __future__ import annotations

import datetime as dt

import pytest

from osm_pipe.changes import Scope, expand, parse_changes
from osm_pipe.geo import BBox
from osm_pipe.transform import apply_rules

OPENING = dt.date(2029, 12, 31)


def _expand(changes, scope):
    return expand(
        project_id="dk-electrification",
        specs=parse_changes(changes, project_id="dk-electrification"),
        scope=scope,
        opening=OPENING,
    )


def test_attribute_only_project_uses_its_own_scope():
    rules = _expand(
        [{"default": {"electrified": "contact_line"}}],
        Scope(ways=frozenset({42})),
    )
    tags = {"railway": "rail"}
    inside = apply_rules(tags, tuple(rules), "w", obj_id=42)
    outside = apply_rules(tags, tuple(rules), "w", obj_id=43)
    assert inside["electrified"] == "contact_line"
    assert "electrified" not in outside


def test_attribute_only_respects_existing_data():
    rules = _expand(
        [{"default": {"electrified": "contact_line"}}],
        Scope(ways=frozenset({42})),
    )
    out = apply_rules(
        {"railway": "rail", "electrified": "no"}, tuple(rules), "w", obj_id=42
    )
    assert out["electrified"] == "no", "`default` must not overwrite OSM"


def test_attribute_only_with_bbox_scope():
    rules = _expand(
        [{"set": {"maxspeed": "200"}}],
        Scope(bbox=BBox(54.0, 8.0, 58.0, 13.0)),
    )
    tags = {"railway": "rail"}
    assert (
        apply_rules(tags, tuple(rules), "w", points=[(56.0, 10.0)])["maxspeed"] == "200"
    )
    assert "maxspeed" not in apply_rules(tags, tuple(rules), "w", points=[(48.0, 9.0)])


def test_attribute_only_refuses_to_run_globally():
    # Unscoped, this would rewrite every railway=rail way in the extract.
    with pytest.raises(ValueError, match="needs a scope"):
        _expand([{"set": {"electrified": "contact_line"}}], Scope())


def test_attribute_only_project_is_still_auditable():
    # A route over this project's track must carry a trace of it, or the whole
    # point of dated, attributable networks is lost.
    rules = _expand(
        [{"default": {"electrified": "contact_line"}}],
        Scope(ways=frozenset({42})),
    )
    out = apply_rules({"railway": "rail"}, tuple(rules), "w", obj_id=42)
    assert out["ntn:project"] == "dk-electrification"
    assert out["ntn:opening"] == "2029-12-31"


def test_drop_oneway_without_a_promotion_is_an_error():
    # It keys off the marker a promotion writes, so alone it would match
    # nothing and report nothing.
    with pytest.raises(ValueError, match="needs a `promote:`"):
        _expand(["drop_oneway"], Scope(ways=frozenset({42})))


def test_promoting_project_still_keys_off_the_marker():
    # With a promotion present the fallback must NOT kick in: keying off the
    # marker is tighter than the scope, so a neighbouring project's ways
    # inside the same bbox stay untouched.
    rules = expand(
        project_id="p",
        specs=parse_changes(
            [{"promote": "construction"}, {"default": {"maxspeed": "200"}}],
            project_id="p",
        ),
        scope=Scope(bbox=BBox(-90, -180, 90, 180)),
        opening=OPENING,
    )
    already_rail = {"railway": "rail"}
    out = apply_rules(already_rail, tuple(rules), "w", points=[(50.0, 10.0)])
    assert "maxspeed" not in out
