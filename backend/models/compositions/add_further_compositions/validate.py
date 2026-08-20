"""
Consistency checker for the add_further_compositions workspace.

Run from this folder with any Python >= 3.10, no dependencies:

    python validate.py

Checks the six workspace CSVs against each other and against the existing
catalog: header shapes, id uniqueness and collisions, source references,
formation ordering, material-family consistency. Exits non-zero on errors;
warnings are advisory. Ends with a derived per-composition summary (length,
weight, places) so implausible formations stand out before review.

The existing catalog is read from ../calib/seed/*.csv when present (the
regenerated seed artifacts). They are usually absent in a fresh checkout, so
a frozen snapshot of the catalog (2026-08-20, COMPOSITIONS_MODEL 0.9.3) is
embedded as fallback — refresh it here if the catalog grows.
"""

import csv
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEED_DIR = HERE.parent / "calib" / "seed"

ALLOWED_CLASS_MAIN = {"seat", "couchette", "capsule", "sleeper"}
ALLOWED_MATERIAL = {"new", "refurbished"}
KNOWN_LOCO_TYPES = {"VECTRON-MS-200", "VECTRON-MS-230"}
LOCO_BY_MATERIAL = {"refurbished": "VECTRON-MS-200", "new": "VECTRON-MS-230"}
ZUGCHEF_CONVENTION = {False: 1.19, True: 2.38}  # keyed by ">= 10 coaches"

EXPECTED_HEADERS = {
    "sources.csv": [
        "source_id",
        "short_id",
        "title",
        "publisher",
        "pub_year",
        "price_basis_year",
        "currency",
        "kind",
        "url_or_file",
        "date_accessed",
        "reliability_note",
    ],
    "parameter_observations.csv": [
        "source_id",
        "parameter",
        "value",
        "unit",
        "condition",
        "confidence",
        "conversion_note",
        "extraction_note",
    ],
    "coach_types.csv": [
        "coach_type_id",
        "description",
        "length_m",
        "weight_t",
        "svc_length_m",
        "svc_weight_t",
        "crew",
        "wifi",
        "bikes",
        "aircon",
        "plugs",
        "source_ids",
        "notes",
    ],
    "coach_type_sections.csv": [
        "coach_type_id",
        "position",
        "class_main",
        "section_label",
        "places",
        "length_m",
        "weight_t",
        "crew",
        "source_ids",
    ],
    "compositions.csv": [
        "composition_type_id",
        "description",
        "material_strategy",
        "max_speed_kmh",
        "hsr_allowed",
        "zugchef_crew_factor",
        "length_cost_prop",
        "food_and_beverages",
        "loco_type_ids",
        "source_ids",
        "notes",
    ],
    "formations.csv": ["composition_type_id", "position", "coach_type_id"],
}

# Frozen catalog snapshot: coach_type_id -> (family, length_m, weight_t,
# places). Family "" would mean cross-family use, which the catalog forbids.
FALLBACK_COACHES = {
    "A10tuh": ("refurbished", 26.4, 54.48, 56),
    "A9c9ux": ("refurbished", 26.4, 52.88, 36),
    "ABbmpvz": ("new", 26.5, 45.5, 30),
    "ARkimmbz": ("refurbished", 26.4, 50.0, 0),
    "Am": ("refurbished", 26.4, 55.28, 66),
    "Apm": ("refurbished", 26.4, 54.8, 60),
    "B (78)": ("refurbished", 26.4, 56.24, 78),
    "B10c10ux": ("refurbished", 26.4, 54.8, 60),
    "B8c8ux": ("refurbished", 26.4, 53.84, 48),
    "Bc (36)": ("refurbished", 26.4, 52.88, 36),
    "Bcmz (54)": ("refurbished", 26.4, 54.32, 54),
    "Bcmz_5291": ("new", 26.5, 45.5, 40),
    "Bfmpz": ("new", 26.8, 46.0, 70),
    "Bmpz (74)": ("refurbished", 26.4, 55.92, 74),
    "Bmz": ("refurbished", 26.4, 55.28, 66),
    "Bpm (78)": ("refurbished", 26.4, 56.24, 78),
    "Bvcmbz": ("refurbished", 26.4, 54.0, 50),
    "Bvcmz (50)": ("refurbished", 26.4, 54.0, 50),
    "Bvcmz (60)": ("refurbished", 26.4, 54.8, 60),
    "WLABee": ("refurbished", 26.4, 52.4, 30),
    "WLABm (36)": ("refurbished", 26.4, 52.88, 36),
    "WLABmz (DD)": ("refurbished", 26.4, 62.4, 30),
    "WLAmz_7091": ("new", 26.45, 45.5, 20),
    "WLBmz (DD)": ("refurbished", 26.4, 63.36, 42),
}
FALLBACK_COMPOSITION_IDS = {
    "REF-BUD-6",
    "REF-COUCH-6",
    "REF-BAL-9",
    "REF-COUCH-10",
    "REF-BUD-12",
    "REF-PREM-12",
    "NEW-BAL-7",
    "NEW-BAL-14",
}

errors: list[str] = []
warnings: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


def warn(msg: str) -> None:
    warnings.append(msg)


def read_rows(name: str) -> list[dict]:
    path = HERE / name
    if not path.is_file():
        err(f"{name}: file missing")
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != EXPECTED_HEADERS[name]:
            err(
                f"{name}: header mismatch\n"
                f"    expected: {EXPECTED_HEADERS[name]}\n"
                f"    found:    {reader.fieldnames}"
            )
            return []
        return [row for row in reader if any(v.strip() for v in row.values())]


def parse_float(name: str, row_id: str, col: str, value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        err(f"{name} [{row_id}]: {col} is not a number: {value!r}")
        return None


def parse_bool(name: str, row_id: str, col: str, value: str) -> bool | None:
    if value in ("True", "False"):
        return value == "True"
    err(f"{name} [{row_id}]: {col} must be True or False, got {value!r}")
    return None


def check_unique(name: str, values: list[str], what: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            err(f"{name}: duplicate {what}: {value!r}")
        seen.add(value)


def split_ids(value: str) -> list[str]:
    return [part.strip() for part in value.split(";") if part.strip()]


def load_existing_catalog() -> tuple[dict, set[str], str]:
    """Existing coaches {id: (family, length, weight, places)}, existing
    composition ids, and where they came from."""
    coach_csv = SEED_DIR / "coach_types.csv"
    comp_csv = SEED_DIR / "composition_types.csv"
    classes_csv = SEED_DIR / "coach_type_classes.csv"
    if not (coach_csv.is_file() and comp_csv.is_file()):
        return FALLBACK_COACHES, FALLBACK_COMPOSITION_IDS, "frozen snapshot"

    places: dict[str, int] = {}
    if classes_csv.is_file():
        with open(classes_csv, newline="") as f:
            for row in csv.DictReader(f):
                cid = row["coach_type_id"]
                places[cid] = places.get(cid, 0) + int(row["places"])
    family = {"STD-REF": "refurbished", "STD-NEW": "new"}
    coaches = {}
    with open(coach_csv, newline="") as f:
        for row in csv.DictReader(f):
            cid = row["coach_type_id"]
            coaches[cid] = (
                family.get(row["coach_type_operator_id"], ""),
                float(row["coach_type_length_m"]),
                float(row["coach_type_weight_gross_t"]),
                places.get(cid, 0),
            )
    with open(comp_csv, newline="") as f:
        comp_ids = {row["composition_type_id"] for row in csv.DictReader(f)}
    return coaches, comp_ids, "calib/seed"


def main() -> int:
    existing_coaches, existing_comp_ids, catalog_from = load_existing_catalog()
    print(
        f"Existing catalog: {catalog_from} "
        f"({len(existing_coaches)} coaches, {len(existing_comp_ids)} compositions)\n"
    )

    sources = read_rows("sources.csv")
    observations = read_rows("parameter_observations.csv")
    coaches = read_rows("coach_types.csv")
    sections = read_rows("coach_type_sections.csv")
    compositions = read_rows("compositions.csv")
    formations = read_rows("formations.csv")

    # --- sources -----------------------------------------------------------
    check_unique("sources.csv", [r["source_id"] for r in sources], "source_id")
    for row in sources:
        sid = row["source_id"]
        if not (sid.startswith("J") and sid[1:].isdigit()):
            err(f"sources.csv [{sid}]: source_id must be J-prefixed (J01, J02, ...)")
        for col in ("short_id", "title", "url_or_file", "date_accessed"):
            if not row[col].strip():
                err(f"sources.csv [{sid}]: {col} is required")
    workspace_sources = {r["source_id"] for r in sources}

    def check_source_refs(name: str, row_id: str, value: str) -> None:
        """A source_ids value: workspace J-ids or register S-ids."""
        ids = split_ids(value)
        if not ids:
            warn(f"{name} [{row_id}]: no source_ids — flag as TO_VERIFY in notes")
            return
        for sid in ids:
            in_register = sid.startswith("S") and sid[1:].isdigit()
            if sid not in workspace_sources and not in_register:
                err(
                    f"{name} [{row_id}]: unknown source id {sid!r} "
                    "(register it in sources.csv or use an existing S-id)"
                )

    # --- parameter observations -------------------------------------------
    for i, row in enumerate(observations, start=2):
        label = f"line {i}"
        check_source_refs("parameter_observations.csv", label, row["source_id"])
        if not row["parameter"].strip():
            err(f"parameter_observations.csv [{label}]: parameter is required")
        parse_float("parameter_observations.csv", label, "value", row["value"])

    # --- new coach types ---------------------------------------------------
    check_unique(
        "coach_types.csv", [r["coach_type_id"] for r in coaches], "coach_type_id"
    )
    new_coach_dims: dict[str, tuple[float, float]] = {}
    for row in coaches:
        cid = row["coach_type_id"]
        if cid in existing_coaches:
            err(
                f"coach_types.csv [{cid}]: collides with the existing catalog — "
                "changed parameters need a NEW id"
            )
        length = parse_float("coach_types.csv", cid, "length_m", row["length_m"])
        weight = parse_float("coach_types.csv", cid, "weight_t", row["weight_t"])
        svc_l = parse_float("coach_types.csv", cid, "svc_length_m", row["svc_length_m"])
        svc_w = parse_float("coach_types.csv", cid, "svc_weight_t", row["svc_weight_t"])
        parse_float("coach_types.csv", cid, "crew", row["crew"])
        for col in ("wifi", "bikes", "aircon", "plugs"):
            parse_bool("coach_types.csv", cid, col, row[col])
        if None not in (length, svc_l) and svc_l > length:
            err(f"coach_types.csv [{cid}]: svc_length_m exceeds length_m")
        if None not in (weight, svc_w) and svc_w > weight:
            err(f"coach_types.csv [{cid}]: svc_weight_t exceeds weight_t")
        if length is not None and weight is not None:
            new_coach_dims[cid] = (length, weight)
        check_source_refs("coach_types.csv", cid, row["source_ids"])

    # --- sections of new coach types --------------------------------------
    by_coach: dict[str, list[dict]] = {}
    for row in sections:
        by_coach.setdefault(row["coach_type_id"], []).append(row)
    new_coach_places: dict[str, int] = {cid: 0 for cid in new_coach_dims}
    for cid, rows in by_coach.items():
        if cid not in {r["coach_type_id"] for r in coaches}:
            err(
                f"coach_type_sections.csv [{cid}]: coach not defined in "
                "coach_types.csv (existing catalog coaches keep their sections)"
            )
            continue
        positions = sorted(int(r["position"]) for r in rows if r["position"].isdigit())
        if positions != list(range(1, len(rows) + 1)):
            err(
                f"coach_type_sections.csv [{cid}]: positions must be 1..n "
                f"contiguous, got {positions}"
            )
        section_length = 0.0
        for row in rows:
            label = f"{cid} pos {row['position']}"
            if row["class_main"] not in ALLOWED_CLASS_MAIN:
                err(
                    f"coach_type_sections.csv [{label}]: class_main must be one "
                    f"of {sorted(ALLOWED_CLASS_MAIN)}, got {row['class_main']!r}"
                )
            if not row["section_label"].strip():
                err(f"coach_type_sections.csv [{label}]: section_label is required")
            places = row["places"]
            if not (places.isdigit() and int(places) > 0):
                err(
                    f"coach_type_sections.csv [{label}]: places must be a "
                    f"positive integer, got {places!r}"
                )
            elif cid in new_coach_places:
                new_coach_places[cid] += int(places)
            length = parse_float(
                "coach_type_sections.csv", label, "length_m", row["length_m"]
            )
            parse_float("coach_type_sections.csv", label, "weight_t", row["weight_t"])
            parse_float("coach_type_sections.csv", label, "crew", row["crew"])
            check_source_refs("coach_type_sections.csv", label, row["source_ids"])
            if length is not None:
                section_length += length
        if cid in new_coach_dims and section_length > new_coach_dims[cid][0] + 0.01:
            err(
                f"coach_type_sections.csv [{cid}]: section lengths sum to "
                f"{section_length:.2f} m, exceeding the coach's "
                f"{new_coach_dims[cid][0]:.2f} m"
            )
    for row in coaches:
        if row["coach_type_id"] not in by_coach:
            warn(
                f"coach_types.csv [{row['coach_type_id']}]: no sections — "
                "treated as a pure service coach (restaurant); confirm intended"
            )

    # --- compositions ------------------------------------------------------
    check_unique(
        "compositions.csv",
        [r["composition_type_id"] for r in compositions],
        "composition_type_id",
    )
    comp_material: dict[str, str] = {}
    for row in compositions:
        cid = row["composition_type_id"]
        if cid in existing_comp_ids:
            err(
                f"compositions.csv [{cid}]: collides with the existing catalog — "
                "changed parameters need a NEW id"
            )
        material = row["material_strategy"]
        if material not in ALLOWED_MATERIAL:
            err(
                f"compositions.csv [{cid}]: material_strategy must be "
                f"{sorted(ALLOWED_MATERIAL)}, got {material!r}"
            )
        else:
            comp_material[cid] = material
        parse_float("compositions.csv", cid, "max_speed_kmh", row["max_speed_kmh"])
        parse_bool("compositions.csv", cid, "hsr_allowed", row["hsr_allowed"])
        parse_float(
            "compositions.csv", cid, "zugchef_crew_factor", row["zugchef_crew_factor"]
        )
        prop = parse_float(
            "compositions.csv", cid, "length_cost_prop", row["length_cost_prop"]
        )
        if prop is not None and not 0.0 <= prop <= 1.0:
            err(f"compositions.csv [{cid}]: length_cost_prop must be in [0, 1]")
        locos = split_ids(row["loco_type_ids"])
        if not locos:
            err(f"compositions.csv [{cid}]: at least one loco_type_id required")
        for loco in locos:
            if loco not in KNOWN_LOCO_TYPES:
                err(
                    f"compositions.csv [{cid}]: unknown loco type {loco!r} "
                    f"(known: {sorted(KNOWN_LOCO_TYPES)}); a genuinely new "
                    "machine needs a loco_types catalog entry — raise with David"
                )
            elif material in LOCO_BY_MATERIAL and loco != LOCO_BY_MATERIAL[material]:
                warn(
                    f"compositions.csv [{cid}]: {loco} deviates from the "
                    f"{material}-family convention "
                    f"({LOCO_BY_MATERIAL[material]}) — note the reason"
                )
        check_source_refs("compositions.csv", cid, row["source_ids"])

    # --- formations --------------------------------------------------------
    workspace_comp_ids = {r["composition_type_id"] for r in compositions}
    workspace_coach_ids = {r["coach_type_id"] for r in coaches}
    formation_by_comp: dict[str, list[dict]] = {}
    for row in formations:
        formation_by_comp.setdefault(row["composition_type_id"], []).append(row)
    for cid in workspace_comp_ids - set(formation_by_comp):
        err(f"formations.csv: composition {cid} has no formation rows")
    for cid, rows in formation_by_comp.items():
        if cid not in workspace_comp_ids:
            err(f"formations.csv [{cid}]: composition not defined in compositions.csv")
            continue
        positions = sorted(int(r["position"]) for r in rows if r["position"].isdigit())
        if positions != list(range(1, len(rows) + 1)):
            err(
                f"formations.csv [{cid}]: positions must be 1..n contiguous, "
                f"got {positions}"
            )
        material = comp_material.get(cid)
        for row in rows:
            coach = row["coach_type_id"]
            if coach in existing_coaches:
                coach_family = existing_coaches[coach][0]
                if material and coach_family and coach_family != material:
                    err(
                        f"formations.csv [{cid}]: {coach} belongs to the "
                        f"{coach_family} family, composition is {material} — "
                        "coach types are single-family"
                    )
            elif coach not in workspace_coach_ids:
                err(
                    f"formations.csv [{cid}]: unknown coach {coach!r} "
                    "(not in catalog, not in coach_types.csv)"
                )
        # Zugchef convention depends on formation size, so check it here.
        comp_row = next(r for r in compositions if r["composition_type_id"] == cid)
        expected = ZUGCHEF_CONVENTION[len(rows) >= 10]
        try:
            zugchef = float(comp_row["zugchef_crew_factor"])
        except ValueError:
            zugchef = None
        if zugchef is not None and abs(zugchef - expected) > 1e-9:
            warn(
                f"compositions.csv [{cid}]: zugchef_crew_factor {zugchef} "
                f"deviates from the convention ({expected} for "
                f"{len(rows)} coaches) — note the reason"
            )

    # --- derived summary ---------------------------------------------------
    if formation_by_comp and not errors:
        print("Derived composition summary:")
        print(
            f"  {'composition':24} {'coaches':>7} {'length_m':>9} "
            f"{'weight_t':>9} {'places':>7}"
        )
        for cid, rows in sorted(formation_by_comp.items()):
            length = weight = places = 0.0
            complete = True
            for row in rows:
                coach = row["coach_type_id"]
                if coach in existing_coaches:
                    _, coach_l, coach_w, coach_p = existing_coaches[coach]
                elif coach in new_coach_dims:
                    coach_l, coach_w = new_coach_dims[coach]
                    coach_p = new_coach_places.get(coach, 0)
                else:
                    complete = False
                    break
                length += coach_l
                weight += coach_w
                places += coach_p
            if complete:
                print(
                    f"  {cid:24} {len(rows):>7} {length:>9.1f} "
                    f"{weight:>9.1f} {places:>7.0f}"
                )
            else:
                print(f"  {cid:24} {len(rows):>7} {'?':>9} {'?':>9} {'?':>7}")
        print()

    # --- report ------------------------------------------------------------
    example_rows = [
        r["composition_type_id"]
        for r in compositions
        if r["composition_type_id"].startswith("EXAMPLE-")
    ]
    if example_rows:
        warn(
            f"EXAMPLE rows still present ({', '.join(example_rows)}) — "
            "delete them (in all files) before handoff"
        )

    for msg in warnings:
        print(f"WARNING: {msg}")
    for msg in errors:
        print(f"ERROR:   {msg}")
    print(f"\n{len(errors)} error(s), {len(warnings)} warning(s).")
    if not errors:
        print(
            "Workspace is consistent."
            if not warnings
            else "Workspace is consistent — review the warnings."
        )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
