"""
Unit tests for RailRouter.build_custom_model() and route_variant_key() —
the resolved GraphHopper custom model, rule by rule. No DB, no Docker: a
RailRouter over an empty CountryIndex opens no connection, and the model
is built entirely from constants and geometry.

The routed end (a trip actually avoiding unelectrified track) is not
asserted anywhere: it depends on OSM tagging in the imported graph, which
is not a property of this source tree. What is asserted here is the
contract every routed request rides on.

Also guards the profile chain in docker/config.yml, because half of what
is in force comes from OpenRailRouting's BUILT-IN custom models rather
than from custom_models/ — see routing/README.md.
"""

from pathlib import Path

import pytest
import yaml

from models.route.model import (
    BLOCKED_COUNTRIES,
    HSR_AVOIDANCE_PRIORITY_FACTOR,
    HSR_TRACK_SPEED_SANITY_MAX_KMH,
    HSR_TRACK_SPEED_THRESHOLD_KMH,
    NON_ELECTRIFIED_PRIORITY_FACTOR,
    SUPPORTED_GAUGES_MM,
)
from models.route.routing.rail_router import (
    CountryIndex,
    RailRouter,
    route_variant_key,
)

_CONFIG_YML = (
    Path(__file__).resolve().parents[1] / "models/route/routing/docker/config.yml"
)

# A unit square per country — enough for get_largest_polygon() and
# get_blocking_rings() to return a ring; the coordinates never matter.
_SQUARES = ("DE", "FR", "IT") + BLOCKED_COUNTRIES


def _square(index: int) -> dict:
    x = float(index)
    return {
        "type": "Polygon",
        "coordinates": [[[x, 0.0], [x + 1, 0.0], [x + 1, 1.0], [x, 1.0], [x, 0.0]]],
    }


@pytest.fixture(scope="module")
def router() -> RailRouter:
    geometries = [(cc, _square(i)) for i, cc in enumerate(_SQUARES)]
    return RailRouter(CountryIndex(geometries))


@pytest.fixture(scope="module")
def bare_router() -> RailRouter:
    """No polygons at all — the degraded deployment the blocked-country
    warning path describes. Isolates rules that must survive it."""
    return RailRouter(CountryIndex([]))


def _rules(model: dict, block: str) -> list[dict]:
    return model.get(block, [])


def _electrification_rules(model: dict) -> list[dict]:
    return [r for r in _rules(model, "priority") if "electrified" in r.get("if", "")]


def _config() -> dict:
    with _CONFIG_YML.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)["graphhopper"]


@pytest.fixture(scope="module")
def profiles() -> list[dict]:
    return _config()["profiles"]


class TestElectrification:
    """The one rule with no condition attached to it anywhere."""

    @pytest.mark.parametrize(
        "max_speed,avoid_hsr",
        [
            (None, None),  # route_geometry()
            (160, None),  # simpleRouting
            (160, {"DE": True, "FR": True}),  # fullRouting, global HSR ban
            (160, {"DE": True, "FR": False}),  # fullRouting, mixed HSR
            (230, {"DE": False, "FR": False}),  # fullRouting, HSR allowed
        ],
    )
    def test_present_in_every_mode(self, router, max_speed, avoid_hsr):
        model = router.build_custom_model(max_speed, avoid_hsr)
        assert _electrification_rules(model) == [
            {
                "if": "electrified == NO",
                "multiply_by": str(NON_ELECTRIFIED_PRIORITY_FACTOR),
            }
        ]

    def test_survives_missing_country_polygons(self, bare_router):
        # Blocked-country rules degrade to nothing without geometry; the
        # electrification rule has no geometry to lose.
        model = bare_router.build_custom_model(None, None)
        assert len(_electrification_rules(model)) == 1

    def test_matches_tagged_no_never_untagged(self, router):
        # UNSET is GraphHopper's "no electrified tag on this way". Unknown
        # is not forbidden — the same discipline the HSR sanity bound
        # enforces for untagged maxspeed.
        condition = _electrification_rules(router.build_custom_model(None, None))[0][
            "if"
        ]
        assert "UNSET" not in condition
        assert "!=" not in condition

    def test_is_a_preference_not_a_veto(self, router):
        # Softer than HSR avoidance by an order of magnitude, on purpose:
        # HSR avoidance encodes a permission, this encodes a preference.
        assert 0 < NON_ELECTRIFIED_PRIORITY_FACTOR < 1
        assert NON_ELECTRIFIED_PRIORITY_FACTOR > HSR_AVOIDANCE_PRIORITY_FACTOR


class TestModelIsAlwaysBuilt:
    """Since 0.9.31 build_custom_model() never returns None — the reason
    every mode, route_geometry() included, routes LM rather than CH."""

    def test_never_none(self, router, bare_router):
        for r in (router, bare_router):
            assert isinstance(r.build_custom_model(None, None), dict)

    def test_priority_block_always_emitted(self, bare_router):
        assert bare_router.build_custom_model(None, None)["priority"]


class TestSpeedRules:
    def test_cap_applied_when_given(self, router):
        speed = _rules(router.build_custom_model(160, None), "speed")
        assert {"if": "true", "limit_to": "160"} in speed

    def test_no_cap_without_composition(self, router):
        speed = _rules(router.build_custom_model(None, None), "speed")
        assert not [r for r in speed if r.get("limit_to")]

    def test_blocked_countries_are_hard_zero(self, router):
        speed = _rules(router.build_custom_model(160, None), "speed")
        blocked = [r for r in speed if r.get("multiply_by") == "0"]
        assert len(blocked) >= len(BLOCKED_COUNTRIES)
        assert all(r["if"].startswith("in_blocked") for r in blocked)

    def test_no_speed_block_at_all_without_polygons_or_cap(self, bare_router):
        assert "speed" not in bare_router.build_custom_model(None, None)


class TestHsrAvoidance:
    def test_absent_when_nobody_disallows(self, router):
        model = router.build_custom_model(160, {"DE": False, "FR": False})
        assert not [r for r in model["priority"] if "max_speed" in r["if"]]

    def test_global_rule_when_everybody_disallows(self, router):
        model = router.build_custom_model(160, {"DE": True, "FR": True})
        hsr = [r for r in model["priority"] if "max_speed" in r["if"]]
        assert hsr == [
            {
                "if": (
                    f"max_speed > {HSR_TRACK_SPEED_THRESHOLD_KMH} "
                    f"&& max_speed < {HSR_TRACK_SPEED_SANITY_MAX_KMH}"
                ),
                "multiply_by": str(HSR_AVOIDANCE_PRIORITY_FACTOR),
            }
        ]
        # A global rule needs no rings — only the blocked countries do.
        area_ids = {f["id"] for f in model["areas"]["features"]}
        assert not [a for a in area_ids if a.startswith("hsr")]

    def test_area_scoped_rules_when_permissions_are_mixed(self, router):
        model = router.build_custom_model(160, {"DE": True, "FR": False, "IT": True})
        hsr = [r for r in model["priority"] if "max_speed" in r["if"]]
        assert {r["if"].split(" && ")[0] for r in hsr} == {"in_hsrde", "in_hsrit"}
        area_ids = {f["id"] for f in model["areas"]["features"]}
        assert {"hsrde", "hsrit"} <= area_ids
        assert "hsrfr" not in area_ids


class TestVariantKey:
    def test_stable_for_the_same_model(self, router):
        model = router.build_custom_model(160, {"DE": True})
        assert route_variant_key("night_train", model) == route_variant_key(
            "night_train", model
        )

    def test_profile_is_part_of_the_key(self, router):
        model = router.build_custom_model(160, None)
        keys = {
            route_variant_key(f"night_train_{g}", model) for g in SUPPORTED_GAUGES_MM
        }
        assert len(keys) == len(SUPPORTED_GAUGES_MM)

    def test_differs_when_the_model_differs(self, router):
        capped = router.build_custom_model(160, None)
        uncapped = router.build_custom_model(230, None)
        assert route_variant_key("night_train", capped) != route_variant_key(
            "night_train", uncapped
        )


class TestProfileChainContract:
    """docker/config.yml wires four custom models per profile, and only two
    of them live in custom_models/. rail.json is OpenRailRouting's built-in
    and carries `!rail_access || railway_class != RAIL -> priority 0` —
    which is what already excludes trams, subways, light rail and narrow
    gauge from every profile, snapping included. Dropping it from the chain
    would silently re-open the urban tram network to night trains."""

    def test_one_profile_per_supported_gauge(self, profiles):
        assert len(profiles) == len(SUPPORTED_GAUGES_MM)

    def test_rail_json_leads_every_chain(self, profiles):
        assert all(p["custom_model_files"][0] == "rail.json" for p in profiles)

    def test_shared_night_train_model_follows_it(self, profiles):
        assert all(p["custom_model_files"][1] == "night_train.json" for p in profiles)

    def test_electrified_is_encoded_in_the_graph(self):
        # The rule this module tests is request-time, but it can only be
        # evaluated because `electrified` survived the import. Losing it
        # from graph.encoded_values would fail every routing call.
        encoded = _config()["graph.encoded_values"]
        assert "electrified" in {v.strip() for v in encoded.split(",")}
