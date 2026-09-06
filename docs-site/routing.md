---
title: How a route is planned
description: From a list of stops to a timetable, a distance and an energy figure.
---

# How a route is planned

You give the tool a list of stops and a train. Everything else — the path
over the rails, the distances, the timetable, the energy — is computed
from there. This page explains that chain, because every cost downstream
depends on it.

## Finding the path

The route between two consecutive stops is found by a self-hosted
[OpenRailRouting](https://github.com/geofabrik/OpenRailRouting) engine, a
rail-aware fork of GraphHopper running on an OpenStreetMap extract of
Europe. It returns the actual track path, its length, and the distance run
in each country.

Gauge is respected rather than assumed away. Standard, Iberian, Russian
and Irish gauge each get their own routing profile, so a route cannot
silently cross a break of gauge that a real train could not.

Routing is done per consecutive stop pair and cached. This has no effect
on the result — stitching pairs gives the same path as routing the whole
list at once, because intermediate stops are hard constraints either way —
but it means a route sharing a leg with one already computed is free.

## From a path to a timetable

Raw driving time from the routing engine assumes a train that cruises at
constant speed and never stops. Two corrections turn that into a schedule:

**Stop dynamics.** A real train brakes before a stop and accelerates
after it. Braking uses a comfortable constant deceleration; acceleration
follows the physics of the locomotive actually pulling the train's weight,
so a heavier train loses more time at every stop. The routing engine
knows nothing of this, so it is added per stop.

**Schedule buffer.** No railway timetables to the theoretical minimum.
Each country adds a percentage margin reflecting how congested and
delay-prone its network is — calibrated against slack observed in real
night train timetables, not chosen. See
[route context](/methodology/route-context).

Dwell time at each stop is then the larger of what the train needs and
what the station needs, which differ: a long train at a short platform is
constrained by the train, a busy station by the station.

## The night window, and mirroring

A night train is defined by when it runs, not just where. The tool builds
an outbound service and mirrors it into a return, and will stretch the
schedule to keep the journey inside the night window rather than arriving
at an hour nobody wants.

This is why time-of-day matters to cost and not only to convenience: the
share of each country run that falls inside its night tariff window
determines what fraction of the [track access charge](/cost/tac) and the
[traction electricity](/cost/energy) is billed at the night rate.

## Suggested extra stops

The tool can propose additional stops that fit within a time budget. A
candidate is priced by what it would actually cost the schedule: the
detour to reach it, the braking and acceleration it forces, and the wait
there. Candidates whose total exceeds the budget, or that would detour the
route too far, are not offered.

## Energy

Once the timetable exists, energy follows from it. The
[energy model](/methodology/energy) takes the train's weight, length,
distance and average speed per country leg and returns kilowatt-hours —
which the [electricity cost](/cost/energy) then prices at each country's
tariff.

## What this does not do

The route is planned in isolation. It does not check whether a path is
actually available at the time requested, whether the capacity exists, or
whether a real infrastructure manager would grant the slot. A route the
tool plans is a technically coherent one, not an allocated one.

<FeedbackForm />
