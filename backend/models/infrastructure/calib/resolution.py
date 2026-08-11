"""
resolution.py
=============
Country parameter resolution for the track infrastructure calibration.

Holds the mechanism shared by both calibration notebooks so neither of them
carries a private copy: the reference night train, the three-step resolution
ladder, the plausibility audit that decides whether a network-statement
extraction may be trusted, and the price-basis escalation to the evaluation
year.

The resolution ladder ranks the ways a country value can be established, best
first. A value is always taken from the highest rung that yields an
observation:

  EXTRACTED  the infrastructure manager's own tariff, evaluated for the
             reference night train — the only rung that reflects a country's
             actual charging formula
  ANCHORED   a country figure from a uniform pan-European statistic, mapped
             onto the night train case by a calibrated factor
  DEFAULT    the EU fallback row, used when a country has no observation at
             all

Escalation is deliberately parameter-specific rather than one global rate:
track access charges have their own observed trend, other monetary parameters
follow general escalation, and dimensionless parameters are exempt by
construction. See INFRA_CALIBRATION.md for the derivation of every rate.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from statistics import median
from typing import Iterable, Optional

# Evaluation year of the target network — the price basis every monetary
# parameter is escalated to.
TARGET_YEAR = 2032


class Method(str, Enum):
    """Resolution ladder rung, best first. Ordering is used by resolve()."""

    EXTRACTED = "extracted"
    ANCHORED = "anchored"
    DEFAULT = "default"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


_LADDER = (Method.EXTRACTED, Method.ANCHORED, Method.DEFAULT)


@dataclass(frozen=True)
class ReferenceNightTrain:
    """
    The train every country tariff is evaluated for.

    Charging formulas are train-specific — they weigh gross tonnage, length,
    speed band, traction and time of day. Comparing countries therefore needs
    one fixed train, exactly as the composition calibration needed one fixed
    reference route. Values are the mid-point of the eight standard
    compositions, not a ninth invented consist.
    """

    label: str
    gross_weight_t: float
    length_m: float
    max_speed_kmh: int
    n_locos: int
    electric: bool
    market_segment: str  # PSO status, which drives mark-up eligibility
    time_band: str  # charging period the train predominantly occupies
    line_category: str  # conventional vs high-speed infrastructure


@dataclass(frozen=True)
class Escalation:
    """
    One escalation rule: a nominal rate applied to a set of parameters.

    parameters is the authoritative list of what the rule covers, so a new
    parameter that nobody assigned a rule to fails loudly in escalator_for()
    instead of silently inheriting someone else's rate.
    """

    name: str
    rate_per_year: float
    parameters: frozenset[str]
    rationale: str


@dataclass(frozen=True)
class Observation:
    """
    One measured or derived country value, before escalation.

    value is expressed in the parameter's own unit at basis_year prices.
    Dimensionless parameters carry basis_year purely for provenance.
    """

    country_code: str
    parameter: str
    value: float
    unit: str
    basis_year: int
    method: Method
    source_id: str
    confidence: Confidence
    note: str = ""


@dataclass(frozen=True)
class Resolved:
    """A country parameter after ladder resolution and escalation."""

    country_code: str
    parameter: str
    value: float  # escalated to TARGET_YEAR
    value_basis: float  # as observed, before escalation
    unit: str
    basis_year: int
    method: Method
    source_id: str
    confidence: Confidence
    note: str

    @property
    def is_default(self) -> bool:
        """Mirrors TrackInfrastructure.field_is_default in the domain model."""
        return self.method is Method.DEFAULT


def escalate(value: float, basis_year: int, rate_per_year: float) -> float:
    """Compound a nominal rate from basis_year to TARGET_YEAR."""
    return value * (1.0 + rate_per_year) ** (TARGET_YEAR - basis_year)


def escalator_for(parameter: str, rules: Iterable[Escalation]) -> Escalation:
    """The rule covering a parameter. Raises if none or more than one does."""
    matches = [r for r in rules if parameter in r.parameters]
    if len(matches) != 1:
        raise KeyError(
            f"{parameter!r} is covered by {len(matches)} escalation rules, expected exactly 1"
        )
    return matches[0]


def audit_extraction(
    extracted: float, anchor: float, band: tuple[float, float]
) -> tuple[bool, float, str]:
    """
    Decide whether an extraction may be trusted, by comparing it against the
    country's own anchor.

    An extraction and an anchor measure the same thing through different
    lenses, so their ratio should sit in a narrow band. A ratio far outside it
    means the extraction captured the wrong tariff line, the wrong unit or the
    wrong currency — all of which we have actually seen in the source workbook.
    Returns (accepted, implied_factor, reason).
    """
    if anchor <= 0:
        return False, float("nan"), "no anchor to audit against"
    factor = extracted / anchor
    low, high = band
    if factor < low:
        return (
            False,
            factor,
            f"implied factor {factor:.2f} below plausibility band {low}",
        )
    if factor > high:
        return (
            False,
            factor,
            f"implied factor {factor:.2f} above plausibility band {high}",
        )
    return True, factor, "within plausibility band"


def resolve(
    country_code: str,
    parameter: str,
    observations: Iterable[Observation],
    rules: Iterable[Escalation],
) -> Resolved:
    """
    Pick the best available observation for one country parameter and escalate
    it. Observations for other countries or parameters are ignored, so callers
    can pass the whole table.
    """
    candidates = [
        o
        for o in observations
        if o.country_code == country_code and o.parameter == parameter
    ]
    if not candidates:
        raise LookupError(f"no observation for {country_code}/{parameter}")

    best = min(candidates, key=lambda o: _LADDER.index(o.method))
    rate = escalator_for(parameter, rules).rate_per_year
    return Resolved(
        country_code=best.country_code,
        parameter=best.parameter,
        value=escalate(best.value, best.basis_year, rate),
        value_basis=best.value,
        unit=best.unit,
        basis_year=best.basis_year,
        method=best.method,
        source_id=best.source_id,
        confidence=best.confidence,
        note=best.note,
    )


def resolve_all(
    country_codes: Iterable[str],
    parameters: Iterable[str],
    observations: Iterable[Observation],
    rules: Iterable[Escalation],
) -> list[Resolved]:
    """resolve() over the full country x parameter grid."""
    obs = list(observations)
    return [resolve(cc, p, obs, rules) for cc in country_codes for p in parameters]


def eu_default(values: Iterable[float], statistic: str = "median") -> Optional[float]:
    """
    Collapse resolved country values into the EU fallback.

    Median by default: the fallback stands in for a country we know nothing
    about, and a handful of very high-charging networks would drag a mean far
    above anything typical. Mean is available for the comparison the
    documentation shows.
    """
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    if statistic == "median":
        return median(vals)
    if statistic == "mean":
        return sum(vals) / len(vals)
    raise ValueError(f"unknown statistic {statistic!r}")
