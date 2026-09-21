# Night Train — Demand Model

DEMAND 0.1.0 is the **manual demand model** (`docs/2026-09-18_manual_demand_guide.md`,
sketch `docs/design/2026-09-18_details-sketch-round7.html`): a potential
demand per year is a request input, split into five traveller groups with
class preferences, seated onto every composition's places by a fixed rule,
spread over the sellable OD pairs by a stop-weight matrix, and attributed
by journey length to the plane, the car or an induced trip. It replaced
the uniform stopgap (a flat 70 % of every class) on 2026-09-19.

**Related documentation:** domain model & pipeline —
[`../README.md`](../README.md) · evaluation model —
[`../evaluation/README.md`](../evaluation/README.md) · emission factors —
[`../emissions/README.md`](../emissions/README.md)

## Structure

```
demand/
├── model.py         # DEMAND_MODEL_VERSION, changelog, every standard value (levels, groups,
│                    #   rounds, OD presets, source split, tariff defaults), open TODOs
├── groups.py        # allocate(places_by_class, demand_by_group) -> Allocation — D14–D19
├── od_matrix.py     # sellable pairs, preset_weights(), od_shares(), pin_pair(), drop_stale_pins()
├── sources.py       # air_share(km), split_sources(loads) — who the passengers are
├── distribute.py    # distribute_demand(route, DemandInputs, fares) -> DemandResult; writes od_pairs
└── calib/vat/       # VAT on rail tickets per country: vat_calibration.py -> seed/*.csv,
                     #   VAT_CALIBRATION.md — seeded into input_params.ticket_vat_rates,
                     #   served by GET /api/params/TicketVat, applied by the frontend only
```

## VAT on tickets (display only)

The model prices **net of VAT** and nothing in `distribute.py` or the
evaluation reads a VAT rate. What the passenger pays on top is shown beside
the fares and the ticket revenue in the builder, from
`input_params.ticket_vat_rates`: per country the rate on a domestic ticket
and the rate on the country's distance share of a cross-border ticket (0
where the international leg is exempt — most of Europe). The frontend forms
a route's effective rate as Σ distance share × rate over the route's
countries (`lib/ticketVat.ts`), with the international rate whenever the
route crosses a border. Rates and provenance:
`calib/vat/VAT_CALIBRATION.md`; regenerate with
`uv run python models/demand/calib/vat/vat_calibration.py`.

## The rule, in one paragraph each

**Allocation (`groups.py`, D14–D19).** Per departure, demand per group =
total ÷ departures × share. Four rounds release 50 / 20 / 20 / 10 % of
every group's demand; in each round the groups are walked in order
(comfort, group, senior, budget, business) and seat what they released:
80 % along the preference list, first class until full then the next; 20 %
spread evenly over the group's *other* listed classes first, and whatever
of that cannot be seated rejoins the rule-followers. A group sits only in
the classes it lists — no overflow, no spill — so demand no listed class
can seat is *not served*. Expected values, never random draws. The rounds
interleave the groups; do not collapse them into one pass (finding 1 of
the guide).

**OD spread (`od_matrix.py`, D25–D30).** Sellable pair = boarding stop
(BOARDING/BOTH) before alighting stop (ALIGHTING/BOTH); NIGHT stops sell
nothing. share(o, d) ∝ w_board(o) × w_alight(d), normalised over the
unpinned pairs onto what the pins leave. Presets write the weights from
each stop's position along the route (0.3 … 3.0, one decimal; *even* is
1). Pinning a pair rescales the other pins by (100 − v) / (100 − old) and
the unpinned pairs through the remainder. Pins whose pair is no longer
sellable are dropped and reported (`od.dropped_pins`). The outbound trip's
matrix is the one the request describes; the return trip is its mirror,
renormalised over its own sellable pairs.

**Sources (`sources.py`).** Per OD pair, the air share is 0 below 300 km,
25 % at 300 km and rises linearly to 100 % at 1 200 km; the rest is
"other", half shifted from the car and half induced. The CO2 saving in the
summary row is air × (plane − train) + car × (car − train) − induced ×
train per passenger-km (factors: `models/emissions/model.py`).

**Places sold (`distribute.py`).** `places_sold` per (trip, pair, class)
= served places of the class per departure × the pair's share × operating
days — a float. `avg_price` is the two-part base fare, fare_per_pax +
fare_per_km × km; services and catering ride on passengers in the
evaluation.

## Request and response

Request (`api/helpers/member_compute.py::validate_demand` /
`normalize_demand`; every part optional):

```jsonc
"demand": {
  "level": "medium",                 // small | medium | large | xl | custom — a label
  "passengers_per_year": 200000,     // both directions; default: the level's total
  "group_shares_pct": { "comfort": 50, "group": 25, "senior": 10, "budget": 10, "business": 5 },
  "od": {
    "preset": "even",                // even | long | mid | short | custom — a label
    "stop_weights": { "board": { "<stop_id>": 1.0 }, "alight": { "<stop_id>": 1.0 } },
    "pinned_shares_pct": { "<origin_stop_id>": { "<destination_stop_id>": 12.5 } }
  }
}
```

The resolved echo always carries the complete block; `passengers_per_year`,
`group_shares_pct`, `stop_weights` and `pinned_shares_pct` are in the
family key, `level` and `od.preset` are not (`models/family/key.py`).

Response: `evaluation.demand` on a member payload and the views endpoint,
`members[].demand` on a family document
(`api/helpers/evaluation_serialize.py::demand_to_dict`): per-trip and
per-year figures by group and class, `not_served`, the OD matrix with
names, weights, pins, `dropped_pins` and `average_distance_km`, and the
`sources`. `GET /api/models` carries the defaults (`demand.defaults`) and
the rule's constants (`demand.constants`) so the frontend previews the same
arithmetic between recalculations.

## Callers

- `models/pipeline.py::run_compute()` — every compute pass (the family's
  members, publish, the on-load refresh) runs `distribute_demand()` after
  `plan_route()`.
- `db/dev/seed.py` — the seeded example proposal runs it on its
  hand-crafted route at the defaults.
- `models/evaluation/summary.py::_demand_kpis()` — the gallery KPIs read
  the source split off the OD loads.

Tests that need *controlled* demand (formula-correctness testing) bypass
this module and set OD pairs directly
(`tests/helpers.py::add_directional_domain_demand()`).

## Tests

`tests/test_83_demand_units.py` — standalone, no stack: the reference
table of the guide (§3) to the cent, the findings, the request boundary,
`distribute_demand()` on a hand-built route. It writes
`tests/fixtures/demand_reference.json`, which the frontend's parity tests
(`frontend/src/lib/demandAllocation.test.ts`, `odMatrix.test.ts`) read, so
the Python and TypeScript ports of the sketch cannot drift.

## Open items

See `OPEN_TODOS` in `model.py`: a demand model that *derives* the
potential demand, and per-class OD matrices.
