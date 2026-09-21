---
title: Scenarios and main figures
description: What a scenario fixes, and what each of the eight headline figures of a proposal means.
---

# Scenarios and main figures

<!-- The anchors on this page are linked from the builder's info overlays
     (frontend/src/lib/docsLinks.ts). The explicit {#…} ids keep them stable
     when a heading is reworded — change an id only together with
     docsLinks.ts. -->

## The scenario {#the-scenario}

Every figure answers a question with a condition attached: _what would this
train cost, and what would it achieve, under these circumstances?_ A scenario
fixes the circumstances. It has three parts.

**Rail network.** _Infrastructure 2026_ is today's network. _Infrastructure
2032_ (coming soon) is the network expected to exist by 2032, including the
fixed links and line upgrades now under construction or firmly committed —
journeys that take a long detour today become direct.

**Operating conditions.** _Night trains may use high-speed lines_ is a policy
change, not a construction project: infrastructure managers open existing
high-speed track to night trains, and journeys shorten wherever such a line
runs alongside the conventional route. _Optimised timetables_ gives night
trains well-designed paths instead of the generous padding they carry today,
because they rarely hold priority and are planned around other traffic. It is
only modelled together with high-speed lines.

**Price and regulatory measures** (coming soon): a VAT exemption on tickets,
an energy tax exemption, and track access charged at direct cost only.

The **baseline** is Infrastructure 2026 with nothing switched on — the
realistic answer to _what if this train started running this year?_ Every
figure is shown against the baseline with the same train, so the difference
is the scenario's alone.

## The main figures

Eight figures summarise a proposal. Unless stated otherwise they cover a
full year and both directions, at the frequency and demand set in the
Details section.

### Journey time {#journey-time}

The scheduled time of one direction, from the first departure to the last
arrival, averaged over the two directions. It includes braking and
acceleration at every stop, the timetable buffer and the dwell times — see
[Route planning](/routing#from-a-path-to-a-timetable).

### Passenger trips {#passenger-trips}

The passengers the train carries. This is the [demand you set](/demand),
as far as the train's classes can seat it: demand that no class on a
traveller group's list can take is not served and not counted.

### Passenger-km {#passenger-km}

Each passenger trip multiplied by the distance that passenger travels,
summed. It is what the revenue per kilometre and the CO₂e saving are built on.

### Necessary subsidy {#necessary-subsidy}

What the route would need per year from public funds: every cost of running
it plus the operator's profit margin, less ticket, services and catering
revenue — the negative of the [net result](/cost/net). A route whose revenue
covers all of that shows **none**, with its surplus beside it; a negative
subsidy is never shown.

### Shifted from air {#shifted-from-air}

Passengers who would otherwise have flown. The share depends on how far each
passenger travels: nobody under 300 km, a quarter at exactly 300 km, rising
evenly to everyone from 1,200 km. It is applied per origin–destination pair,
so a route with many short hops shifts fewer flights than its length
suggests.

### Shifted from car or induced {#shifted-from-car-or-induced}

Everyone else: half would have driven, and half would not have made the
journey at all — induced travel.

### CO₂e saved {#co2-saved}

The greenhouse gas the route avoids per year, in tonnes of CO₂-equivalent —
including the non-CO₂ warming of aviation, which is most of what a flight
causes. Each shifted passenger-km saves the plane's or the car's factor less
the train's own; an induced passenger-km adds the train's. The factors and
their source are on the [emissions](/emissions) page.

### Subsidy per tonne of CO₂e {#subsidy-per-t-co2}

The necessary subsidy divided by the CO₂e saved: what one tonne avoided costs
the public purse. It reads 0 when the route needs no subsidy, and has no
value when the route saves nothing.

<FeedbackForm />
