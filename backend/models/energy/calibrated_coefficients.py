"""
calibrated_coefficients.py
==========================
Fitted coefficients of the night train energy model.

REGENERATED, NOT EDITED. calib/02_energy_calibration.ipynb rewrites this
file on every full run; commit the regenerated file together with any
change to the calibration inputs. Hand edits are overwritten.

The values below were derived on 2026-08-30 from the calibration outputs
of the corrected collection (samples_all 2026-08-30, 1192 rows, and the
factorial speed sweep, 1440 rows, 199 route-stable groups). PROVENANCE
says which run wrote the file; "derived-2026-08-30" marks this initial,
hand-derived set - the first local 02 run replaces it with the exact
group-level fit.

Mass basis: coach gross weight at 80% load, LOCOMOTIVE EXCLUDED
(Composition.total_weight_t()). The locomotive's own resistance is
constant across the fleet and lives in the per-km constant B.
Length basis: coach rake length, locomotive excluded
(Composition.total_length_m()).
"""

from __future__ import annotations

PROVENANCE: str = "derived-2026-08-30"
DRAG_IDENTIFIED_UP_TO_KMH: float = 165.5
"""Highest realised average leg speed in the calibration sweep. Above it
the v^2 term extrapolates on physics (measured exponent ~2), not on data."""

# --- traction: level terms ---------------------------------------------------
A_PER_LEG_KWH_PER_T: float = 0.045
"""Start/stop energy per leg, per tonne. Carries acceleration work that a
purely per-km model cannot: without it, legs under 50 km under-predict by
about a third."""

B_PER_KM_KWH: float = 1.40
"""Per-km constant, mass-independent: locomotive resistance and everything
common to every composition."""

C_PER_TKM_KWH: float = 0.00265
"""Rolling resistance per coach tonne-km."""

# --- traction: drag (applied to average leg speed squared) -------------------
K_MASS_DRAG: float = 4.287e-07
"""kWh/(t*km*(km/h)^2). Mass-linked share of drag."""

K_LENGTH_DRAG: float = 6.205e-07
"""kWh/(m*km*(km/h)^2). Length-linked share of drag (skin friction). The
mass-matched composition pairs identify this: +17% length at equal mass
costs +6-8% drag, so neither a pure-mass nor a pure-length form fits."""

# --- auxiliaries (applied to leg driving time) -------------------------------
P_LOCO_AUX_KW: float = 99.9
"""Locomotive auxiliary draw, measured: 99.9 kW, flat across all eight
compositions, R^2 = 1.000 against leg time."""

P_HOTEL_PER_COACH_KW: float = 15.0
"""ASSUMPTION, not measured: Trassenfinder was queried with coach hotel
load off, so heating/air-conditioning/lighting of the coaches is absent
from the calibration data. Installed comfort power is 50-100 kVA per
coach (UIC 550 era equipment; the UIC train-line cap is 50 kVA per
coach); 15 kW is a mid estimate of the average draw, range 10-25
depending on season. Linear in time, so changing it never requires
re-collection."""
