---
title: Views of costs and revenue
description: How the cost and revenue breakdown is accounted for the full route, per country, per route section and per stop, and what the units mean.
---

# Views of costs and revenue

<!-- The anchors on this page are linked from the builder's info overlays
     (frontend/src/lib/docsLinks.ts, DOCS_VIEW). The explicit {#…} ids keep
     them stable when a heading is reworded — change an id only together
     with docsLinks.ts. -->

The _Costs and revenue_ section of a proposal shows one breakdown at a time:
every cost item, every revenue item and the operator's margin, for one
**slice** of the route in one **unit**. The model computes every slice once,
on the server, when the proposal is evaluated; the switches above the
breakdown only choose which pre-computed slice to read. Nothing is summed or
divided in the browser.

All slices start from the same annual figures. Every cost is first computed
per event — per segment, per stop call, per stabling stay, per shunting move,
per coach per year — and multiplied up to a year of operation; every ticket
relation (origin, destination, class) carries its annual revenue. A view then
decides **where each of those euros lands**.

## Full route {#full-route}

The whole proposal in one figure set: every segment, stop, stabling stay,
shunting move, coach and ticket relation, both directions, a full year. This
is the view the necessary subsidy and the other headline figures are read
from. Nothing is allocated here — each item is simply summed.

_By trip pair_ (shown only once a route has more than one pair, such as a
Y-shaped route with two branches sharing a trunk) is the same summation for
one outbound-and-return pair alone.

## By country {#by-country}

A trip pair's money split by the countries it runs through. The rule is
that **costs land where the train drives or where the event happens, and
revenue where the passengers sit**:

| Item                                                                                            | Lands in                                                                                                                                                                              |
| ----------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Driver and crew while driving                                                                   | each country by its share of the driving time                                                                                                                                         |
| Driver and crew during a stop, station charges, shunting, stabling                              | the country of that stop, terminal or siding                                                                                                                                          |
| Track access                                                                                    | the country whose infrastructure manager levied the charge — a segment crossing a border is priced by each side at its own rate; a separately charged crossing keeps a distance split |
| Traction energy                                                                                 | the country that supplied the electricity, at its tariff                                                                                                                              |
| Coach maintenance                                                                               | each country by its share of the distance                                                                                                                                             |
| Coach amortisation, financing, fixed overhead                                                   | each country by the pair's distance share                                                                                                                                             |
| Locomotive lease, cleaning                                                                      | each country by the pair's time share                                                                                                                                                 |
| Ticket revenue, additional services, catering, service and stockings, variable overhead, margin | each country by the place-km sold on its territory — a Vienna → Berlin passenger contributes to Austria, Czechia and Germany in proportion to the kilometres ridden in each           |

Country cells partition the pair: their annual figures add up exactly to the
_Full route_ figure. Their per-kilometre figures do not — see [Units](#units).

## By route section {#by-route-section}

Money attributed to a **physical piece of a trip** between two of its stops,
chosen with the two-thumb slider. Every ordered pair of stops is a section,
night stops included, and one section counts **both directions** over the
same piece of track.

Selecting _Hamburg – Berlin_ on a Copenhagen – Hamburg – Berlin – Munich
train means:

- every cost that occurs between Hamburg and Berlin — the segments'
  driver, crew, track access, energy and maintenance, and the stop calls at
  both boundary stops — in full;
- the locomotive lease for the section's own minutes (driving plus dwell);
- a share of the pair's fleet costs (amortisation, financing, fixed overhead)
  by the section's kilometres, and of cleaning by its driving hours;
- a share of shunting and stabling by the section's share of the pair's
  revenue;
- and the **kilometre-proportional revenue of everyone on board there** —
  a Copenhagen → Munich passenger contributes the fraction of their fare
  that matches the kilometres they ride inside the section, together with
  the service, overhead and margin that ride on that fare.

Sections **overlap by construction** — the full-length section _is_ the
whole trip — so, unlike the other views, section cells do not add up to the
route figure. Each section carries per-class sub-cells as well, which do add
up to the section's own total.

## By stop {#by-stop}

Money attributed to **one stop call of one direction**. Only the passengers
who board or alight there count: a through-rider is invisible at a stop,
which is exactly what makes this the view for the question _what does
calling here cost and earn?_

| Item                                                                                            | Lands on the stop                                                                                       |
| ----------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| Driver and crew during the dwell, station charge                                                | directly, from the stop call                                                                            |
| Driver, crew, track access, energy, maintenance of the adjacent segments                        | by the boarding and alighting passengers' share of the place-km on those segments                       |
| Ticket revenue, additional services, catering, service and stockings, variable overhead, margin | of the relations that board or alight here, in full                                                     |
| Every other cost (fleet, lease, cleaning, shunting, stabling)                                   | by the stop's share of the route's place-km, half at each relation's origin and half at its destination |

Stop cells partition the route: over all stops of both directions they add
up to the _Full route_ figure.

## Units {#units}

Every view can be read per year, per operating day, per train-kilometre, per
available place-kilometre or per sold place-kilometre. The two time units
simply divide by the year's operating days; the three per-kilometre units
divide by **the slice's own** kilometres: a country cell by the kilometres
run in that country, a section by its own length, the full route by the
whole cycle. That is what makes a per-kilometre figure comparable between
slices — the Dutch track-access rate reads as the Dutch rate, not as the
Dutch charge spread over the whole journey — and it is also why per-kilometre
figures of different slices cannot be added: rates over different
denominators do not sum. Annual and per-day figures stay additive.

The class switch reads the same slice for one accommodation class: its own
ticket revenue and passenger-side costs directly, and the train-level costs
by the class's share of the train's place-km. Class cells add up to the
"all classes" cell of the same slice.
