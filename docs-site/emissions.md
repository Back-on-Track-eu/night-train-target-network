---
title: Emissions
description: How the CO₂ saving is estimated, and the assumption it rests on.
---

# Emissions

The tool reports a CO₂ saving for a proposed route. It is built from two
inputs of very different quality.

## The factors are sourced

Per-passenger-kilometre factors come from Back-on-Track's 2022 report
[_The Global Warming Reduction Potential of Night-Trains_](https://back-on-track.eu/the-global-warming-reduction-potential-of-night-trains/)
(Figure 3):

| Mode                     | g CO₂e per passenger-km |
| ------------------------ | ----------------------- |
| Night train (average EU) | 14                      |
| Plane (intra-EU)         | 389                     |
| Car (average occupancy)  | 132                     |

They are well-to-wheel, on the EU electricity mix of 2019, and the plane's
figure **includes the non-CO₂ warming of aviation** — contrails, NOx and
water vapour, on the GWP\* basis. That term is what separates it from the
EEA's CO₂-only 160 g, and it makes the night train 28 times cleaner than the
plane per passenger-km. The night-train figure is a European average at a
high load factor; it does not yet reflect the electricity mix of the
countries a route runs through, which an energy-based model will replace it
with.

## The mode shift

Converting factors into a saving requires saying what each passenger would
otherwise have done. The model decides it by journey length, per
origin–destination pair: nobody would have flown under 300 km, a quarter at
exactly 300 km, rising evenly to everyone from 1,200 km. Of the rest, half
would have driven and half would not have travelled at all.

The saving of a year is then

- every passenger-km shifted from the plane × (389 − 14) g,
- plus every passenger-km shifted from the car × (132 − 14) g,
- minus every induced passenger-km × 14 g,

since a shifted passenger still travels on the train, and an induced one adds
the train's emissions without saving anything. The builder shows the result
as [CO₂ saved](/scenarios#co2-saved).

<FeedbackForm />
