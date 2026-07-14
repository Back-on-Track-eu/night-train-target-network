"""
dynamics.py
===========
Traction dynamics for the route model: the time a train loses at each stop
by braking to a halt and accelerating back to cruise speed — physics the
routing engine itself cannot provide (GraphHopper computes edge times as
distance / constant edge speed and has no vehicle model; a via-point adds
zero seconds, so without this correction every intermediate stop costs
only its dwell time — see CHANGELOG 0.9.7 in version.py).

Model
-----
Every RoutedLeg runs from a stop to a stop, so each leg contains exactly
one acceleration phase (out of the departure stop) and one braking phase
(into the arrival stop). Per leg, the surcharge over the router's
constant-cruise-speed time is:

  braking      — constant service deceleration TRACTION_BRAKE_DECELERATION_MS2
                 (rail braking is effectively mass-independent: brake systems
                 are dimensioned to deliver a standard deceleration; the
                 chosen value is on the gentle side for sleeping passengers).
                 Time lost vs passing at v:  v / (2 · a_dec)

  acceleration — two-phase traction of an assumed standard locomotive
                 (Siemens Vectron — locomotives are full-service leased and
                 not part of the composition data, so the loco is a standard
                 assumption; constants in version.py) hauling the
                 composition's own coach weight:
                   phase 1: constant tractive effort F up to v1 = P / F
                   phase 2: constant power, F(v) = P / v
                 Time lost vs passing at v:  t_acc(v) − d_acc(v) / v

The cruise speed v is each leg's own average speed (distance /
pre-surcharge driving time) — i.e. the speed on the link before the stop
governs the braking loss and the speed on the link after the stop governs
the acceleration loss, exactly as the two phases attach to their own legs.

Deliberate simplifications (documented, tunable via version.py):
  - no rotating-mass supplement, no gradient, no adhesion limit;
  - assumes the leg is long enough to actually reach v — where the
    combined acceleration + braking distance exceeds the leg, the loss is
    damped linearly by distance / (d_acc + d_dec) instead of solving the
    exact triangular speed profile (only relevant for legs of a few km,
    shorter than any realistic night-train stop spacing);
  - real-world station-throat speed restrictions are not modelled, so the
    correction stays conservative (a lower bound on the true loss).

Applied in-place by RailRouter.route() for routing_mode="fullRouting"
only (simpleRouting deliberately bypasses all physics refinements) —
inside the router so every consumer (trip building, auto_stop_addition's
candidate mini-reroutes and final reroute) gets consistent physics from a
single call site. The surcharge lands in its OWN field,
RoutedLeg.dynamics_time_min, leaving driving_time_min as the raw router
time so the two stay differentiable downstream (route builder 0.9.8).

Order of operations (guaranteed, route builder 0.9.9): the cruise speed v
is derived from the leg's RAW driving time — buffer plays no role in the
dynamics calculation. Only AFTERWARDS is the schedule buffer applied, at
each country's own quota, to BOTH components: driving's share was already
added by _parse_legs() at parse time; this module then adds the dynamics
share (unrounded loss × the leg's time-share-weighted quota) on top of
leg.buffer_time_min. Rationale: on congested networks — which is what a
high buffer quota encodes — the extra travel time around stops (braking,
accelerating, queuing into the station) suffers the same operational
margins as cruise running, so dynamics time deserves the same padding.
Note on magnitudes: at current quotas (0.08-0.15) and ~1min of dynamics
per leg the buffered share is a handful of seconds and usually rounds to
0 at the model's whole-minute resolution — the structural guarantee is
in place and becomes visible for heavier/faster compositions or higher
quotas. country_time_shares stay unchanged, which implicitly distributes
both dynamics and its buffer across countries proportionally.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from models.route.version import (
    TRACTION_LOCO_WEIGHT_T,
    TRACTION_LOCO_POWER_KW,
    TRACTION_LOCO_TRACTIVE_EFFORT_KN,
    TRACTION_BRAKE_DECELERATION_MS2,
)

if TYPE_CHECKING:  # runtime import would be circular (rail_router imports us)
    from models.params import Composition, TrackInfraCollection
    from models.route.routing.rail_router import RoutedLeg


def _acceleration_profile(
    cruise_speed_ms: float, mass_kg: float
) -> tuple[float, float]:
    """(time_s, distance_m) to accelerate 0 → cruise_speed_ms with two-phase
    traction: constant tractive effort F up to v1 = P/F, constant power above."""
    force_n = TRACTION_LOCO_TRACTIVE_EFFORT_KN * 1_000
    power_w = TRACTION_LOCO_POWER_KW * 1_000
    v1 = power_w / force_n  # transition speed between the phases

    v = cruise_speed_ms
    if v <= v1:
        time_s = mass_kg * v / force_n
        distance_m = mass_kg * v**2 / (2 * force_n)
    else:
        time_s = mass_kg * v1 / force_n + mass_kg * (v**2 - v1**2) / (2 * power_w)
        distance_m = mass_kg * v1**2 / (2 * force_n) + mass_kg * (
            v**3 - v1**3
        ) / (3 * power_w)
    return time_s, distance_m


def stop_time_loss_s(cruise_speed_ms: float, mass_kg: float) -> float:
    """Seconds lost on one leg vs constant-cruise passage: acceleration out
    of the departure stop + braking into the arrival stop, damped where the
    leg can't physically contain both phases (see module docstring). Split
    out from apply_traction_dynamics() so the assumption is testable as a
    pure function."""
    accel_time_s, accel_dist_m = _acceleration_profile(cruise_speed_ms, mass_kg)
    accel_loss_s = accel_time_s - accel_dist_m / cruise_speed_ms
    brake_loss_s = cruise_speed_ms / (2 * TRACTION_BRAKE_DECELERATION_MS2)
    return accel_loss_s + brake_loss_s


def apply_traction_dynamics(
    legs: list[RoutedLeg],
    composition: Composition,
    tracks: TrackInfraCollection,
) -> None:
    """Fill RoutedLeg.dynamics_time_min in-place with the per-leg stop
    time loss (same in-place enrichment pattern as calc_energy_consumption)
    and add the dynamics' own schedule-buffer share (same per-country quota
    as driving's, weighted by the leg's country time shares) on top of
    leg.buffer_time_min — see the module docstring for the guaranteed
    order of operations. driving_time_min is read (cruise speed) but never
    modified. Train mass = the composition's coach weight plus the assumed
    standard locomotive (Composition.total_weight_t is coaches only —
    locos are leased, not composition data)."""
    mass_kg = (composition.total_weight_t + TRACTION_LOCO_WEIGHT_T) * 1_000

    for leg in legs:
        if leg.distance_m <= 0 or leg.driving_time_min <= 0:
            continue
        # Cruise speed from RAW driving time — buffer plays no role here.
        cruise_speed_ms = leg.distance_m / (leg.driving_time_min * 60)

        loss_s = stop_time_loss_s(cruise_speed_ms, mass_kg)

        # Damp where the leg is too short to reach cruise speed at all.
        _, accel_dist_m = _acceleration_profile(cruise_speed_ms, mass_kg)
        brake_dist_m = cruise_speed_ms**2 / (2 * TRACTION_BRAKE_DECELERATION_MS2)
        if accel_dist_m + brake_dist_m > leg.distance_m:
            loss_s *= leg.distance_m / (accel_dist_m + brake_dist_m)

        leg.dynamics_time_min = round(loss_s / 60)

        # Buffer on dynamics — same quota the leg's driving buffer already
        # used, weighted by country time shares (UNK/missing = no quota,
        # matching _parse_legs()), computed from the UNROUNDED loss so the
        # two roundings don't compound.
        weighted_quota = sum(
            share * tracks.get(cc).buffer_quota_per
            for cc, share in leg.country_time_shares.items()
            if tracks.get(cc) is not None
        )
        leg.buffer_time_min += round(loss_s * weighted_quota / 60)