---
title: Emissions
description: How the CO₂ saving is estimated, and the assumption it rests on.
---

# Emissions

The tool reports a CO₂ saving for a proposed route. It is built from two
inputs of very different quality.

## The factors are sourced

Per-passenger-kilometre emission factors come from **EEA TERM 2020**
([Transport and environment report 2020, "Train or plane?"](https://www.eea.europa.eu/en/analysis/publications/transport-and-environment-report-2020)):

| Mode                     | g CO₂e per passenger-km |
| ------------------------ | ----------------------- |
| Rail (night train proxy) | 33                      |
| Air (intra-EU)           | 160                     |
| Car (average occupancy)  | 143                     |

Two caveats come from the EEA. The aviation figure is CO₂ only: it
excludes contrails and NOx, whose warming effect would push the real number
substantially higher. And the rail figure is an EU-average passenger-rail
value rather than a night-train-specific one. It reflects neither the
electricity mix of the countries a route runs through nor the fact that a
night train carries fewer people per tonne than a commuter service.

## The mode shift

Converting factors into a saving requires saying what the passengers would
otherwise have done. The model assumes **35% would have flown and 20% would
have driven**.

<FeedbackForm />
