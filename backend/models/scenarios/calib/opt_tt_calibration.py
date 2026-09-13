"""
opt_tt_calibration.py
=====================
How much schedule supplement the optimised-timetable scenario removes, per
country. Writes the seed CSV `db/dev/seed.py` reads and the calibration
document that states the derivation.

    uv run python models/scenarios/calib/opt_tt_calibration.py

Outputs (both regenerated, never hand-edited):

    seed/opt_tt_buffer_reduction.csv   the reduced quota per country
    OPT_TT_CALIBRATION.md              the derivation, committed

Stdlib only: `db/dev/seed.py` runs this inside the API container when the
seed CSV is absent, and that image carries no dev extras.

The rule
--------
    opt_quota = base_quota - SUPPLEMENT_REDUCTION x theory_supplement

A percentage-POINT cut off the country's own theoretical timetable
supplement, not a share of its whole quota. That distinction is the whole
point of this file, so it is worth stating plainly.

`track_buffer_quota_per` is not a timetable supplement. It is the entire
residual of a real night-train schedule against the router's passage time,
and it contains four things (route_context/calib's
ROUTE_CONTEXT_CALIBRATION.md, §3): pathing and construction allowance,
margin because a night train does not hold priority, speed the train
cannot sustain, and dynamics the model misses. Better timetabling acts on
the first two. Scaling the whole quota would credit it with the last two
as well — i.e. with fixing our own router's optimism — and produce trains
that are fast in the tool and impossible on the ground.

The theoretical supplement per country IS the first two, already
calibrated: `4 + 2.5 sqrt(u / 18.67) + 6 (1 - p)` over network utilisation
and long-distance punctuality, seeded as `timetable_buffer_theory_pct` and
described in that document as the term a priority-improvement scenario
would act on. This file takes it at its word.

Why 0.375
---------
Three independent readings put a European running-time supplement at
8-9 %, and one published case puts the feasible cut at 37.5 % of it.

- UIC leaflet 451-1 (4th ed., 2000) recommends, for loco-hauled passenger
  trains, a fixed 1.5 min/100 km plus a speed- and weight-dependent
  percentage; a night-train rake over 500 t at 161-200 km/h sits at 6-7 %,
  and at ~100 km/h average the fixed part adds roughly 2.5 pp. Total
  8-9 %.
- Hansen & Pachl, Railway Timetabling & Operations (2014): regular
  recovery time is 3-7 % of pure running time on European railways, with
  construction handled separately as special recovery time.
- The theory column here has a median of 8.1 % (range 6.1-10.2) from an
  entirely different derivation. Three routes, one band.

What infrastructure managers actually apply is higher. Rail Net Denmark's
planning rules run 7-13 % against UIC's 3-5 % in the same speed bands, and
Schittenhelm (2011, DTU / Rail Net Denmark) reports a real service
carrying 16.3 %. His Copenhagen-Odense case then costs the reduction: to
meet the political travel-time target the supplement has to fall from
16 % to 10 %, a cut of 37.5 %, which he calls drastic and says needs a new
philosophy for timetabling and operations. Going the rest of the way to
bare UIC levels he rejects as leaving a dangerously small margin.

So 0.375 is the published ceiling of what better timetabling can take out
of a running-time supplement, as assessed by a national infrastructure
manager. The scenario claims exactly that and no more.

What this replaces
------------------
A benchmark rule: converge each country a quarter of the way from its own
quota toward Austria's 0.12. It had two defects. It gave the largest
absolute cut to the countries whose quota is LEAST likely to be timetable
supplement (Sweden 23 %, the United Kingdom 24 %) and none at all to
Austria, whose quota is 73 % supplement and therefore has the most
headroom in proportion. And its floor was one country's calibrated value
doing duty as a European constant.

Still provisional
-----------------
For the reason the route-context calibration gives, not this one: its own
discriminator, the correlation of implied supplement against each driver,
came out with both signs wrong, so the residual is currently believed to
be dominated by router speed error rather than by buffer. Re-run the
recalibration procedure in models/scenarios/README.md before treating any
of this as settled. Sizing the cut off the theory column rather than off
the measured quota is what keeps that uncertainty out of the reduction:
the theory column does not depend on the residual at all.
"""

from __future__ import annotations

import csv
import statistics
from pathlib import Path

# Share of a country's theoretical timetable supplement that a prioritised,
# well-pathed night path removes. Schittenhelm (2011): 16 % -> 10 %.
SUPPLEMENT_REDUCTION = 0.375

# Quotas are seeded at three decimals (db/schema.py), so the reduction is
# rounded to the same precision rather than carrying digits the column
# cannot hold.
QUOTA_NDIGITS = 3

DEFAULT_KEY = "_default"

CALIB_DIR = Path(__file__).resolve().parent
SEED_DIR = CALIB_DIR / "seed"
SEED_CSV = SEED_DIR / "opt_tt_buffer_reduction.csv"
DOC_MD = CALIB_DIR / "OPT_TT_CALIBRATION.md"

ROUTE_CONTEXT_DIR = CALIB_DIR.parents[1] / "infrastructure" / "route_context" / "calib"
_BASE_QUOTA_CSV = ROUTE_CONTEXT_DIR / "seed" / "track_route_context.csv"
_DEFAULT_QUOTA_CSV = ROUTE_CONTEXT_DIR / "seed" / "track_route_context_default.csv"

# The theoretical supplement, kept as this calibration's OWN source file
# rather than read live from route_context/calib/data/route_context.csv.
# That table is both gitignored and .dockerignored (**/calib/data/), so
# inside the API image it does not exist, and a seed-time calibration
# cannot depend on a file the image deliberately drops. sources/ is the
# established home for an input a calibration cannot reproduce itself —
# route_context/calib/sources/ is un-ignored for exactly this reason.
#
# refresh_theory_from_route_context() rewrites it whenever the route-context
# table IS present (a developer machine after a recalibration), so the copy
# cannot drift silently: re-run this script after re-running route context
# and the new values land here and get committed.
SOURCES_DIR = CALIB_DIR / "sources"
_THEORY_CSV = SOURCES_DIR / "timetable_buffer_theory.csv"
_ROUTE_CONTEXT_DATA_CSV = ROUTE_CONTEXT_DIR / "data" / "route_context.csv"

_THEORY_PARAMETER = "timetable_buffer_theory_pct"
_THEORY_FIELDS = (
    "country_code",
    "timetable_buffer_theory_pct",
    "basis",
    "source_id",
    "note",
)

_FIELDS = (
    "country_code",
    "base_quota_per",
    "theory_supplement_per",
    "reduction_per",
    "opt_quota_per",
    "theory_basis",
)


def _read_csv(path: Path, produced_by: str) -> list[dict]:
    assert path.is_file(), f"missing {path} — run {produced_by} first"
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def base_quotas() -> dict[str, float | None]:
    """Every seeded country's schedule supplement, plus the EU fallback
    row under DEFAULT_KEY. An empty cell stays None: that country resolves
    the column from the fallback, which is reduced in its own right."""
    rows = _read_csv(
        _BASE_QUOTA_CSV, "route_context/calib/02_route_context_calibration.ipynb"
    )
    out: dict[str, float | None] = {
        row["country_code"]: (
            float(row["track_buffer_quota_per"])
            if row["track_buffer_quota_per"]
            else None
        )
        for row in rows
    }
    default_row = _read_csv(
        _DEFAULT_QUOTA_CSV, "route_context/calib/02_route_context_calibration.ipynb"
    )[0]
    out[DEFAULT_KEY] = float(default_row["track_buffer_quota_per"])
    return out


def refresh_theory_from_route_context() -> bool:
    """Re-copy the theory column from route_context's calibration table.

    A no-op when that table is absent, which is the normal case inside the
    API image and on a checkout that has not run the notebooks. Returns
    whether it wrote.
    """
    if not _ROUTE_CONTEXT_DATA_CSV.is_file():
        return False
    rows = [
        {
            "country_code": r["country_code"],
            "timetable_buffer_theory_pct": r["value"],
            "basis": r["status"],
            "source_id": r["source_id"],
            "note": r["note"],
        }
        for r in _read_csv(_ROUTE_CONTEXT_DATA_CSV, "route_context/calib/02_*.ipynb")
        if r["parameter"] == _THEORY_PARAMETER and r["value"]
    ]
    if not rows:
        return False
    rows.sort(key=lambda r: r["country_code"])
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    with open(_THEORY_CSV, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(_THEORY_FIELDS))
        writer.writeheader()
        writer.writerows(rows)
    return True


def theory_supplements() -> dict[str, float]:
    """The RMMS-driver timetable supplement per country, as a fraction.

    The fallback row gets the median of the calibrated countries. A median
    rather than a mean because the distribution has a tail (Romania and
    Slovenia sit above 10 % on poor punctuality), and rather than the
    ONTD-weighted prior the quota uses because this term is not measured
    from legs at all — a country with no legs still has a utilisation and
    a punctuality figure, so nothing about it is less known than the rest.
    """
    rows = _read_csv(
        _THEORY_CSV,
        "models/scenarios/calib/opt_tt_calibration.py — the file is "
        "committed, so a missing one means an incomplete checkout",
    )
    out = {
        row["country_code"]: float(row[_THEORY_PARAMETER]) / 100
        for row in rows
        if row[_THEORY_PARAMETER]
    }
    assert out, f"no {_THEORY_PARAMETER} rows in {_THEORY_CSV}"
    out[DEFAULT_KEY] = round(statistics.median(out.values()), 4)
    return out


def reduce_quota(quota: float, theory: float) -> float:
    """One country's optimised-timetable supplement.

    The floor never binds on the current calibration — every quota is at
    least twice its theory value — and exists so a future recalibration
    that inverts the two cannot drive a country to zero or below. Removing
    more supplement than the theory says exists would be the same
    overreach as scaling the whole quota.
    """
    reduced = quota - SUPPLEMENT_REDUCTION * theory
    floor = (1 - SUPPLEMENT_REDUCTION) * theory
    return round(max(reduced, floor), QUOTA_NDIGITS)


def calibrate() -> list[dict]:
    """One row per country plus the fallback, in seed-CSV shape."""
    quotas = base_quotas()
    theory = theory_supplements()

    missing = sorted(
        cc for cc, q in quotas.items() if q is not None and cc not in theory
    )
    assert not missing, (
        f"no {_THEORY_PARAMETER} for {missing} — the route-context "
        "calibration seeds a quota for these countries but no theoretical "
        "supplement, so the reduction cannot be sized; re-run "
        "02_route_context_calibration.ipynb"
    )

    rows = []
    for cc in sorted(quotas):
        quota = quotas[cc]
        if quota is None:
            # Resolves the column from the fallback row, which this file
            # reduces separately — nothing to do here, and writing a value
            # would silently give the country its own.
            continue
        t = theory[cc]
        opt = reduce_quota(quota, t)
        rows.append(
            {
                "country_code": cc,
                "base_quota_per": f"{quota:.3f}",
                "theory_supplement_per": f"{t:.4f}",
                "reduction_per": f"{quota - opt:.3f}",
                "opt_quota_per": f"{opt:.3f}",
                "theory_basis": (
                    "median of the calibrated countries"
                    if cc == DEFAULT_KEY
                    else "RMMS drivers (utilisation, long-distance punctuality)"
                ),
            }
        )
    return rows


def write_seed_csv(rows: list[dict]) -> None:
    SEED_DIR.mkdir(parents=True, exist_ok=True)
    with open(SEED_CSV, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _journey_delta_pct(base: float, opt: float) -> float:
    """What the reduction takes off scheduled driving time. The quota
    multiplies driving and dynamics time, so the ratio is against the
    already-supplemented total, not against the raw quota difference."""
    return ((1 + opt) / (1 + base) - 1) * 100


def write_document(rows: list[dict]) -> None:
    deltas = {
        r["country_code"]: _journey_delta_pct(
            float(r["base_quota_per"]), float(r["opt_quota_per"])
        )
        for r in rows
    }
    shares = {
        r["country_code"]: float(r["theory_supplement_per"])
        / float(r["base_quota_per"])
        for r in rows
    }
    ordered = sorted(rows, key=lambda r: deltas[r["country_code"]])

    lines = [
        "# Optimised timetables — the buffer reduction",
        "",
        "Generated by `models/scenarios/calib/opt_tt_calibration.py` — "
        "do not edit by hand. The reasoning, the sources and the rejected "
        "alternatives are in that file's module docstring; this document "
        "is what the numbers came out as.",
        "",
        "## The rule",
        "",
        "```",
        f"opt_quota = base_quota - {SUPPLEMENT_REDUCTION} x theory_supplement",
        "```",
        "",
        "A percentage-point cut off each country's own theoretical timetable "
        "supplement — the term better timetabling actually acts on — not a "
        "share of its whole schedule supplement, which also contains line-speed "
        "physics and the router's own optimism.",
        "",
        f"`{SUPPLEMENT_REDUCTION}` is Schittenhelm (2011, DTU / Rail Net Denmark): "
        "the Copenhagen-Odense case costs a running-time supplement cut from "
        "16 % to 10 % to meet a political travel-time target, and calls it the "
        "outer edge of what a new timetabling philosophy could deliver.",
        "",
        "## Per country",
        "",
        "`share` is how much of the country's schedule supplement is timetable "
        "supplement at all; `driving time` is what the reduction takes off "
        "scheduled driving time, dwell excluded.",
        "",
        "| | base quota | theory | share | reduction | OPT TT quota | driving time |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in ordered:
        cc = r["country_code"]
        lines.append(
            f"| {cc} | {r['base_quota_per']} | {float(r['theory_supplement_per']):.3f} "
            f"| {shares[cc]:.0%} | {r['reduction_per']} | {r['opt_quota_per']} "
            f"| {deltas[cc]:+.2f} % |"
        )

    values = list(deltas.values())
    lines += [
        "",
        f"Median {statistics.median(values):+.2f} %, "
        f"range {min(values):+.2f} % to {max(values):+.2f} %.",
        "",
        "## Reading it",
        "",
        "The spread is narrower than the schedule supplements themselves, and "
        "that is the point: the supplements run from 0.113 to 0.385 mostly "
        "because of how well the router models each network, while the "
        "timetable component behind them runs only from 0.061 to 0.102. A "
        "country is credited for the margin a planner could actually give "
        "back, not for the size of our own measurement error.",
        "",
        "Austria is no longer excluded. Under the previous benchmark rule it "
        "was pinned at exactly zero for being the floor, despite having the "
        "highest timetable share in Europe — the most headroom in proportion, "
        "and none of it granted.",
        "",
        "The reduction is still PROVISIONAL, for the reason the route-context "
        "calibration gives rather than anything in this file: its own "
        "correlation discriminator came out with both signs wrong, so the "
        "measured residual is currently believed to be dominated by router "
        "speed error. Sizing the cut off the theory column keeps that "
        "uncertainty out of the reduction itself, but it does not settle the "
        "baseline the reduction applies to.",
        "",
    ]
    DOC_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    if refresh_theory_from_route_context():
        print(f"  refreshed {_THEORY_CSV.name} from the route-context calibration")
    rows = calibrate()
    write_seed_csv(rows)
    write_document(rows)
    print(f"  wrote {SEED_CSV.name} ({len(rows)} rows) and {DOC_MD.name}")


if __name__ == "__main__":
    main()
