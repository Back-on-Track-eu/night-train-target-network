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

<!-- The next three headings are linked from the builder's info overlays
     (frontend/src/lib/docsLinks.ts) by their slugs. Renaming one breaks the
     link silently — update docsLinks.ts with it. -->

## The route figures

Under the timetable the builder shows four figures for the route on screen.

**Distance** is the length of the routed track path, stop to stop. **The
countries** are the ones that path runs through, in order.

**Average speed** is that distance divided by the scheduled journey time,
from the first departure to the last arrival. It therefore includes
everything above — braking and acceleration at every stop, the timetable
buffer, and the dwell times — and it is not a top speed. The train matters
twice: its weight and traction set the time lost at each stop, and its top
speed caps every stretch of the path. High-speed lines are used only where
both the train and the country's rules allow it. The same route with a
different train can therefore show a different average, and occasionally a
different path.

**Stops** counts every call, including the first and the last.

## The night and its stops

A night train is timetabled around the night rather than from a departure
time. The automatic timetable places the whole trip symmetrically around
02:30 and runs the return as its mirror image, so both directions spend the
same share of the journey at night.

The night is 00:00–05:00, and every stop falls into one of three kinds:

- **Boarding stop** — the train leaves it before midnight.
- **Alighting stop** — the train reaches it at 05:00 or later.
- **Night stop** — anything in between. Passengers are asleep, so a night
  stop sells no tickets: demand is counted only from boarding stops to
  alighting stops.

On a long route the automatic placement can put the night somewhere
inconvenient — over a strong evening catchment, say. The
[expert timetable](#expert-timetable) lets you fix the night between two stops
of your choice instead. The timetable then centres 00:00–05:00 on that
section: its first stop must be left by 23:59 and its last reached at 05:00
or later. If the section is naturally shorter than five hours, it is
stretched to fit by adding minutes to its legs in proportion to their running
time.

## Expert timetable

The automatic timetable is a sound default and needs no input. Expert mode,
available once a route has been calculated, lets you shape it instead:

- **First departure.** Type the departure into the timetable. Pinned, it
  stays at that time when the route changes; following, it keeps its offset
  from the automatic time, so it moves with it.
- **Minutes on single legs.** Add running time where the model's is too
  optimistic, or to hold a train for a connection.
- **The return.** By default the return mirrors the outbound around 02:30,
  departure and added minutes included. It can instead carry its own times.
- **The night.** Fix the night between two stops, as described
  [above](#the-night-and-its-stops).

Nothing changes until you recalculate, so several adjustments can be made
first. Leaving expert mode drops the overrides, and the next calculation uses
the automatic timetable again.

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
