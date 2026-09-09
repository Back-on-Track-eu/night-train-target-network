---
title: 'Model versions'
---

# Model versions

<!-- Generated from the model registries. Edit the model, not this page —
     anything outside the GENERATED markers survives regeneration. -->

<!-- BEGIN GENERATED: versions -->
| Model | Version | What it computes |
|---|---|---|
| Route & timetable builder | `0.9.34` | Route and timetable builder: turns a list of stops, a train composition, and a few mode selections into a complete route — trip pairs, travel and stopping times with schedule buffers, and a mirrored outbound/return night schedule. |
| Energy model | `1.1.1` | Traction energy model calibrated against Deutsche Bahn Trassenfinder technical runs: start/stop energy per leg, rolling resistance per tonne-kilometre, air resistance growing with train length and the square of average speed, plus a constant auxiliary and hotel-power draw for the running time. Coach hotel power is an assumption, not a measurement - Trassenfinder was queried with it switched off. |
| Demand model | `0.0.2` | Demand model (placeholder): assumes every accommodation class is 70% booked at a flat per-kilometre fare, spread evenly across all connections — a stand-in until a real demand model with directional demand, price sensitivity, and competition from other modes replaces it. |
| Cost & revenue evaluation | `0.9.26` | Cost and revenue evaluation: computes the operator's fixed and variable costs, the charges paid to infrastructure companies, and the ticket revenue of a route, then aggregates the result into views per route, trip pair, country, connection, route section, and stop. |
| Emissions model | `0.1.1` | Climate impact factors: how many grams of CO2-equivalent one passenger-kilometre causes by night train, plane, and car — used for the mode comparison and the CO2-savings estimate. The night-train value is a European average until a country-resolved, energy-based model replaces it. |
| Composition cost model | `0.9.5` | Composition cost model: calibrated purchase, maintenance, cleaning, crew, and availability parameters per train composition, in a 'new' and a 'refurbished' rolling stock family, at 2032 prices. |
| Infrastructure parameter model | `0.9.6` | Infrastructure parameter model: per-country track access charges, station charges, traction energy prices, shunting and stabling, terrain, schedule supplements and minimum stopping times, with EU-average fallbacks — plus the catalog of possible night train stops. Four calibrated domains, each a package under models/infrastructure/ with its own source register, notebooks and published calibration document. |
<!-- END GENERATED: versions -->

<FeedbackForm />
