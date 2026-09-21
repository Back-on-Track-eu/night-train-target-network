"""
vat_calibration.py
==================
VAT on rail passenger tickets, per country: the rate on a domestic
ticket and the rate on the domestic share of a cross-border ticket. Writes
the seed CSVs `db/dev/seed.py` reads and the calibration document that
states the sources.

    uv run python models/demand/calib/vat/vat_calibration.py

Outputs (both regenerated, never hand-edited):

    seed/ticket_vat_rates.csv   one row per country in input_params.countries
    seed/sources.csv            the documents the rates were read from
    VAT_CALIBRATION.md          the table with its provenance, committed

Stdlib only: `db/dev/seed.py` runs this inside the API container when the
seed CSVs are absent, and that image carries no dev extras.

Why two rates
-------------
Under Article 48 of the VAT Directive, passenger transport is taxed where
it takes place, in proportion to the distances covered in each country. A
Vienna–Amsterdam night train therefore does not carry one VAT rate: each
country's rate applies to the kilometres run on its territory. Most member
states, however, exempt (zero-rate) the domestic leg of an INTERNATIONAL
rail journey while taxing purely domestic tickets, and the EFTA and
non-EU countries follow the same shape. So a country needs two figures:

    vat_domestic_per        rate on a ticket that starts and ends in the
                            country
    vat_international_per   rate on the country's share of a ticket that
                            crosses a border — 0 where the international
                            leg is exempt

The tool applies them distance-weighted: for a route with country distance
shares s_c (models/route, Segment.country_distance_shares),

    effective_rate = sum_c s_c x rate_c

with rate_c = vat_international_per where the route crosses a border, else
vat_domestic_per. That arithmetic runs where the fares are shown (the
frontend's Places and prices / What follows panels) and touches no cost or
revenue figure: the model prices net, VAT is what the passenger pays on
top, and the necessary subsidy is a net figure.

Status flags
------------
Every rate carries a status the same way the infrastructure calibrations
do (models/infrastructure/README.md):

    sourced     read from a document in sources.csv
    assumed     a standard or reduced rate applied by analogy — the note
                says which — because no rail-specific publication was at
                hand; stated so a reader can challenge it
    no_railway  the country has no railway (CY, MT); no ticket is ever
                priced there
    blocked     routing never enters the country (BY, RU); the figure is
                a placeholder that never applies

International rates of the EU member states are the best-sourced figures
here: T&E's 2025 VAT gap analysis lists the five member states that still
tax international rail (Croatia 25 %, Germany 7 %, Spain 10 %, Belgium 6 %,
Netherlands 9 %) and Greece (13 %, no cross-border service today); the
European Commission's 2017 passenger-transport VAT study (CE Delft) had
also listed Austria, which taxes the Austrian section of an international
ticket at 10 % on ÖBB's own invoices — kept at 10 % here, with the
discrepancy noted for review.

Price year
----------
VAT is a rate, not a price: nothing here is escalated (docs-site
price-basis.md).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

CALIB_DIR = Path(__file__).resolve().parent
SEED_DIR = CALIB_DIR / "seed"
SEED_CSV = SEED_DIR / "ticket_vat_rates.csv"
SOURCES_CSV = SEED_DIR / "sources.csv"
DOC_MD = CALIB_DIR / "VAT_CALIBRATION.md"

CALIBRATION_REVIEWED = "2026-09-21"

SOURCED = "sourced"
ASSUMED = "assumed"
NO_RAILWAY = "no_railway"
BLOCKED = "blocked"

# --- source register --------------------------------------------------------
# One row per document a rate was read from. The seeder turns these into
# input_params.sources rows and resolves the FK through source_description,
# so descriptions must be unique across every calibration's register.
SOURCES: dict[str, dict] = {
    "TE-VAT-2025": {
        "source_description": (
            "Transport & Environment (2025): European long-distance passenger "
            "transport — VAT gap analysis. Contribution to the European "
            "Commission's public consultation on VAT rules for travel and "
            "tourism; rail annex (member states taxing international rail)"
        ),
        "source_url": (
            "https://www.transportenvironment.org/articles/"
            "european-long-distance-passenger-transport-vat-gap-analysis"
        ),
        "source_date": "2025-11-20",
    },
    "EC-VAT-2017": {
        "source_description": (
            "European Commission, DG TAXUD / CE Delft (2017): Study on the "
            "economic effects of the current VAT rules for passenger transport "
            "— international rail taxed in AT, BE, HR, DE, GR, NL, ES"
        ),
        "source_url": (
            "https://taxation-customs.ec.europa.eu/document/download/"
            "b98dfd42-245a-40f5-b702-2680b68f4026_en"
        ),
        "source_date": "2017-12-01",
    },
    "TEDB-2025": {
        "source_description": (
            "European Commission: Taxes in Europe Database (TEDB) — VAT rates "
            "applied by the member states to domestic passenger transport, "
            "CPA 49.10 rail, as published for 2025"
        ),
        "source_url": "https://ec.europa.eu/taxation_customs/tedb/",
        "source_date": "2025-07-01",
    },
    "ESTV-MBI-10": {
        "source_description": (
            "Eidgenössische Steuerverwaltung: MWST-Branchen-Info 10, "
            "Transportunternehmungen des öffentlichen und des touristischen "
            "Verkehrs — Personenbeförderung im Inland (Normalsatz 8,1 %) und "
            "grenzüberschreitende Personenbeförderung im Eisenbahnverkehr"
        ),
        "source_url": "https://www.estv.admin.ch/estv/de/home/mehrwertsteuer.html",
        "source_date": "2024-01-01",
    },
    "HMRC-VAT-701-19": {
        "source_description": (
            "HM Revenue & Customs: VAT Notice 744A — passenger transport "
            "(zero rate for vehicles, ships and aircraft carrying ten or more "
            "passengers; scheduled rail)"
        ),
        "source_url": (
            "https://www.gov.uk/guidance/vat-on-passenger-transport-notice-744a"
        ),
        "source_date": "2024-04-01",
    },
    "SKATT-NO-2025": {
        "source_description": (
            "Skatteetaten (Norway): merverdiavgift — persontransport 12 %; "
            "merverdiavgiftsloven § 6-28, fritak for transport direkte til "
            "eller fra utlandet"
        ),
        "source_url": "https://www.skatteetaten.no/",
        "source_date": "2025-01-01",
    },
}


@dataclass(frozen=True)
class Rate:
    country_code: str
    domestic_per: float
    international_per: float
    status: str
    source_id: str
    note: str


# --- the table --------------------------------------------------------------
# Order follows db/dev/seed.py COUNTRIES. Rates as fractions (0.07 = 7 %).
RATES: tuple[Rate, ...] = (
    Rate(
        "DE",
        0.07,
        0.07,
        SOURCED,
        "TE-VAT-2025",
        "7 % on long-distance rail since 2020; Germany taxes the German section of an international ticket",
    ),
    Rate(
        "AT",
        0.10,
        0.10,
        SOURCED,
        "EC-VAT-2017",
        "10 % reduced rate on passenger transport; the Austrian section of an international ticket is taxed (ÖBB invoices) — T&E 2025 no longer lists AT, review",
    ),
    Rate(
        "CH",
        0.081,
        0.0,
        SOURCED,
        "ESTV-MBI-10",
        "Normalsatz 8,1 % im Inland; die grenzüberschreitende Eisenbahnbeförderung ist für den inländischen Streckenteil steuerbefreit",
    ),
    Rate(
        "FR",
        0.10,
        0.0,
        SOURCED,
        "TE-VAT-2025",
        "10 % domestic; international rail exempt",
    ),
    Rate(
        "BE",
        0.06,
        0.06,
        SOURCED,
        "TE-VAT-2025",
        "6 % on passenger transport, also on the Belgian section of an international ticket",
    ),
    Rate(
        "DK",
        0.0,
        0.0,
        SOURCED,
        "TEDB-2025",
        "passenger transport exempt without credit",
    ),
    Rate("SE", 0.06, 0.0, SOURCED, "TEDB-2025", "6 % domestic; international exempt"),
    Rate(
        "BG",
        0.20,
        0.0,
        ASSUMED,
        "TEDB-2025",
        "standard rate on domestic passenger transport; international exempt",
    ),
    Rate(
        "HR",
        0.25,
        0.25,
        SOURCED,
        "TE-VAT-2025",
        "standard rate, also on the Croatian section of an international ticket",
    ),
    Rate("CY", 0.0, 0.0, NO_RAILWAY, "TEDB-2025", "no railway"),
    Rate(
        "CZ",
        0.12,
        0.0,
        SOURCED,
        "TEDB-2025",
        "12 % reduced rate since the 2024 consolidation; international exempt",
    ),
    Rate(
        "EE",
        0.24,
        0.0,
        ASSUMED,
        "TEDB-2025",
        "standard rate (24 % from July 2025) assumed for domestic rail; international exempt",
    ),
    Rate(
        "FI",
        0.14,
        0.0,
        SOURCED,
        "TEDB-2025",
        "reduced rate 14 % since 2025 (was 10 %); international exempt",
    ),
    Rate(
        "GR",
        0.13,
        0.13,
        SOURCED,
        "TE-VAT-2025",
        "13 % reduced rate, applied to international rail too — no cross-border service runs today",
    ),
    Rate(
        "HU",
        0.27,
        0.0,
        ASSUMED,
        "TEDB-2025",
        "standard rate assumed for domestic rail; international exempt (T&E 2025)",
    ),
    Rate("IE", 0.0, 0.0, SOURCED, "TEDB-2025", "passenger transport exempt"),
    Rate("IT", 0.10, 0.0, SOURCED, "TEDB-2025", "10 % domestic; international exempt"),
    Rate(
        "LV",
        0.12,
        0.0,
        SOURCED,
        "TEDB-2025",
        "12 % reduced rate on regular domestic passenger transport; international exempt",
    ),
    Rate(
        "LT",
        0.09,
        0.0,
        SOURCED,
        "TEDB-2025",
        "9 % reduced rate on regular passenger transport; international exempt",
    ),
    Rate(
        "LU",
        0.03,
        0.0,
        SOURCED,
        "TEDB-2025",
        "3 % super-reduced rate; international exempt",
    ),
    Rate("MT", 0.0, 0.0, NO_RAILWAY, "TEDB-2025", "no railway"),
    Rate(
        "NL",
        0.09,
        0.09,
        SOURCED,
        "TE-VAT-2025",
        "9 % reduced rate, also on the Dutch section of an international ticket",
    ),
    Rate(
        "PL", 0.08, 0.0, SOURCED, "TEDB-2025", "8 % reduced rate; international exempt"
    ),
    Rate(
        "PT", 0.06, 0.0, SOURCED, "TEDB-2025", "6 % reduced rate; international exempt"
    ),
    Rate(
        "RO",
        0.11,
        0.0,
        ASSUMED,
        "TEDB-2025",
        "reduced rate 11 % (August 2025 reform) assumed for domestic rail; international exempt",
    ),
    Rate(
        "SK",
        0.23,
        0.0,
        ASSUMED,
        "TEDB-2025",
        "standard rate (23 % from 2025) assumed for domestic rail; international exempt",
    ),
    Rate(
        "SI",
        0.095,
        0.0,
        SOURCED,
        "TEDB-2025",
        "9.5 % reduced rate; international exempt",
    ),
    Rate(
        "ES",
        0.10,
        0.10,
        SOURCED,
        "TE-VAT-2025",
        "10 % reduced rate, also on the Spanish section of an international ticket",
    ),
    Rate(
        "NO",
        0.12,
        0.0,
        SOURCED,
        "SKATT-NO-2025",
        "12 % on passenger transport; transport directly to or from abroad exempt (§ 6-28)",
    ),
    Rate(
        "GB",
        0.0,
        0.0,
        SOURCED,
        "HMRC-VAT-701-19",
        "zero-rated: scheduled passenger transport",
    ),
    Rate(
        "BA",
        0.17,
        0.0,
        ASSUMED,
        "TEDB-2025",
        "single standard rate assumed; international transport exempt by analogy",
    ),
    Rate(
        "RS",
        0.10,
        0.0,
        ASSUMED,
        "TEDB-2025",
        "reduced rate 10 % on passenger transport assumed; international exempt by analogy",
    ),
    Rate(
        "ME",
        0.07,
        0.0,
        ASSUMED,
        "TEDB-2025",
        "reduced rate 7 % on passenger transport assumed; international exempt by analogy",
    ),
    Rate(
        "AL",
        0.20,
        0.0,
        ASSUMED,
        "TEDB-2025",
        "standard rate assumed; international transport exempt by analogy",
    ),
    Rate(
        "UA",
        0.20,
        0.0,
        ASSUMED,
        "TEDB-2025",
        "standard rate assumed for domestic rail; international passenger transport 0 %",
    ),
    Rate(
        "TR",
        0.10,
        0.0,
        ASSUMED,
        "TEDB-2025",
        "reduced rate 10 % on passenger transport assumed; international transport exempt (KDV Kanunu Art. 14)",
    ),
    Rate(
        "MD",
        0.20,
        0.0,
        ASSUMED,
        "TEDB-2025",
        "standard rate assumed; international exempt by analogy",
    ),
    Rate(
        "MK",
        0.05,
        0.0,
        ASSUMED,
        "TEDB-2025",
        "preferential 5 % on passenger transport assumed; international exempt by analogy",
    ),
    Rate(
        "LI",
        0.081,
        0.0,
        SOURCED,
        "ESTV-MBI-10",
        "Swiss VAT law applies in Liechtenstein",
    ),
    Rate("BY", 0.20, 0.0, BLOCKED, "TEDB-2025", "routing never enters Belarus"),
    Rate("RU", 0.20, 0.0, BLOCKED, "TEDB-2025", "routing never enters Russia"),
)

_FIELDS = (
    "country_code",
    "vat_domestic_per",
    "vat_international_per",
    "status",
    "source_id",
    "note",
)
_SOURCE_FIELDS = ("source_id", "source_description", "source_url", "source_date")


def write_seed_csvs() -> None:
    SEED_DIR.mkdir(parents=True, exist_ok=True)
    with open(SEED_CSV, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_FIELDS)
        writer.writeheader()
        for r in RATES:
            writer.writerow(
                {
                    "country_code": r.country_code,
                    "vat_domestic_per": f"{r.domestic_per:.3f}",
                    "vat_international_per": f"{r.international_per:.3f}",
                    "status": r.status,
                    "source_id": r.source_id,
                    "note": r.note,
                }
            )
    with open(SOURCES_CSV, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_SOURCE_FIELDS)
        writer.writeheader()
        for sid, row in SOURCES.items():
            writer.writerow({"source_id": sid, **row})


def _pct(value: float) -> str:
    return f"{value * 100:g} %"


def write_document() -> None:
    counts: dict[str, int] = {}
    for r in RATES:
        counts[r.status] = counts.get(r.status, 0) + 1
    taxing = [r.country_code for r in RATES if r.international_per > 0]
    rows = "\n".join(
        f"| {r.country_code} | {_pct(r.domestic_per)} | {_pct(r.international_per)} | "
        f"{r.status} | {r.source_id} | {r.note} |"
        for r in RATES
    )
    sources = "\n".join(
        f"| {sid} | {row['source_description']} | {row['source_date']} | "
        f"{row['source_url']} |"
        for sid, row in SOURCES.items()
    )
    text = f"""# VAT on rail tickets — calibration

*Generated by `vat_calibration.py` on {CALIBRATION_REVIEWED}; do not edit by hand.*

{len(RATES)} countries: {counts.get(SOURCED, 0)} sourced, {counts.get(ASSUMED, 0)}
assumed, {counts.get(NO_RAILWAY, 0)} without a railway, {counts.get(BLOCKED, 0)}
never routed.

## The rule

Passenger transport is taxed where it takes place, in proportion to the
distance covered in each country (Article 48 of the VAT Directive; the same
shape outside the EU). A cross-border ticket therefore carries each
country's rate on that country's share of the route, and most countries
exempt that share. The tool applies, per route,

    effective_rate = Σ share_c × rate_c

with `rate_c` the international rate where the route crosses a border and the
domestic rate otherwise. VAT is shown on the fares and on the ticket revenue
a passenger pays; it enters no cost, revenue or subsidy figure, which are
net.

Member states still taxing the domestic section of an international rail
ticket: {", ".join(taxing)}.

## Rates

| Country | Domestic | International leg | Status | Source | Note |
|---|---|---|---|---|---|
{rows}

`assumed` rows apply a country's standard or reduced rate by analogy where no
rail-specific publication was at hand; they only ever price a route that runs
inside that one country, since every assumed international rate is 0 %.

## Sources

| id | Document | Date | Link |
|---|---|---|---|
{sources}
"""
    DOC_MD.write_text(text, encoding="utf-8")


def main() -> None:
    write_seed_csvs()
    write_document()
    print(
        f"  wrote {SEED_CSV.name} ({len(RATES)} rows), {SOURCES_CSV.name} and {DOC_MD.name}"
    )


if __name__ == "__main__":
    main()
