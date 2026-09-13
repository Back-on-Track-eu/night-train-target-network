"""
test_22_expert_timetable.py
===========================
Content + contract tests for expert timetable mode (ROUTE_BUILDER 0.9.32) —
the request's optional `expert_timetable` block: a manual first departure
(pinned or shifted) and manual per-leg minutes.

Sits with the route-content family (test_20/test_21) rather than the calc
API's structural file: everything asserted here is about what the override
does to the timetable a route carries, not about the response envelope.

Covers:
  - Absent block: the timetable is byte-identical to the automatic one
  - "absolute": the trip departs exactly there; every later stop shifts by
    the same delta; a different composition (different duration) does not
    move it
  - "shift": the departure is the automatic value plus the delta, and DOES
    move when the automatic value does
  - segment_addons: land on the named leg only, grow that leg's elapsed
    time and every later stop time by exactly N, leave earlier stops alone
  - Mirroring: the return direction pads the reversed pair by default; an
    explicit return block wins
  - The resolved-request echo is canonical (add-on order irrelevant)
  - Validation: negative/zero add_min, non-adjacent pair, duplicate pair,
    unknown mode, unknown keys, over-cap values → 400

Every request here pins auto_stop_addition="off" unless the test is about
the interaction with it: an auto-added stop changes the stop list, which is
exactly what the drop rule is about, and would otherwise make the
leg-by-leg assertions non-deterministic (see test_20's module docstring).
"""

from tests.conftest import STOPS_BERLIN_DRESDEN_WIEN
from tests.helpers import compute, post_member, stop_times, trip_by_direction

BASE = {"stops": STOPS_BERLIN_DRESDEN_WIEN, "auto_stop_addition": "off"}

# The two legs of the standard 3-stop corridor, in outbound travel order.
LEG_1 = (STOPS_BERLIN_DRESDEN_WIEN[0], STOPS_BERLIN_DRESDEN_WIEN[1])
LEG_2 = (STOPS_BERLIN_DRESDEN_WIEN[1], STOPS_BERLIN_DRESDEN_WIEN[2])


def _addon(pair: tuple[str, str], minutes: int) -> dict:
    return {"from_stop_id": pair[0], "to_stop_id": pair[1], "add_min": minutes}


def _expert(outbound: dict | None = None, return_block: dict | None = None) -> dict:
    block: dict = {}
    if outbound is not None:
        block["outbound"] = outbound
    if return_block is not None:
        block["return"] = return_block
    return block


def _departure(trip: dict) -> int:
    return trip["segments"][0]["from_stop"]["departure_time_min"]


def _elapsed(seg: dict) -> int:
    """Stop-to-stop elapsed time of one leg, straight off the timetable."""
    return seg["to_stop"]["arrival_time_min"] - seg["from_stop"]["departure_time_min"]


def _post(api_base: str, body: dict, timeout: int = 90):
    """The wire view of a member request — a 1×1 family — for the
    validation cases; content cases use compute() in-process."""
    return post_member(api_base, body, timeout=timeout)


# =============================================================================
# The block is optional and inert
# =============================================================================


class TestNoOverrides:
    def test_absent_block_is_the_automatic_timetable(self, api_base):
        """The whole feature's compatibility claim: sending nothing changes
        nothing. Compared stop-by-stop rather than by duration, so a
        compensating pair of errors can't pass."""
        automatic = compute(api_base, **BASE)["route"]
        explicit_none = compute(api_base, **BASE, expert_timetable=None)["route"]
        for direction in (0, 1):
            a = stop_times(trip_by_direction(automatic, direction))
            b = stop_times(trip_by_direction(explicit_none, direction))
            assert [(s["arrival_time_min"], s["departure_time_min"]) for s in a] == [
                (s["arrival_time_min"], s["departure_time_min"]) for s in b
            ]

    def test_addon_time_min_is_zero_everywhere(self, api_base):
        route = compute(api_base, **BASE)["route"]
        for direction in (0, 1):
            trip = trip_by_direction(route, direction)
            assert all(seg["addon_time_min"] == 0 for seg in trip["segments"])
            assert trip["general_parameters"]["manual_addon_min"] == 0


# =============================================================================
# Departure override
# =============================================================================


class TestDepartureOverride:
    def test_absolute_departs_exactly_there(self, api_base):
        automatic = compute(api_base, **BASE)["route"]
        auto_dep = _departure(trip_by_direction(automatic, 0))
        pinned = auto_dep + 47

        route = compute(
            api_base,
            **BASE,
            expert_timetable=_expert(
                outbound={"departure": {"mode": "absolute", "time_min": pinned}}
            ),
        )["route"]
        trip = trip_by_direction(route, 0)
        assert _departure(trip) == pinned

    def test_absolute_shifts_every_stop_by_the_same_delta(self, api_base):
        """A departure override moves the trip on the clock; it must not
        change any leg's own duration. Dwell can legitimately change when a
        stop crosses a night threshold, so the invariant asserted is on the
        LEG elapsed times, not on the stop times themselves."""
        automatic = compute(api_base, **BASE)["route"]
        auto_trip = trip_by_direction(automatic, 0)
        auto_dep = _departure(auto_trip)

        route = compute(
            api_base,
            **BASE,
            expert_timetable=_expert(
                outbound={"departure": {"mode": "absolute", "time_min": auto_dep - 60}}
            ),
        )["route"]
        trip = trip_by_direction(route, 0)
        assert _departure(trip) == auto_dep - 60
        assert [_elapsed(s) for s in trip["segments"]] == [
            _elapsed(s) for s in auto_trip["segments"]
        ]

    def test_shift_is_relative_to_the_automatic_value(self, api_base):
        automatic = compute(api_base, **BASE)["route"]
        auto_dep = _departure(trip_by_direction(automatic, 0))

        route = compute(
            api_base,
            **BASE,
            expert_timetable=_expert(
                outbound={"departure": {"mode": "shift", "shift_min": -35}}
            ),
        )["route"]
        assert _departure(trip_by_direction(route, 0)) == auto_dep - 35

    def test_absolute_survives_a_longer_trip_while_shift_moves(self, api_base):
        """The one behavioural difference between the two modes. Adding
        minutes to a leg lengthens the trip, which re-centres the automatic
        mirror around 02:30 — a pinned departure ignores that, a shifted one
        follows it."""
        automatic = compute(api_base, **BASE)["route"]
        auto_dep = _departure(trip_by_direction(automatic, 0))

        padded_auto = compute(
            api_base,
            **BASE,
            expert_timetable=_expert(outbound={"segment_addons": [_addon(LEG_1, 40)]}),
        )["route"]
        padded_dep = _departure(trip_by_direction(padded_auto, 0))
        assert padded_dep != auto_dep, (
            "a 40-minute-longer trip should re-centre on MIRROR_MIN — if this "
            "fails the rest of the test proves nothing"
        )

        pinned = compute(
            api_base,
            **BASE,
            expert_timetable=_expert(
                outbound={
                    "departure": {"mode": "absolute", "time_min": auto_dep},
                    "segment_addons": [_addon(LEG_1, 40)],
                }
            ),
        )["route"]
        shifted = compute(
            api_base,
            **BASE,
            expert_timetable=_expert(
                outbound={
                    "departure": {"mode": "shift", "shift_min": 0},
                    "segment_addons": [_addon(LEG_1, 40)],
                }
            ),
        )["route"]
        assert _departure(trip_by_direction(pinned, 0)) == auto_dep
        assert _departure(trip_by_direction(shifted, 0)) == padded_dep

    def test_return_departure_is_never_mirrored(self, api_base):
        """An outbound pin says nothing about when the return leaves — the
        return keeps its own automatic departure."""
        automatic = compute(api_base, **BASE)["route"]
        auto_return_dep = _departure(trip_by_direction(automatic, 1))
        auto_out_dep = _departure(trip_by_direction(automatic, 0))

        route = compute(
            api_base,
            **BASE,
            expert_timetable=_expert(
                outbound={
                    "departure": {"mode": "absolute", "time_min": auto_out_dep - 90}
                }
            ),
        )["route"]
        assert _departure(trip_by_direction(route, 1)) == auto_return_dep


# =============================================================================
# Per-leg add-ons
# =============================================================================


class TestSegmentAddons:
    def test_addon_lands_on_its_own_leg_only(self, api_base):
        automatic = trip_by_direction(compute(api_base, **BASE)["route"], 0)
        route = compute(
            api_base,
            **BASE,
            expert_timetable=_expert(outbound={"segment_addons": [_addon(LEG_2, 12)]}),
        )["route"]
        trip = trip_by_direction(route, 0)

        assert [s["addon_time_min"] for s in trip["segments"]] == [0, 12]
        assert trip["general_parameters"]["manual_addon_min"] == 12
        assert _elapsed(trip["segments"][0]) == _elapsed(automatic["segments"][0])
        assert _elapsed(trip["segments"][1]) == _elapsed(automatic["segments"][1]) + 12

    def test_addon_grows_the_trip_duration_by_exactly_its_minutes(self, api_base):
        automatic = trip_by_direction(compute(api_base, **BASE)["route"], 0)
        route = compute(
            api_base,
            **BASE,
            expert_timetable=_expert(
                outbound={"segment_addons": [_addon(LEG_1, 7), _addon(LEG_2, 5)]}
            ),
        )["route"]
        trip = trip_by_direction(route, 0)
        assert (
            trip["general_parameters"]["route_duration_min"]
            == automatic["general_parameters"]["route_duration_min"] + 12
        )

    def test_leg_time_still_equals_its_components(self, api_base):
        """The invariant test_20 asserts for every route, re-checked with a
        manual add-on in play: elapsed = driving + dynamics + buffer + slack
        + addon."""
        route = compute(
            api_base,
            **BASE,
            expert_timetable=_expert(outbound={"segment_addons": [_addon(LEG_1, 9)]}),
        )["route"]
        for direction in (0, 1):
            for seg in trip_by_direction(route, direction)["segments"]:
                assert _elapsed(seg) == (
                    seg["driving_time_min"]
                    + seg["dynamics_time_min"]
                    + seg["buffer_time_min"]
                    + seg["slack_time_min"]
                    + seg["addon_time_min"]
                )

    def test_return_mirrors_outbound_by_default(self, api_base):
        route = compute(
            api_base,
            **BASE,
            expert_timetable=_expert(outbound={"segment_addons": [_addon(LEG_1, 11)]}),
        )["route"]
        return_trip = trip_by_direction(route, 1)
        # Return runs the reversed stop list, so outbound's first leg is the
        # return's last.
        assert [s["addon_time_min"] for s in return_trip["segments"]] == [0, 11]
        last = return_trip["segments"][-1]
        assert (last["from_stop"]["stop_id"], last["to_stop"]["stop_id"]) == (
            LEG_1[1],
            LEG_1[0],
        )

    def test_explicit_return_block_wins_over_mirroring(self, api_base):
        route = compute(
            api_base,
            **BASE,
            expert_timetable=_expert(
                outbound={"segment_addons": [_addon(LEG_1, 11)]},
                return_block={
                    "segment_addons": [_addon((LEG_2[1], LEG_2[0]), 4)],
                },
            ),
        )["route"]
        assert [
            s["addon_time_min"] for s in trip_by_direction(route, 0)["segments"]
        ] == [
            11,
            0,
        ]
        # Return: its own first leg (Wien → Dresden) padded by 4, and
        # outbound's 11 minutes NOT mirrored in.
        assert [
            s["addon_time_min"] for s in trip_by_direction(route, 1)["segments"]
        ] == [
            4,
            0,
        ]


# =============================================================================
# Resolved-request echo (the compute cache key)
# =============================================================================


class TestResolvedRequest:
    def test_echo_is_canonical_regardless_of_addon_order(self, api_base):
        """Two bodies that mean the same thing must resolve to the same
        request — otherwise they occupy two cache entries holding one
        result."""
        forward = compute(
            api_base,
            **BASE,
            expert_timetable=_expert(
                outbound={"segment_addons": [_addon(LEG_1, 3), _addon(LEG_2, 6)]}
            ),
        )["request"]
        reversed_order = compute(
            api_base,
            **BASE,
            expert_timetable=_expert(
                outbound={"segment_addons": [_addon(LEG_2, 6), _addon(LEG_1, 3)]},
                return_block={"mirror_outbound": True},
            ),
        )["request"]
        assert forward["expert_timetable"] == reversed_order["expert_timetable"]

    def test_echo_is_null_when_nothing_is_overridden(self, api_base):
        response = compute(api_base, **BASE, expert_timetable={"outbound": {}})
        assert response["request"]["expert_timetable"] is None


# =============================================================================
# Validation
# =============================================================================


class TestValidation:
    def test_zero_and_negative_addons_are_rejected(self, api_base):
        for minutes in (0, -5):
            resp = _post(
                api_base,
                {
                    **BASE,
                    "expert_timetable": _expert(
                        outbound={"segment_addons": [_addon(LEG_1, minutes)]}
                    ),
                },
            )
            assert resp.status_code == 400, minutes
            assert "add_min" in resp.text

    def test_non_adjacent_pair_is_rejected(self, api_base):
        """Berlin → Wien skips Dresden: a real pair of stops, but not a leg
        of this route."""
        resp = _post(
            api_base,
            {
                **BASE,
                "expert_timetable": _expert(
                    outbound={
                        "segment_addons": [
                            _addon(
                                (
                                    STOPS_BERLIN_DRESDEN_WIEN[0],
                                    STOPS_BERLIN_DRESDEN_WIEN[2],
                                ),
                                5,
                            )
                        ]
                    }
                ),
            },
        )
        assert resp.status_code == 400
        assert "not a leg" in resp.text

    def test_duplicate_pair_is_rejected(self, api_base):
        resp = _post(
            api_base,
            {
                **BASE,
                "expert_timetable": _expert(
                    outbound={"segment_addons": [_addon(LEG_1, 3), _addon(LEG_1, 4)]}
                ),
            },
        )
        assert resp.status_code == 400
        assert "repeats" in resp.text

    def test_unknown_departure_mode_is_rejected(self, api_base):
        resp = _post(
            api_base,
            {
                **BASE,
                "expert_timetable": _expert(
                    outbound={"departure": {"mode": "relative", "time_min": 1200}}
                ),
            },
        )
        assert resp.status_code == 400
        assert "departure.mode" in resp.text

    def test_over_cap_shift_is_rejected(self, api_base):
        resp = _post(
            api_base,
            {
                **BASE,
                "expert_timetable": _expert(
                    outbound={"departure": {"mode": "shift", "shift_min": 5000}}
                ),
            },
        )
        assert resp.status_code == 400
        assert "shift_min" in resp.text

    def test_unknown_keys_are_rejected(self, api_base):
        resp = _post(
            api_base,
            {**BASE, "expert_timetable": {"outbund": {}}},
        )
        assert resp.status_code == 400
        assert "unknown keys" in resp.text

    def test_return_cannot_mirror_and_override_at_once(self, api_base):
        resp = _post(
            api_base,
            {
                **BASE,
                "expert_timetable": _expert(
                    outbound={"segment_addons": [_addon(LEG_1, 3)]},
                    return_block={
                        "mirror_outbound": True,
                        "segment_addons": [_addon((LEG_1[1], LEG_1[0]), 3)],
                    },
                ),
            },
        )
        assert resp.status_code == 400
        assert "mirror_outbound" in resp.text
