"""
Trassenfinder client for the energy calibration collections.

Extracted from 01_source_extraction.ipynb so the speed sweep (01b) queries the
API through the same payload template, the same mutter resolution and the same
error handling as the main collection. Two notebooks hitting the same API with
two copies of the request body is how the samples silently stop being
comparable.

Behaviour is unchanged from the version that produced samples_all.csv:
build_payload() emits a byte-identical body for the same arguments, so 01 does
NOT need re-running because of this refactor.

What is new is optional and off by default:

  v_max_kmh=      override the booked maximum speed. None keeps the
                  composition's own v_max, which is what 01 does.
  gewichtung=     override the 40/30/30 route weighting. None keeps the
                  template's.
  vermeidung=     override named vermeidung_parameter keys, e.g.
                  {"schnellfahrstrecken_meiden": False}. Merged into the
                  template's block rather than replacing it, so an unnamed key
                  keeps its value.
  zug=            override named zugcharakteristik keys, e.g.
                  {"bremsstellung": "R", "bremshundertstel": 150}. Merged, not
                  substituted. Used by 00_payload_validation.ipynb.
  MIN_INTERVAL_S  minimum spacing between requests, 0.0 by default.

Usage:

    import trassenfinder as tf

    tf.resolve_stations(["AH", "MH"], composition)
    row = tf.query("AH", "MH", composition, v_max_kmh=140)
"""

from __future__ import annotations

import copy
import itertools
import time

import requests

URL = "https://trassenfinder.de/api/web/routen/suche"

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Origin": "https://trassenfinder.de",
    "Referer": "https://trassenfinder.de/",
}

# Trassenfinder applies a token-bucket rate limiter. The original collection ran
# without spacing and did not trip it, so the default stays 0.0 and 01 behaves
# exactly as before. The sweep sets this to a small positive value because it
# fires several requests per segment in quick succession.
MIN_INTERVAL_S: float = 0.0

# Attempts on HTTP 429 before giving up, with a doubling wait between them.
RATE_LIMIT_RETRIES: int = 3

_last_request_at: float = 0.0

# Resolved "mutter" flag per DS100, filled by resolve_station() and reused by
# every subsequent request for that station, in any collection.
MUTTER_CACHE: dict[str, bool] = {}


class TrassenfinderError(RuntimeError):
    """Carries the API response body, which raise_for_status() would discard.

    The body is the only thing that says which of the two stations was
    rejected, so it must survive the failure path.
    """


# =============================================================================
# BRAKING AND LINE CLASS
# =============================================================================
# Both were wrong in the template until 2026-08-30 and both bounded what the
# whole collection could say. They are derived per composition here rather than
# fixed, because both depend on the train.
#
# --- Bremshundertstel -------------------------------------------------------
# BrH = 100 x (sum of braked weights) / (train mass). It sets the permitted
# speed through the brake tables, so a wrong value caps the train silently.
#
# The template carried 70, a freight-grade value. Measured on Hamburg-Hannover
# on 2026-08-30: 70 BrH gives 110.3 km/h average, 130 gives 157.3, and energy
# rises 81% between them.
#
# Braked weight is not published per vehicle for this fleet, so it is modelled
# as a ratio of vehicle mass, anchored on two references:
#   - a disc-braked coach in R (no Mg): 31 t mass, 55 t braked -> ratio 1.77
#   - a modern IC coach in R+Mg (Avmz): about 111 t braked on roughly 51 t
#     mass -> ratio about 2.15, and a whole IC reaching about 205 BrH
# Mg (magnetic rail brake) is mandatory above 160 km/h and cannot be expressed
# in Trassenfinder's bremsstellung field, so its contribution is carried here,
# in the braked weight, which is how it enters a real brake calculation anyway.
#
# The locomotive dilutes the ratio: its braked weight relative to its own mass
# is lower than a coach's, so short formations come out a few BrH below long
# ones. That is real, and it is why this is computed per composition.
COACH_BRAKED_WEIGHT_RATIO: float = 2.10
"""Braked weight per tonne of coach gross mass, R+Mg, modern disc brakes."""

LOCO_BRAKED_WEIGHT_T: float = 120.0
"""Braked weight of the Vectron in R plus its dynamic brake."""

LOCO_MASS_T: float = 87.0
LOCO_LENGTH_M: float = 18.98
LOCO_AXLES: int = 4

# Below this, a loco-hauled passenger train must deduct 8 t of braked weight per
# R+Mg vehicle. Every standard composition sits near 195-201, comfortably clear,
# but the check is asserted rather than assumed.
BRH_MG_DEDUCTION_THRESHOLD: float = 170.0

# Above this Wagenzug length, 1% of braked weight is deducted per started 10 m.
# The longest standard formation is 371.4 m, so this never bites today.
BRH_LENGTH_DEDUCTION_M: float = 400.0

# --- Streckenklasse (EN 15528) ---------------------------------------------
# Letter = permitted axle load, digit = permitted metre load. A train needs the
# lowest class that accommodates its heaviest vehicle on BOTH counts.
LINE_CLASSES: tuple = (
    ("A", 16.0, 5.0),
    ("B1", 18.0, 5.0),
    ("B2", 18.0, 6.4),
    ("C2", 20.0, 6.4),
    ("C3", 20.0, 7.2),
    ("C4", 20.0, 8.0),
    ("D2", 22.5, 6.4),
    ("D3", 22.5, 7.2),
    ("D4", 22.5, 8.0),
)


def bremshundertstel(composition) -> int:
    """Braked-weight percentage for one composition, locomotive included."""
    wagenzug_t = float(composition["coaches_gross_weight_80pct_t_wagenzugmasse"])
    wagenzug_m = float(composition["coaches_length_m_wagenzuglaenge"])

    braked = LOCO_BRAKED_WEIGHT_T + COACH_BRAKED_WEIGHT_RATIO * wagenzug_t

    # Long-formation deduction, per started 10 m over the threshold.
    if wagenzug_m > BRH_LENGTH_DEDUCTION_M:
        over = wagenzug_m - BRH_LENGTH_DEDUCTION_M
        steps = int(over // 10) + (1 if over % 10 else 0)
        braked *= 1.0 - 0.01 * steps

    return round(100.0 * braked / (LOCO_MASS_T + wagenzug_t))


def streckenklasse(composition) -> str:
    """Lowest EN 15528 line class this composition can run on.

    The letter is set by the locomotive: a Vectron at 87 t on four axles is
    21.75 t per axle, which needs D (22.5 t) and rules out every C class
    (20.0 t) whatever the metre load. The digit is set by the heaviest vehicle
    per metre, again the locomotive at 4.58 t/m, which clears the lowest digit.

    So D4 in the old template was over-specified only in its digit. Relaxing it
    to D2 is correct and opens D2 and D3 lines, but it will not rescue the
    branch-line routing failures: those lines are typically C class or below,
    and the locomotive cannot use them at all.
    """
    wagenzug_t = float(composition["coaches_gross_weight_80pct_t_wagenzugmasse"])
    wagenzug_m = float(composition["coaches_length_m_wagenzuglaenge"])
    n_coaches = int(composition["n_coaches"])

    axle_load = max(
        LOCO_MASS_T / LOCO_AXLES,
        wagenzug_t / n_coaches / 4.0,  # standard coaches are four-axle
    )
    metre_load = max(LOCO_MASS_T / LOCO_LENGTH_M, wagenzug_t / wagenzug_m)

    for name, max_axle, max_metre in LINE_CLASSES:
        if axle_load <= max_axle and metre_load <= max_metre:
            return name

    raise ValueError(
        f"no EN 15528 class covers {axle_load:.2f} t/axle and " f"{metre_load:.2f} t/m"
    )


# =============================================================================
# REQUEST TEMPLATE
# =============================================================================
# Passenger long-distance traffic with a locomotive (spfv_lok). Route and
# composition fields are overwritten per request; everything else is held
# constant across every collection so that energy differences are attributable
# to route, train and (in the sweep) booked speed, not to search settings.
#
# Three settings shape the result and matter when interpreting the data:
#
#   schnellfahrstrecken_meiden  high-speed lines avoided, as night trains
#                               generally do not use them
#   gewichtung_parameter        the route returned is a 40/30/30 compromise
#                               between distance, time and energy, not the
#                               shortest path
#   bremshundertstel,           fixed for all compositions, so they act as a
#   streckenklasse,             level effect rather than a difference between
#   bremsstellung               trains

PAYLOAD_TEMPLATE = {
    "infrastruktur_id": 8,
    "sucheinstellungen": {
        "verkehrsart": "spfv_lok",
        "an_abzeit": "2026-08-12T20:00:00+02:00",
        "zeitvorgabe_typ": "abzeit",
        "optimierungsvarianten_berechnen": True,
        "richtungswechsel_zulaessig": True,
        "rangierfahrt_zulaessig": False,
        "vermeidung_parameter": {
            "ueberlastete_meiden": False,
            "sbahnen_meiden": True,
            "nebenbahnen_meiden": False,
            "schnellfahrstrecken_meiden": True,
            "knotenbahnhoefe_meiden": True,
            "notbremsueberbrueckung_meiden": False,
            "wirbelstrombremse_meiden": False,
            "eingleisige_strecken_meiden": False,
            "strecken_mit_vorrang_sgv_meiden": False,
            "strecken_mit_vorrang_spv_meiden": False,
        },
        "initiale_sperrungen_beruecksichtigen": True,
        "wendezeit_min": 30,
        "mit_realistischen_fahrzeiten_optimieren": True,
        "verkehrshalte_nur_an_bahnsteigen": False,
        "einschraenkungen_beachten": True,
        "manueller_fahrzeitzuschlag_prozent": 0,
        "einzelgrenzlastberechnung_zulaessig": False,
        "bauzuschlaege_beachten": False,
        "laengenabhaengige_grenzlasten_verwenden": False,
        "tpn_triebfahrzeugbezeichnung_anzeigen": False,
        "gewichtung_parameter": {
            "streckenlaenge_prozent": 40,
            "fahrzeit_prozent": 30,
            "energie_prozent": 30,
        },
        "zusatzkosten_parameter": {
            "energiebezugspreis_euro_pro_kwh": 0.18,
            "rueckspeisung_euro_pro_kwh": 0.09,
            "kosten_besetzte_tfz_inkl_personal_euro_pro_h": 150,
            "kosten_unbesetzte_tfz_euro_pro_h": 80,
            "kosten_wagenzug_euro_pro_h": 150,
            "kostenpauschale_ungekuppelt_nachschieben_euro": 999,
            "zusaetzlicher_energieverbrauch_pro_wagen_kw": 0,
            "energieverbrauch_hilfsbetriebe_und_wagen_beachten": True,
        },
    },
    "wegpunkte": [
        {
            "zugcharakteristik": {
                # Overwritten per composition by build_payload(). See
                # bremshundertstel() and BRAKING NOTES below: the 70 / "P" this
                # template used until 2026-08-30 was a freight setting that
                # capped every train in the collection at about 110 km/h.
                "bremshundertstel": 195,
                "bremsstellung": "R",
                "aktive_neigetechnik": False,
                "kupplungsbauart": "kn450",
                "dla_u_profile": [],
                "fuehrendes_fahrzeug": "lokomotive",
                "kv_profil": {"p": "N", "c": "N"},
                "nachschiebeart": "ohne",
                "streckenklasse": "D2",  # overwritten; see streckenklasse()
                "traktionsartwechsel": False,
                "triebfahrzeug": {
                    "hauptnummer": "6193",
                    "unternummer": 2,
                    "kennung": "L",
                    "kennung_wert": 80,
                },
                "vorspannart": "ohne",
                "wagenzuglaenge_m": 240,
                "wagenzugmasse_t": 500,
                "wagenanzahl": 0,
                "v_max": 100,
                "zugbeeinflussung_parameter": {
                    "etcs_system_version": "ohne",
                    "lzb": True,
                    "pzb": True,
                },
            },
            "betriebsstelle": {"ds100": "AH", "mutter": True},
        },
        {"betriebsstelle": {"ds100": "MH", "mutter": True}},
    ],
    "nutzer_sperrungen": [],
}


# =============================================================================
# PAYLOAD
# =============================================================================


def build_payload(
    start_ds100,
    end_ds100,
    composition,
    start_mutter,
    end_mutter,
    *,
    v_max_kmh: float | None = None,
    gewichtung: dict | None = None,
    vermeidung: dict | None = None,
    zug: dict | None = None,
) -> dict:
    """Return a request body for one route segment and one composition.

    v_max_kmh overrides the booked maximum speed; None uses the composition's
    own v_max_kmh, which is what the main collection does. gewichtung overrides
    the route weighting; None keeps the template's 40/30/30. vermeidung
    overrides named avoidance flags and is merged, not substituted.

    An avoidance flag changes which line the train runs on, not how fast it
    runs on one line, so it is a stratum and never a swept variable: hold it
    constant within a group or the speed response is confounded with the route.
    """
    body = copy.deepcopy(PAYLOAD_TEMPLATE)

    body["wegpunkte"][0]["betriebsstelle"] = {
        "ds100": str(start_ds100),
        "mutter": start_mutter,
    }
    body["wegpunkte"][1]["betriebsstelle"] = {
        "ds100": str(end_ds100),
        "mutter": end_mutter,
    }

    # Named zug_block, not zug: the parameter is called zug, and shadowing it
    # here makes the override below a silent self-update that changes nothing.
    zug_block = body["wegpunkte"][0]["zugcharakteristik"]
    zug_block["triebfahrzeug"]["hauptnummer"] = str(
        composition["trassenfinder_triebfahrzeug_hauptnummer"]
    )
    zug_block["wagenzuglaenge_m"] = float(
        composition["coaches_length_m_wagenzuglaenge"]
    )
    zug_block["wagenzugmasse_t"] = float(
        composition["coaches_gross_weight_80pct_t_wagenzugmasse"]
    )
    zug_block["wagenanzahl"] = int(composition["n_coaches"])
    zug_block["v_max"] = float(
        composition["v_max_kmh"] if v_max_kmh is None else v_max_kmh
    )

    # Derived per composition, not fixed. Both cap the achievable speed, so a
    # constant here silently bounds what any collection can measure.
    zug_block["bremshundertstel"] = bremshundertstel(composition)
    zug_block["streckenklasse"] = streckenklasse(composition)

    if gewichtung is not None:
        body["sucheinstellungen"]["gewichtung_parameter"] = dict(gewichtung)

    if vermeidung is not None:
        unknown = set(vermeidung) - set(
            body["sucheinstellungen"]["vermeidung_parameter"]
        )
        if unknown:
            raise KeyError(f"unknown vermeidung_parameter key(s): {sorted(unknown)}")
        body["sucheinstellungen"]["vermeidung_parameter"].update(vermeidung)

    if zug is not None:
        unknown = set(zug) - set(zug_block)
        if unknown:
            raise KeyError(f"unknown zugcharakteristik key(s): {sorted(unknown)}")
        zug_block.update(zug)

    return body


# =============================================================================
# TRANSPORT
# =============================================================================


def _post(body: dict) -> requests.Response:
    """POST one body, spacing requests and retrying on HTTP 429."""
    global _last_request_at

    for attempt in range(RATE_LIMIT_RETRIES + 1):
        if MIN_INTERVAL_S:
            wait = MIN_INTERVAL_S - (time.monotonic() - _last_request_at)
            if wait > 0:
                time.sleep(wait)

        response = requests.post(URL, json=body, headers=HEADERS)
        _last_request_at = time.monotonic()

        if response.status_code != 429 or attempt == RATE_LIMIT_RETRIES:
            return response

        # Token bucket refills; back off and try the same request again.
        time.sleep(2.0 * (2**attempt))

    return response  # unreachable, kept for the type checker


def _send(body: dict) -> dict:
    """POST a body and return the parsed JSON, raising on either failure mode."""
    response = _post(body)

    if response.status_code != 200:
        raise TrassenfinderError(f"HTTP {response.status_code}: {response.text[:300]}")

    data = response.json()

    # The API returns 200 with a "failure" block when no route can be built.
    if "failure" in data:
        raise ValueError(data["failure"]["message"])

    return data


def query_raw(
    start_ds100,
    end_ds100,
    composition,
    **overrides,
) -> dict:
    """The full parsed response, unreduced.

    query() keeps three fields. Everything Trassenfinder returns about how the
    run was computed - per-section speeds, limiting factors, the vehicle it
    resolved - is discarded there and visible here. Use it when a number looks
    wrong and you need to see what the API actually said.
    """
    return _send(
        build_payload(
            start_ds100,
            end_ds100,
            composition,
            MUTTER_CACHE.get(str(start_ds100), True),
            MUTTER_CACHE.get(str(end_ds100), True),
            **overrides,
        )
    )


def query(
    start_ds100,
    end_ds100,
    composition,
    *,
    v_max_kmh: float | None = None,
    gewichtung: dict | None = None,
    vermeidung: dict | None = None,
    zug: dict | None = None,
) -> dict:
    """Query one route segment for one composition.

    Returns:
        Dictionary with energy consumption, distance and technical travel time.

    Raises:
        TrassenfinderError: on a non-200 response, carrying the API message.
        ValueError: if the API accepts the request but cannot build a route.
    """
    body = build_payload(
        start_ds100,
        end_ds100,
        composition,
        MUTTER_CACHE.get(str(start_ds100), True),
        MUTTER_CACHE.get(str(end_ds100), True),
        v_max_kmh=v_max_kmh,
        gewichtung=gewichtung,
        vermeidung=vermeidung,
        zug=zug,
    )

    data = _send(body)

    route = data["result"]["gewichtete_route"]
    summary = route["zusammenfassung"]

    # Energy is decomposed per route point into traction, locomotive
    # auxiliaries and coach load. Only the total appears in zusammenfassung, and
    # only the total was collected until 2026-08-30. The split matters: traction
    # scales with the square of speed, auxiliaries with time, and fitting one
    # coefficient to their sum makes the speed term absorb both.
    #
    # THESE FIELDS ARE CUMULATIVE RUNNING TOTALS, NOT PER-SEGMENT INCREMENTS.
    # Point 0 reads zero and the last point carries the whole trip, so the value
    # wanted is the last point, never the sum. Summing them over-counts by about
    # half the number of route points: measured at 22x the trip total at the
    # median and 145x on the longest route, while a two-point route came out
    # exactly right, which is the signature of a cumulative series.
    last = route["routenpunkte"][-1].get("energieverbrauch_info") or {}
    traction = last.get("energieverbrauch_traktion_kwh", 0.0)
    auxiliaries = last.get("energieverbrauch_hilfsbetriebe_kwh", 0.0)
    coaches = last.get("energieverbrauch_wagen_kwh", 0.0)
    components = last.get("energieverbrauch_gesamt_kwh", 0.0)

    # --- speed profile ------------------------------------------------------
    # Each route point carries the technical speed on the segment that follows
    # it, in hectometres per hour, and the cumulative distance to that point.
    # Together they are the actual speed profile, and it is captured because it
    # cannot be reconstructed later from an average.
    #
    # It matters because drag is convex: a leg averaging 130 km/h with a 230
    # km/h section and slow approaches burns more than one held steady at 130.
    # The quantity a v^2 drag law actually responds to is the distance-weighted
    # ROOT MEAN SQUARE speed, not the arithmetic mean, and their ratio says how
    # much the average-speed formulation understates.
    #
    # The deployed model still has to use average speed, because that is all
    # CountryLeg carries. These columns are there to measure that error, not to
    # replace the input.
    points = route["routenpunkte"]
    seg_len = []
    seg_v = []
    seg_fast = []
    for first, second in itertools.pairwise(points):
        length_km = (second.get("laufende_hm", 0) - first.get("laufende_hm", 0)) / 10
        if length_km <= 0:
            continue
        seg_len.append(length_km)
        seg_v.append(first.get("geschwindigkeit_technisch_hmh", 0) / 10)
        seg_fast.append(
            bool((first.get("strecke_info") or {}).get("schnellfahrt", False))
        )

    total_len = sum(seg_len)
    if total_len > 0:
        v_mean_dist = sum(a * b for a, b in zip(seg_len, seg_v)) / total_len
        v_rms = (sum(a * b * b for a, b in zip(seg_len, seg_v)) / total_len) ** 0.5
        v_peak = max(seg_v)
        fast_share = sum(a for a, f in zip(seg_len, seg_fast) if f) / total_len * 100
    else:
        v_mean_dist = v_rms = v_peak = fast_share = 0.0

    return {
        # zusammenfassung is authoritative for the total. The components' own
        # total is carried alongside it rather than assumed equal, so that a
        # divergence — regeneration netted off one but not the other, say —
        # shows up as a column to inspect instead of vanishing into the fit.
        "energy_kwh": summary["energieverbrauch_kwh"],
        "energy_components_kwh": round(components, 1),
        "energy_traktion_kwh": round(traction, 1),
        "energy_hilfsbetriebe_kwh": round(auxiliaries, 1),
        "energy_wagen_kwh": round(coaches, 1),
        "distance_km": summary["weglaenge_hm"] / 10,
        "travel_time_min": summary["fahrzeit_technisch_min"],
        # Free on every request, and an independent cross-check for the TAC and
        # station-charge calibrations, which derive them by other means.
        "trassenpreis_eur": summary.get("trassenpreis_euro"),
        "stationspreis_eur": summary.get("stationspreis_euro"),
        # 356 EUR against 1906 kWh is 0.1868 EUR/kWh, not the 0.18 requested.
        # Something is netted into one figure and not the other, most likely
        # regeneration. Captured so that can be settled without re-collecting.
        "preis_energie_eur": summary.get("preis_energie_euro"),
        "kosten_fahrzeuge_personal_eur": summary.get("kosten_fahrzeuge_personal_euro"),
        "marktsegment": summary.get("marktsegment"),
        # The speed profile, reduced to what a v^2 law needs.
        "v_peak_kmh": round(v_peak, 1),
        "v_mean_dist_kmh": round(v_mean_dist, 1),
        "v_rms_kmh": round(v_rms, 1),
        "schnellfahrt_share_pct": round(fast_share, 1),
        "n_route_points": len(points),
        # Never inspected, two keys, and free to carry.
        "maximalwerte": str(route.get("maximalwerte")),
        "speed_unzulaessig": route.get("punkt_zu_punkt_geschwindigkeit_unzulaessig"),
    }


# =============================================================================
# STATION PRE-FLIGHT
# =============================================================================
# "mutter" is a fixed property of each Betriebsstelle, not a free choice.
# Trassenfinder rejects a Mutterbetriebsstelle sent as a child and a child sent
# as a mother, both with HTTP 400 and no indication which end is at fault. The
# flag is therefore resolved per station once, before any collection starts: an
# invalid code then costs one request instead of one per composition, and the
# collection loops run with a warm cache and no retries.

REFERENCE_DS100 = "AH"  # Hamburg Hbf, a valid Mutterbetriebsstelle
REFERENCE_MUTTER = True


def resolve_station(ds100, composition) -> bool:
    """Determine and cache whether a DS100 is a Mutterbetriebsstelle.

    Probes against REFERENCE_DS100, trying mother first. Returns True if the
    station could be resolved, False if Trassenfinder rejects it either way.
    """
    ds100 = str(ds100)

    if ds100 in MUTTER_CACHE:
        return True

    if ds100 == REFERENCE_DS100:
        MUTTER_CACHE[ds100] = REFERENCE_MUTTER
        return True

    for mutter in (True, False):
        body = build_payload(
            REFERENCE_DS100, ds100, composition, REFERENCE_MUTTER, mutter
        )
        response = _post(body)

        # A routing failure still proves the station itself is valid.
        if (
            response.status_code == 200
            or "Ungültige Betriebsstelle" not in response.text
        ):
            MUTTER_CACHE[ds100] = mutter
            return True

    return False


def resolve_stations(stations, composition) -> list[str]:
    """Resolve every station in one pass. Returns the unresolvable ones."""
    return [s for s in stations if not resolve_station(s, composition)]
