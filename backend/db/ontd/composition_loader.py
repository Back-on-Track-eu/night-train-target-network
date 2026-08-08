"""
One-time import of the curated ONTD composition catalog.

Fills the CURATED half of the ontd schema — coach_classes, coachtypes,
coachtype_classes, compositions, composition_coaches, route_compositions
— from the target-network workbook. After this runs, the DB is the
source of truth: new coach material and missing data are maintained by
hand in the tables, not by re-importing (adapters/proposal/README.md §5.5,
decision 26). Nothing here is part of the half-yearly ONTD refresh, and
db/ontd/loader.py never truncates these tables.

Because the tables are hand-maintained afterwards, a re-run would
silently discard that curation — so the script refuses to touch
non-empty tables unless --replace is passed explicitly.

Run db/ontd/loader.py FIRST: route assignments are restricted to route_ids
that actually exist in ontd.routes, which is what keeps the target
network's proposal-only routes (~200 of the workbook's 367 assignments)
out of a table describing existing trains.

Usage:
    python db/dev/db/ontd/composition_loader.py                 # fetch from Drive
    python db/dev/db/ontd/composition_loader.py --xlsx /path/to/workbook.xlsx
    python db/dev/db/ontd/composition_loader.py --sheet-id <native-sheet-id>
    python db/dev/db/ontd/composition_loader.py --replace
"""

import argparse

from connection import connect

from xlsx_utils import (
    workbook_url,
    is_blank,
    load_workbook,
    sheet_row_dicts,
    sheets_export_url,
    to_float,
    to_int,
    to_text,
)


# Wide-slot layouts: the workbook stores coach slots as repeated column
# groups, which are unpivoted into the composition_coaches /
# coachtype_classes row-per-slot shape.
COMPOSITION_SLOTS = range(1, 16)  # {n}_type / {n}_places / {n}_lying
COACHTYPE_CLASS_SLOTS = range(1, 5)  # class_id_{n} / places_{n} / lying_{n}

CURATED_TABLES = [
    "route_compositions",
    "composition_coaches",
    "compositions",
    "coachtype_classes",
    "coachtypes",
    "coach_classes",
]


def fetch_existing_route_ids(cur) -> set[str]:
    cur.execute("SELECT route_id FROM ontd.routes")
    return {row[0] for row in cur.fetchall()}


def assert_empty_or_replace(cur, replace: bool) -> None:
    populated = []
    for table in CURATED_TABLES:
        cur.execute(f"SELECT count(*) FROM ontd.{table}")
        count = cur.fetchone()[0]
        if count:
            populated.append(f"{table} ({count} rows)")
    if not populated:
        return
    if not replace:
        raise SystemExit(
            "Curated tables already hold data: "
            + ", ".join(populated)
            + "\nThese are hand-maintained after the one-time import, so a "
            "re-import would discard that work. Pass --replace to overwrite "
            "deliberately."
        )
    print("--replace: clearing " + ", ".join(populated))
    cur.execute(
        "TRUNCATE " + ", ".join(f"ontd.{t}" for t in CURATED_TABLES) + " CASCADE"
    )


def load_coach_classes(cur, rows) -> int:
    inserted = 0
    for row in rows:
        class_id = to_text(row.get("class_id"))
        if not class_id:
            continue
        cur.execute(
            "INSERT INTO ontd.coach_classes (class_id, class_main) VALUES (%s, %s) "
            "ON CONFLICT (class_id) DO NOTHING",
            (class_id, to_text(row.get("class_main")) or "Unknown"),
        )
        inserted += cur.rowcount
    return inserted


def load_coachtypes(cur, rows, known_classes: set[str]) -> tuple[int, int, list[str]]:
    """Coach types plus their per-class place breakdown. class_id is a
    soft reference, so slots naming an unknown class are still stored —
    they're reported, not dropped."""
    coach_count = class_count = 0
    unknown_classes: set[str] = set()

    for row in rows:
        coachtype_id = to_text(row.get("coachtype_id"))
        if not coachtype_id:
            continue
        cur.execute(
            """
            INSERT INTO ontd.coachtypes (
                coachtype_id, agency_id, passenger_total, lying_total,
                catering, places_catering, bikes, climatization, plugs,
                weight_gross_t, purchase_price_eur, write_off_years, remarks
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (coachtype_id) DO NOTHING
            """,
            (
                coachtype_id,
                to_text(row.get("agency_id")),
                to_int(row.get("passenger_total")),
                to_int(row.get("lying_total")),
                to_text(row.get("catering")),
                to_int(row.get("places_catering")),
                # 7 rows carry the sheet's "Y" flag in this count column —
                # unknown quantity, so NULL rather than an invented number.
                to_int(row.get("bikes")),
                _flag(row.get("climatization")),
                _flag(row.get("plugs")),
                to_float(row.get("weight_gross_t")),
                to_float(row.get("purchase_price")),
                to_int(row.get("write_off_years")),
                to_text(row.get("remarks")),
            ),
        )
        coach_count += cur.rowcount

        seen: set[str] = set()
        for slot in COACHTYPE_CLASS_SLOTS:
            class_id = to_text(row.get(f"class_id_{slot}"))
            if not class_id or class_id in seen:
                continue  # a class appearing twice in one coach is one entry
            seen.add(class_id)
            if class_id not in known_classes:
                unknown_classes.add(class_id)
            cur.execute(
                "INSERT INTO ontd.coachtype_classes "
                "(coachtype_id, class_id, places, lying) VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (coachtype_id, class_id) DO NOTHING",
                (
                    coachtype_id,
                    class_id,
                    to_int(row.get(f"places_{slot}")) or 0,
                    to_int(row.get(f"lying_{slot}")) or 0,
                ),
            )
            class_count += cur.rowcount

    return coach_count, class_count, sorted(unknown_classes)


def load_compositions(
    cur, rows, known_coachtypes: set[str]
) -> tuple[int, int, list[str]]:
    """Compositions plus their ordered coach slots. coachtype_id IS a real
    FK here, so slots naming an undefined coach type must be skipped."""
    comp_count = slot_count = 0
    unknown_coachtypes: set[str] = set()

    for row in rows:
        composition_id = to_text(row.get("composition_id"))
        if not composition_id:
            continue
        cur.execute(
            "INSERT INTO ontd.compositions "
            "(composition_id, passenger_total, lying_total, weight_gross_t) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (composition_id) DO NOTHING",
            (
                composition_id,
                to_int(row.get("passenger_total")),
                to_int(row.get("lying_total")),
                to_float(row.get("weight_gross_t")),
            ),
        )
        comp_count += cur.rowcount

        position = 0
        for slot in COMPOSITION_SLOTS:
            coachtype_id = to_text(row.get(f"{slot}_type"))
            if not coachtype_id:
                continue
            if coachtype_id not in known_coachtypes:
                unknown_coachtypes.add(coachtype_id)
                continue
            # Positions are renumbered densely: gaps in the sheet's slot
            # columns are layout, not missing coaches.
            position += 1
            cur.execute(
                "INSERT INTO ontd.composition_coaches "
                "(composition_id, position, coachtype_id, places, lying) "
                "VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT (composition_id, position) DO NOTHING",
                (
                    composition_id,
                    position,
                    coachtype_id,
                    to_int(row.get(f"{slot}_places")),
                    to_int(row.get(f"{slot}_lying")),
                ),
            )
            slot_count += cur.rowcount

    return comp_count, slot_count, sorted(unknown_coachtypes)


def load_route_compositions(
    cur, rows, known_compositions: set[str], existing_routes: set[str]
) -> tuple[int, int, int]:
    inserted = skipped_route = skipped_composition = 0
    for row in rows:
        route_id = to_text(row.get("route_id"))
        composition_id = to_text(row.get("composition_id"))
        if not route_id or not composition_id:
            continue
        if route_id not in existing_routes:
            skipped_route += 1  # target-network route with no ONTD counterpart
            continue
        if composition_id not in known_compositions:
            skipped_composition += 1
            continue
        cur.execute(
            "INSERT INTO ontd.route_compositions "
            "(route_id, composition_id, occupancy_rate) VALUES (%s, %s, %s) "
            "ON CONFLICT (route_id) DO NOTHING",
            # occupancy_rate was dropped from the workbook before import;
            # hand-maintained in the DB from here on.
            (route_id, composition_id, None),
        )
        inserted += cur.rowcount
    return inserted, skipped_route, skipped_composition


def _flag(value) -> bool | None:
    """climatization/plugs are 1/0 markers in the sheet, not words."""
    if is_blank(value):
        return None
    return to_int(value) == 1


def main():
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--xlsx", help="Local path to the workbook (skips the Drive fetch)"
    )
    source.add_argument(
        "--sheet-id",
        help="Native Google Sheet id, if the workbook is ever converted from "
        "its current uploaded-.xlsx form",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Overwrite curated tables that already hold data (discards manual edits)",
    )
    args = parser.parse_args()

    conn = connect()
    cur = conn.cursor()

    existing_routes = fetch_existing_route_ids(cur)
    if not existing_routes:
        raise SystemExit(
            "ontd.routes is empty — run db/ontd/loader.py first. Route "
            "assignments are matched against it, so importing now would "
            "store none of them."
        )
    assert_empty_or_replace(cur, args.replace)

    if args.sheet_id:
        url = sheets_export_url(args.sheet_id)
    elif args.xlsx:
        url = None
    else:
        url = workbook_url(
            "ONTD_COMPOSITIONS_ID",
            "ONTD_COMPOSITIONS_KIND",
            "the target-network composition catalog",
        )
    wb = load_workbook(url=url, path=args.xlsx)
    try:
        sheets = {
            name: sheet_row_dicts(wb[name])
            for name in ("classes", "coachtypes", "compositions", "routes")
        }
    finally:
        wb.close()
    for name, rows in sheets.items():
        print(f"  read tab '{name}': {len(rows)} data rows")

    print("\nInserting...\n")
    class_rows = load_coach_classes(cur, sheets["classes"])
    print(f"  ontd.coach_classes:      {class_rows} rows")

    known_classes = {to_text(r.get("class_id")) for r in sheets["classes"]}
    coaches, coach_classes, unknown_classes = load_coachtypes(
        cur, sheets["coachtypes"], known_classes
    )
    print(f"  ontd.coachtypes:         {coaches} rows")
    print(f"  ontd.coachtype_classes:  {coach_classes} rows")

    cur.execute("SELECT coachtype_id FROM ontd.coachtypes")
    known_coachtypes = {row[0] for row in cur.fetchall()}
    comps, slots, unknown_coachtypes = load_compositions(
        cur, sheets["compositions"], known_coachtypes
    )
    print(f"  ontd.compositions:       {comps} rows")
    print(f"  ontd.composition_coaches:{slots} rows")

    cur.execute("SELECT composition_id FROM ontd.compositions")
    known_compositions = {row[0] for row in cur.fetchall()}
    assignments, skipped_route, skipped_comp = load_route_compositions(
        cur, sheets["routes"], known_compositions, existing_routes
    )
    print(f"  ontd.route_compositions: {assignments} rows")

    if unknown_classes:
        print(
            f"\nNOTE {len(unknown_classes)} class id(s) used by coach types but not "
            f"defined on the classes tab (stored anyway — soft reference): "
            f"{unknown_classes}"
        )
    if unknown_coachtypes:
        print(
            f"\nWARNING {len(unknown_coachtypes)} coach type(s) referenced by "
            f"compositions but never defined — those slots were SKIPPED: "
            f"{unknown_coachtypes}"
        )
    if skipped_route:
        print(
            f"\nNOTE {skipped_route} route assignment(s) skipped — target-network "
            f"routes with no counterpart in ontd.routes."
        )
    if skipped_comp:
        print(
            f"\nWARNING {skipped_comp} route assignment(s) skipped — composition "
            f"not defined on the compositions tab."
        )

    conn.commit()
    cur.close()
    conn.close()
    print("\nDone — curated composition catalog imported.")


if __name__ == "__main__":
    main()
