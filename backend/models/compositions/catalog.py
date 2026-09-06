"""
catalog.py
==========
The composition catalog: locomotive types, real coach types with their
class sections, and the standard compositions built from them. The data
lives in calib/catalog/*.csv (committed, hand-curated — see the README
there); this module reads and validates it and hands the calibration
notebook typed objects.

Stdlib-only on purpose: db/dev/seed.py executes the pandas-free cells of
02_calibration.ipynb at container start to regenerate the seed CSVs, and
the cell loading the catalog is one of them.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

CATALOG_DIR = Path(__file__).resolve().parent / "calib" / "catalog"
SOURCES_REGISTER = CATALOG_DIR.parent / "data" / "sources_register.csv"

CLASS_MAINS = ("seat", "couchette", "capsule", "sleeper")
MATERIAL_STRATEGIES = ("refurbished", "new")
FAMILY_PREFIX = {"refurbished": "REF", "new": "NEW"}

# Which machine each fleet strategy runs. The lease rate was derived per
# material strategy and the 230 km/h premium IS the new-fleet premium, so
# this mapping keeps loco_types and operator_loco_costs consistent with
# the calibration rather than adding an assumption (CALIBRATION.md, loco
# lease step 6b).
LOCO_TYPE_BY_MATERIAL = {"refurbished": "VECTRON-MS-200", "new": "VECTRON-MS-230"}

# One train manager (Zugchef) per train regardless of length — the
# staffing rule of S07 Tab. 9 (operator billing data). Expressed as 1.19
# attendant-equivalents, i.e. one person at the manager rate.
ZUGCHEF_CREW_FACTOR = 1.19

# Plausibility ceilings for places per metre of revenue space, per class.
# Set from the densest catalog coach of each class plus headroom; a breach
# is a warning that the section is probably mis-classed, not a hard limit.
PLACES_PER_M_CEILING = {
    "seat": 3.2,  # B (78): 78 / 26.4 = 2.95
    "couchette": 2.6,  # B10c10ux: 60 / 26.4 = 2.27
    "capsule": 2.8,  # Luna Rail Seat Pod coach: 66 / 26.4 = 2.50
    "sleeper": 1.8,  # WLBmz (DD): 42 / 26.4 = 1.59
}

COMPOSITION_ID = re.compile(r"^(REF|NEW)-[A-Z0-9]+-(\d+)$")
REGISTER_ID = re.compile(r"^S\d+$")

HEADERS = {
    "loco_types.csv": [
        "loco_type_id",
        "description",
        "traction",
        "weight_t",
        "max_speed_kmh",
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
    "composition_types.csv": [
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
    "composition_formations.csv": ["composition_type_id", "position", "coach_type_id"],
}


class CatalogError(ValueError):
    """The catalog CSVs are inconsistent; the message lists every defect."""


@dataclass(frozen=True)
class LocoType:
    loco_type_id: str
    description: str
    traction: str
    weight_t: float
    max_speed_kmh: float


@dataclass(frozen=True)
class CoachSection:
    """One class section inside a coach: places plus its share of the
    coach's length/weight (basis of the class cost allocation) and crew."""

    class_main: str
    label: str  # DB class_id = "<coach_type_id> - <label>"
    places: int
    m: float
    t: float
    crew: float
    source_ids: tuple[str, ...]


@dataclass(frozen=True)
class CoachType:
    """Real coach type. Weight is gross at full load (tare + 0.1 t per
    place — the convention the energy calibration verifies against). The
    svc_* share is the on-board service section (dining, crew, luggage);
    revenue space is what remains. crew is the coach total incl. any
    service crew."""

    coach_type_id: str
    description: str
    length_m: float
    weight_t: float
    svc_m: float
    svc_t: float
    crew: float
    wifi: bool
    bikes: bool
    aircon: bool
    plugs: bool
    sections: tuple[CoachSection, ...]
    source_ids: tuple[str, ...]
    notes: str

    @property
    def length_wo_svc(self) -> float:
        return self.length_m - self.svc_m

    @property
    def weight_wo_svc(self) -> float:
        return self.weight_t - self.svc_t

    @property
    def places(self) -> int:
        return sum(s.places for s in self.sections)

    @property
    def is_service_coach(self) -> bool:
        return not self.sections


@dataclass(frozen=True)
class Composition:
    """Ordered real-coach list plus the composition-level factors."""

    composition_type_id: str
    description: str
    material_strategy: str
    max_speed_kmh: float
    hsr_allowed: bool
    coaches: tuple[str, ...]  # ordered coach_type ids
    zugchef_crew_factor: float
    length_cost_prop: float  # X in the class allocation (1-X on weight)
    fnb: str  # food & beverages concept
    loco_type_ids: tuple[str, ...]  # position order; two entries = double heading
    source_ids: tuple[str, ...]
    notes: str
    coach_types: tuple[CoachType, ...] = field(compare=False, repr=False)

    @property
    def n_coaches(self) -> int:
        return len(self.coaches)

    @property
    def n_locos(self) -> int:
        return len(self.loco_type_ids)

    @property
    def length_m(self) -> float:
        return sum(c.length_m for c in self.coach_types)

    @property
    def weight_t(self) -> float:
        return sum(c.weight_t for c in self.coach_types)

    @property
    def length_wo_svc(self) -> float:
        return sum(c.length_wo_svc for c in self.coach_types)

    @property
    def weight_wo_svc(self) -> float:
        return sum(c.weight_wo_svc for c in self.coach_types)

    @property
    def total_crew(self) -> float:
        return sum(c.crew for c in self.coach_types) + self.zugchef_crew_factor

    @property
    def places_by_class(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for c in self.coach_types:
            for s in c.sections:
                out[s.class_main] = out.get(s.class_main, 0) + s.places
        return out

    @property
    def places(self) -> int:
        return sum(self.places_by_class.values())


@dataclass(frozen=True)
class Catalog:
    loco_types: dict[str, LocoType]
    coach_types: dict[str, CoachType]
    compositions: tuple[Composition, ...]
    errors: tuple[str, ...]
    warnings: tuple[str, ...]

    def raise_for_errors(self) -> None:
        if self.errors:
            raise CatalogError(
                f"{len(self.errors)} catalog defect(s):\n  " + "\n  ".join(self.errors)
            )


# ---------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------


def _read(catalog_dir: Path, name: str, errors: list[str]) -> list[dict]:
    path = catalog_dir / name
    if not path.is_file():
        errors.append(f"{name}: missing ({path})")
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != HEADERS[name]:
            errors.append(
                f"{name}: header mismatch — expected {HEADERS[name]}, "
                f"found {reader.fieldnames}"
            )
            return []
        return [r for r in reader if any(v.strip() for v in r.values())]


def _ids(value: str) -> tuple[str, ...]:
    return tuple(p.strip() for p in value.split(";") if p.strip())


def _float(row_id: str, col: str, value: str, errors: list[str]) -> float:
    try:
        return float(value)
    except ValueError:
        errors.append(f"[{row_id}] {col} is not a number: {value!r}")
        return 0.0


def _speed(row_id: str, col: str, value: str, errors: list[str]) -> float:
    """Speeds are whole km/h in the seed; keep them ints when they are."""
    v = _float(row_id, col, value, errors)
    return int(v) if v.is_integer() else v


def _int(row_id: str, col: str, value: str, errors: list[str]) -> int:
    if value.strip().isdigit():
        return int(value)
    errors.append(f"[{row_id}] {col} must be a non-negative integer: {value!r}")
    return 0


def _bool(row_id: str, col: str, value: str, errors: list[str]) -> bool:
    if value in ("True", "False"):
        return value == "True"
    errors.append(f"[{row_id}] {col} must be True or False: {value!r}")
    return False


def _known_sources(register: Path | None) -> set[str] | None:
    """Register ids when 01_source_extraction.ipynb has written them;
    None means only the id shape can be checked."""
    if register is None or not register.is_file():
        return None
    with open(register, newline="", encoding="utf-8") as f:
        return {r["source_id"] for r in csv.DictReader(f)}


def load_catalog(
    catalog_dir: Path = CATALOG_DIR, sources_register: Path | None = SOURCES_REGISTER
) -> Catalog:
    """Read and validate the catalog. Structural defects and every rule
    violation that would produce wrong money land in .errors; judgement
    calls (missing sources, implausible densities) in .warnings. Call
    .raise_for_errors() before using the objects."""
    errors: list[str] = []
    warnings: list[str] = []
    known_sources = _known_sources(sources_register)

    def check_sources(row_id: str, value: str) -> tuple[str, ...]:
        ids = _ids(value)
        if not ids:
            warnings.append(f"[{row_id}] no source_ids — TO_VERIFY")
        for sid in ids:
            if not REGISTER_ID.match(sid):
                errors.append(f"[{row_id}] source id {sid!r} is not an S-id")
            elif known_sources is not None and sid not in known_sources:
                errors.append(f"[{row_id}] source {sid} is not in the register")
        return ids

    # --- locomotives ---------------------------------------------------
    loco_types: dict[str, LocoType] = {}
    for r in _read(catalog_dir, "loco_types.csv", errors):
        lid = r["loco_type_id"]
        if lid in loco_types:
            errors.append(f"loco_types.csv: duplicate {lid}")
        loco_types[lid] = LocoType(
            lid,
            r["description"],
            r["traction"],
            _float(lid, "weight_t", r["weight_t"], errors),
            _speed(lid, "max_speed_kmh", r["max_speed_kmh"], errors),
        )

    # --- coach sections ------------------------------------------------
    sections_by_coach: dict[str, list[dict]] = {}
    for r in _read(catalog_dir, "coach_type_sections.csv", errors):
        sections_by_coach.setdefault(r["coach_type_id"], []).append(r)

    # --- coach types ---------------------------------------------------
    coach_types: dict[str, CoachType] = {}
    for r in _read(catalog_dir, "coach_types.csv", errors):
        cid = r["coach_type_id"]
        if cid in coach_types:
            errors.append(f"coach_types.csv: duplicate {cid}")
        if not r["description"].strip():
            errors.append(f"[{cid}] description is required")
        length = _float(cid, "length_m", r["length_m"], errors)
        weight = _float(cid, "weight_t", r["weight_t"], errors)
        svc_m = _float(cid, "svc_length_m", r["svc_length_m"], errors)
        svc_t = _float(cid, "svc_weight_t", r["svc_weight_t"], errors)
        crew = _float(cid, "crew", r["crew"], errors)
        if svc_m > length or svc_t > weight:
            errors.append(f"[{cid}] service section exceeds the coach")

        rows = sorted(sections_by_coach.pop(cid, []), key=lambda s: s["position"])
        if [int(s["position"]) for s in rows if s["position"].isdigit()] != list(
            range(1, len(rows) + 1)
        ):
            errors.append(f"[{cid}] section positions must run 1..n")
        sections = []
        for s in rows:
            sid = f"{cid} section {s['position']}"
            if s["class_main"] not in CLASS_MAINS:
                errors.append(
                    f"[{sid}] class_main {s['class_main']!r} not in {CLASS_MAINS}"
                )
            if not s["section_label"].strip():
                errors.append(f"[{sid}] section_label is required")
            places = _int(sid, "places", s["places"], errors)
            if places == 0:
                errors.append(f"[{sid}] a section without places is service space")
            sections.append(
                CoachSection(
                    s["class_main"],
                    s["section_label"],
                    places,
                    _float(sid, "length_m", s["length_m"], errors),
                    _float(sid, "weight_t", s["weight_t"], errors),
                    _float(sid, "crew", s["crew"], errors),
                    check_sources(sid, s["source_ids"]),
                )
            )

        coach = CoachType(
            cid,
            r["description"],
            length,
            weight,
            svc_m,
            svc_t,
            crew,
            _bool(cid, "wifi", r["wifi"], errors),
            _bool(cid, "bikes", r["bikes"], errors),
            _bool(cid, "aircon", r["aircon"], errors),
            _bool(cid, "plugs", r["plugs"], errors),
            tuple(sections),
            check_sources(cid, r["source_ids"]),
            r["notes"],
        )
        _check_coach(coach, errors, warnings)
        coach_types[cid] = coach
    for cid in sections_by_coach:
        errors.append(f"coach_type_sections.csv: {cid} is not in coach_types.csv")

    # --- formations ----------------------------------------------------
    formation_by_comp: dict[str, list[dict]] = {}
    for r in _read(catalog_dir, "composition_formations.csv", errors):
        formation_by_comp.setdefault(r["composition_type_id"], []).append(r)

    # --- compositions --------------------------------------------------
    compositions: list[Composition] = []
    family_of_coach: dict[str, str] = {}
    for r in _read(catalog_dir, "composition_types.csv", errors):
        cid = r["composition_type_id"]
        if any(k.composition_type_id == cid for k in compositions):
            errors.append(f"composition_types.csv: duplicate {cid}")
        if not r["description"].strip():
            errors.append(f"[{cid}] description is required")
        material = r["material_strategy"]
        if material not in MATERIAL_STRATEGIES:
            errors.append(f"[{cid}] material_strategy must be {MATERIAL_STRATEGIES}")

        rows = sorted(formation_by_comp.pop(cid, []), key=lambda s: int(s["position"]))
        if [int(s["position"]) for s in rows] != list(range(1, len(rows) + 1)):
            errors.append(f"[{cid}] formation positions must run 1..n")
        coach_ids = tuple(s["coach_type_id"] for s in rows)
        if not coach_ids:
            errors.append(f"[{cid}] has no formation rows")
        for coach_id in coach_ids:
            if coach_id not in coach_types:
                errors.append(f"[{cid}] unknown coach type {coach_id!r}")
            elif family_of_coach.setdefault(coach_id, material) != material:
                errors.append(
                    f"[{cid}] {coach_id} is already used by the "
                    f"{family_of_coach[coach_id]} family — coach types are "
                    "single-family"
                )

        loco_ids = _ids(r["loco_type_ids"])
        if not loco_ids:
            errors.append(f"[{cid}] at least one loco_type_id is required")
        for lid in loco_ids:
            if lid not in loco_types:
                errors.append(f"[{cid}] unknown loco type {lid!r}")
            elif lid != LOCO_TYPE_BY_MATERIAL.get(material):
                errors.append(
                    f"[{cid}] {lid} is not the {material}-family machine "
                    f"({LOCO_TYPE_BY_MATERIAL.get(material)}); the lease rate "
                    "is derived per family, so a deviation needs its own rate"
                )

        comp = Composition(
            cid,
            r["description"],
            material,
            _speed(cid, "max_speed_kmh", r["max_speed_kmh"], errors),
            _bool(cid, "hsr_allowed", r["hsr_allowed"], errors),
            coach_ids,
            _float(cid, "zugchef_crew_factor", r["zugchef_crew_factor"], errors),
            _float(cid, "length_cost_prop", r["length_cost_prop"], errors),
            r["food_and_beverages"],
            loco_ids,
            check_sources(cid, r["source_ids"]),
            r["notes"],
            tuple(coach_types[c] for c in coach_ids if c in coach_types),
        )
        _check_composition(comp, loco_types, errors, warnings)
        compositions.append(comp)
    for cid in formation_by_comp:
        errors.append(
            f"composition_formations.csv: {cid} is not in composition_types.csv"
        )

    return Catalog(
        loco_types, coach_types, tuple(compositions), tuple(errors), tuple(warnings)
    )


# ---------------------------------------------------------------------
# rules
# ---------------------------------------------------------------------


def _check_coach(c: CoachType, errors: list[str], warnings: list[str]) -> None:
    cid = c.coach_type_id
    if cid.startswith("EXAMPLE"):
        errors.append(f"[{cid}] example rows do not belong in the catalog")
    if c.is_service_coach:
        if abs(c.svc_m - c.length_m) > 0.01 or abs(c.svc_t - c.weight_t) > 0.01:
            errors.append(
                f"[{cid}] has no sections, so it is a service coach and its "
                "service section must be the whole coach"
            )
        return
    sec_m = sum(s.m for s in c.sections)
    sec_t = sum(s.t for s in c.sections)
    if sec_m > c.length_wo_svc + 0.01:
        errors.append(
            f"[{cid}] sections claim {sec_m:.2f} m of {c.length_wo_svc:.2f} m "
            "revenue space (coach length minus service section)"
        )
    if sec_t > c.weight_wo_svc + 0.01:
        # The 2026-07-22 workbook's NEW-family section weights already
        # exceed the coach weight by 2-7 % (its excl_service quirk); the
        # allocation model normalises shares, so this stays advisory.
        warnings.append(
            f"[{cid}] sections claim {sec_t:.2f} t of {c.weight_wo_svc:.2f} t "
            "revenue weight"
        )
    sec_crew = sum(s.crew for s in c.sections)
    if abs(sec_crew - c.crew) > 1e-9:
        errors.append(
            f"[{cid}] section crew factors sum to {sec_crew} but the coach "
            f"carries {c.crew}"
        )
    for s in c.sections:
        ceiling = PLACES_PER_M_CEILING.get(s.class_main)
        if ceiling and s.m > 0 and s.places / s.m > ceiling:
            warnings.append(
                f"[{cid}] {s.places} {s.class_main} places on {s.m:.1f} m is "
                f"{s.places / s.m:.2f}/m, above the {ceiling}/m ceiling — "
                "check the class"
            )
    night_places = sum(s.places for s in c.sections if s.class_main != "seat")
    if c.crew == 0 and night_places > c.places / 2:
        warnings.append(f"[{cid}] night-accommodation coach without crew — confirm")
    if "TO_VERIFY" in c.notes:
        warnings.append(f"[{cid}] carries TO_VERIFY notes")


def _check_composition(
    k: Composition, loco_types: dict, errors: list[str], warnings: list[str]
) -> None:
    cid = k.composition_type_id
    if cid.startswith("EXAMPLE"):
        errors.append(f"[{cid}] example rows do not belong in the catalog")
    m = COMPOSITION_ID.match(cid)
    if not m:
        errors.append(f"[{cid}] id must be <REF|NEW>-<CONCEPT>-<N_COACHES>")
    else:
        if m.group(1) != FAMILY_PREFIX.get(k.material_strategy):
            errors.append(f"[{cid}] family prefix contradicts {k.material_strategy}")
        if int(m.group(2)) != k.n_coaches:
            errors.append(f"[{cid}] id says {m.group(2)} coaches, has {k.n_coaches}")
    if abs(k.zugchef_crew_factor - ZUGCHEF_CREW_FACTOR) > 1e-9:
        errors.append(
            f"[{cid}] zugchef_crew_factor {k.zugchef_crew_factor} — convention "
            f"is {ZUGCHEF_CREW_FACTOR} (one train manager, any length)"
        )
    if not 0.0 <= k.length_cost_prop <= 1.0:
        errors.append(f"[{cid}] length_cost_prop must be within [0, 1]")
    # max_speed_kmh is the routing profile speed of the composition's
    # material family (200 refurbished / 230 new), not a literal derivation
    # from the slowest coach — a coach rated below that (e.g. a legacy
    # sleeper) is a real constraint the person building the composition
    # weighs by eye and documents in `notes`; a coach-level speed field
    # would need a matching routing profile per speed tier, which the
    # routing setup does not carry. This check only guards against the
    # composition outrunning its own locomotive.
    loco_speeds = [
        loco_types[l].max_speed_kmh for l in k.loco_type_ids if l in loco_types
    ]
    if loco_speeds and k.max_speed_kmh > min(loco_speeds):
        errors.append(
            f"[{cid}] max_speed_kmh {k.max_speed_kmh:.0f} exceeds the "
            f"locomotive's {min(loco_speeds):.0f}"
        )
    if k.hsr_allowed and k.max_speed_kmh < 230:
        warnings.append(f"[{cid}] hsr_allowed below 230 km/h — confirm")
    if k.coach_types and k.places == 0:
        errors.append(f"[{cid}] has no revenue places")
    if "TO_VERIFY" in k.notes:
        warnings.append(f"[{cid}] carries TO_VERIFY notes")


def summary_lines(catalog: Catalog) -> list[str]:
    """Per-composition derived figures for a quick review."""
    lines = [
        (
            f"  {'composition':14} {'coaches':>7} {'length_m':>9} {'weight_t':>9} "
            f"{'places':>7} {'crew':>6}  places by class"
        )
    ]
    for k in catalog.compositions:
        pbc = " · ".join(f"{cls} {n}" for cls, n in k.places_by_class.items())
        lines.append(
            f"  {k.composition_type_id:14} {k.n_coaches:>7} {k.length_m:>9.1f} "
            f"{k.weight_t:>9.1f} {k.places:>7} {k.total_crew:>6.2f}  {pbc}"
        )
    return lines
