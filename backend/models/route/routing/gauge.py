"""
gauge.py
========
Track-gauge resolution for a trip — which of the per-gauge routing profiles
(docker/config.yml) a stop list must be routed on, decided BEFORE any router
call so an impossible pairing fails as a domain answer, not a snap error.

The rule
--------
Every stop carries the gauges its usable tracks offer (StopInfrastructure.
gauges_mm, from stop pipeline step 8). A trip's gauge is the intersection of
those sets across its stops, further intersected with what the composition's
stock can run on (today: everything — see composition_gauges()):

  - Kyiv {1520} ∩ Lviv {1520}                        → 1520
  - Berlin {1435} ∩ Wien {1435}                      → 1435
  - Kaunas {1435, 1520} ∩ Warszawa {1435}            → 1435
  - Kyiv {1520} ∩ Warszawa {1435}                    → ∅ → GaugeMismatchError

UNKNOWN DOES NOT CONSTRAIN. A stop with gauges_mm=None (step 8 found no
usable tracks nearby — coordinate defects, untagged OSM, war damage) is
excluded from the intersection rather than assumed standard-gauge: the
catalog's NULLs include Ukrainian stops, and defaulting them to 1435 would
422 perfectly valid 1520 trips with a message blaming the wrong stop. The
NULLs are queued for hand-correction (catalog work, 2026-08-27); until then
a NULL stop rides on whatever gauge its known co-stops resolve. Only when
EVERY stop is unknown does STANDARD_GAUGE_MM apply — there is nothing else
to go on, and it keeps composition-less callers (route_geometry()'s
synthetic ONTD stops) on today's behaviour.

Ties prefer STANDARD_GAUGE_MM: a trip entirely over dual-gauge border stops
(Kaunas–Mockava) is a standard-gauge trip unless something forces it broad —
the European mainline network is where every through-service continues.
Any other tie resolves to the smallest gauge, only for determinism; no real
stop pair currently produces one.

Strictness split
----------------
resolve_trip_gauge() is permissive about NULL (above). stop_supports_gauge()
is STRICT — unknown is not support. It guards the auto-stop candidate
filter (timetable._find_nearby_candidates), where the question is inverted:
not "can this trip run at all" but "may this extra stop be added to it".
Adding a gauge-unknown stop to a healthy trip risks an unsnappable route for
a stop nobody asked for; skipping it costs one suggestion.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

from models.route.model import STANDARD_GAUGE_MM, SUPPORTED_GAUGES_MM

if TYPE_CHECKING:  # import cycle guard only — nothing here is read at runtime
    from models.params import Composition, StopInfrastructure


class GaugeMismatchError(ValueError):
    """No single track gauge serves every stop of a trip.

    A subclass of ValueError so an unaware caller still gets the generic
    422 domain_error path; api/proposal_calc.py catches it FIRST and
    answers 422 gauge_mismatch with conflicting_stops so the frontend can
    mark the offending stops instead of printing a sentence.

    conflicting_stops: {stop_id: sorted gauges or None} for every stop of
    the trip — the full picture, not only the minority side, because which
    side is "wrong" is the user's call, not the model's.
    """

    def __init__(self, message: str, conflicting_stops: dict[str, list[int] | None]):
        super().__init__(message)
        self.conflicting_stops = conflicting_stops


def composition_gauges(composition: "Composition | None") -> frozenset[int] | None:
    """Gauges this composition's stock can run on — None means ALL.

    Deliberately trivial today: the composition catalog does not yet model
    gauge capability (every calibrated composition is standard-gauge stock,
    and 1520/1524 concepts are exactly what the tool should help evaluate,
    not refuse). This function is the seam where that lands — a
    gauges_mm-style column on composition_types flows in here and nothing
    else changes. See OPEN_TODOS["composition_gauge_capability"].
    """
    return None


def resolve_trip_gauge(
    stops: Iterable["StopInfrastructure"],
    composition: "Composition | None" = None,
) -> int:
    """The single gauge_mm this stop list is routed on.

    Raises GaugeMismatchError when the stops' known gauge sets have no
    common member (or none the composition can run) — before any router
    call, so the user learns "Kyiv is 1520, Warszawa is 1435" instead of
    "point 0 could not be snapped".

    Raises ValueError on a resolved gauge outside SUPPORTED_GAUGES_MM —
    catalog data naming a gauge no routing profile exists for (config.yml
    contract); nothing a user can cause.
    """
    stop_list = list(stops)
    known = [s for s in stop_list if s.gauges_mm]
    if not known:
        return STANDARD_GAUGE_MM

    common = frozenset(known[0].gauges_mm)
    for stop in known[1:]:
        common &= frozenset(stop.gauges_mm)

    allowed = composition_gauges(composition)
    if allowed is not None:
        common &= allowed

    if not common:
        gauges_by_stop = {
            s.stop_id: sorted(s.gauges_mm) if s.gauges_mm else None for s in stop_list
        }
        described = ", ".join(
            f"{s.stop_name} ({'/'.join(map(str, sorted(s.gauges_mm)))} mm)"
            if s.gauges_mm
            else f"{s.stop_name} (gauge unknown)"
            for s in stop_list
        )
        raise GaugeMismatchError(
            f"No single track gauge serves every stop of this trip: {described}. "
            "Networks of different gauge are not connected for through "
            "running — split the route at a border station that carries "
            "both gauges.",
            conflicting_stops=gauges_by_stop,
        )

    gauge_mm = STANDARD_GAUGE_MM if STANDARD_GAUGE_MM in common else min(common)
    if gauge_mm not in SUPPORTED_GAUGES_MM:
        raise ValueError(
            f"Resolved track gauge {gauge_mm} mm has no routing profile — "
            f"supported: {', '.join(map(str, SUPPORTED_GAUGES_MM))} mm "
            "(models/route/routing/docker/config.yml)."
        )
    return gauge_mm


def stop_supports_gauge(stop: "StopInfrastructure", gauge_mm: int) -> bool:
    """STRICT: does this stop's catalog data say it offers gauge_mm track?

    Unknown (gauges_mm=None) is False — see the module docstring's
    strictness split. resolve_trip_gauge() stays the permissive side.
    """
    return bool(stop.gauges_mm) and gauge_mm in stop.gauges_mm
