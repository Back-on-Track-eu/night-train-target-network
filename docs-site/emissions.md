---
title: Emissions
description: How the CO2 saving is estimated, and the assumption it rests on.
---

# Emissions

The tool reports a CO2 saving for a proposed route. It is built from two
things of very different quality, and the difference matters.

## The factors: sourced

Per-passenger-kilometre emission factors come from **EEA TERM 2020**:

| Mode                     | g CO2e per passenger-km |
| ------------------------ | ----------------------- |
| Rail (night train proxy) | 33                      |
| Air (intra-EU)           | 160                     |
| Car (average occupancy)  | 143                     |

Two caveats the EEA itself makes. The aviation figure is **CO2 only** — it
excludes contrails and NOx, whose warming effect would push the real
number substantially higher. And the rail figure is an EU-average
passenger-rail value, not a night-train-specific one: it does not reflect
the electricity mix of the countries your route actually runs through, nor
the fact that a night train carries fewer people per tonne than a
commuter service.

The [energy model](/methodology/energy) already computes real, per-country
electricity consumption for a route. Connecting the two — so emissions are
derived from the energy actually drawn, at each country's grid intensity —
is the obvious improvement and has not been made.

## The mode shift: assumed

To convert factors into a saving you must say what the passengers would
otherwise have done. The model assumes **35% would have flown and 20%
would have driven**.

These numbers are placeholders. They are not derived from survey data or
from the specific city pair — they are the same two figures on every
route. A short overnight hop where nobody would fly and a long one
competing directly with aviation get the same 35%.

Since the saving is roughly proportional to these shares, a CO2 figure
from this tool inherits their uncertainty directly. Treat it as an
order-of-magnitude indication of the kind of saving a route could
represent, not as a quantity to put in a policy document.

## Reading it fairly

The direction is not in doubt: rail at 33 g against air at 160 g is a
large difference, and it would remain large under any plausible mode-shift
assumption. What is uncertain is the magnitude for _this_ route.

<FeedbackForm />
