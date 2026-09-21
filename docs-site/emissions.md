---
title: Emissions
description: How the CO₂ saving is estimated, and the assumption it rests on.
---

# Emissions

The tool reports a greenhouse gas saving for every proposed route, in tonnes
of **CO₂-equivalent (CO₂e)** per year. It is built from two inputs of very
different quality.

## The factors are sourced

Per-passenger-kilometre factors come from Back-on-Track's 2022 report
[_The Global Warming Reduction Potential of Night-Trains_](https://back-on-track.eu/the-global-warming-reduction-potential-of-night-trains/)
(Figure 3):

| Mode                     | g CO₂e per passenger-km |
| ------------------------ | ----------------------- |
| Night train (average EU) | 14                      |
| Plane (intra-EU)         | 389                     |
| Car (average occupancy)  | 132                     |

All three are **well-to-wheel** — fuel and electricity production included —
for the EU energy mix of the reference year 2019, built on the IEA's
greenhouse gas intensities of passenger transport.

The plane's figure is the one that differs from most published comparisons.
The IEA puts a plane at 144 g without the **non-CO₂ effects of aviation** —
contrails, NOx and water vapour, released high in the atmosphere. The report
adds them by applying a radiative forcing factor of 3.0 to the CO₂ from the
fuel burnt, the best current estimate (Lee et al. 2021) on the **GWP\***
basis, which measures the warming a flight causes now rather than averaged
over a hundred years. It also adds 8 % for flights not flying straight lines.
The result makes a plane 28 times more harmful than a night train per
passenger-km.

The night train's 14 g is the IEA's average for non-urban rail, at a high
load factor. The report keeps it on purpose although it expects night trains
to do better. It does not yet reflect the electricity mix of the countries a
route runs through, nor how full this particular train is — an energy-based
model will replace it.

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
as [CO₂e saved](/scenarios#co2-saved).

The report itself counts only the shift from the plane, and names the car as
additional potential. Counting the car here makes the figure a little larger;
counting induced travel against it makes it a little smaller.

<FeedbackForm />
