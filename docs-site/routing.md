---
title: Route planning
description: From a list of stops to a path, a timetable and an energy figure.
---

# Route planning

You give the tool a list of stops and a train. The path over the rails, the
distances, the timetable and the energy all follow from that.

## Finding the path

The route between two consecutive stops comes from a self-hosted
[OpenRailRouting](https://github.com/geofabrik/OpenRailRouting) engine, a
rail-aware fork of GraphHopper running on an OpenStreetMap extract of Europe.
It returns the track path, its length, and the distance run in each country.

Gauge is respected. Standard, Iberian, Russian and
Irish gauge each get their own routing profile, so a route cannot silently
cross a break of gauge that a real train could not.

## From a path to a timetable

Raw driving time from the routing engine assumes a train that cruises at
constant speed and never stops. We thus make two corrections:

**Stop dynamics.** A real train brakes before a stop and accelerates after
it. Braking uses a comfortable constant deceleration; acceleration follows
the physics of the locomotive pulling the train's actual weight, so a heavier
train loses more time at every stop. The routing engine models none of this,
so we add it per stop.

**Schedule buffer.** No railway timetables to the theoretical minimum. Each
country adds a percentage margin reflecting how congested and delay-prone its
network is, calibrated against slack observed in real night train timetables.

Dwell time at each stop is then the larger of what the train needs and what
the station needs. A long train at a short platform is constrained by the
train; a busy station by the station.

## Suggested extra stops

The tool can propose additional stops that fit within a time budget. Each
candidate is priced by what it costs the schedule: the detour to reach it,
the braking and acceleration it forces, and the wait there. Candidates whose
total exceeds the budget, or that would detour the route too far, are not
offered.

## Energy

Once the timetable exists, energy follows from it. The
[energy model](/methodology/energy) takes the train's weight, length,
distance and average speed per country leg and returns kilowatt-hours, which
the [electricity cost](/cost/energy) prices at each country's tariff.

## What this does not do

The route is planned in isolation. It does not check whether a path is
available at the time requested, whether the capacity exists, or whether an
infrastructure manager would grant the slot.

<FeedbackForm />
