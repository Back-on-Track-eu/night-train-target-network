---
title: Where the data comes from
description: Every external source this tool draws on, and what each one is used for.
---

# Where the data comes from

Nothing in this tool is invented. Every number either comes from a named
external source, is derived from one by documented arithmetic, or is an
assumption we say is an assumption. This page lists the sources; the
[methodology pages](/methodology/track-access) explain how each was turned
into the parameters the model uses.

## The vocabulary we use about a number

The calibration records classify every value they produce. The words are
worth knowing, because they appear throughout this documentation:

| Term           | What it means                                                                                                 |
| -------------- | ------------------------------------------------------------------------------------------------------------- |
| **sourced**    | Read from a named document at a named location — a section of a network statement, a row of a price list      |
| **derived**    | Computed from sourced values by arithmetic that is written down                                               |
| **benchmark**  | Taken from a comparable country or a pan-European statistic because the country's own figure is not published |
| **assumed**    | Chosen because no source exists. Always carries a stated low–high band                                        |
| **not levied** | The country genuinely does not charge this. Different from missing                                            |
| **missing**    | Nobody has researched it yet. **Never** silently treated as zero                                              |

That last distinction is enforced, not merely intended: a country without
a calibrated charge is priced without that component rather than being
given an invented median, and the database tests assert that such a column
stays indistinguishable from a number nobody entered.

## The railway itself

**OpenStreetMap**, routed through a self-hosted
[OpenRailRouting](https://github.com/geofabrik/OpenRailRouting) engine — a
rail-aware fork of GraphHopper. This supplies the track geometry, the
distances, and which countries a route passes through. Gauge is respected:
the model routes standard, Iberian, Russian and Irish gauge on separate
profiles, so a train cannot silently cross a break of gauge.

## Existing night trains

The **Open Night Train Database (ONTD)**, a community-maintained record of
services actually running in Europe. It supplies the existing-route
context you see in the gallery, part of the stop catalogue, and the
observed timetable slack used to calibrate schedule buffers.

## Energy consumption

**Deutsche Bahn Trassenfinder**, an official tool that returns the
technical energy consumption of a specified train over a specified route.
Querying it across many routes and train configurations produced the
dataset the [energy model](/methodology/energy) is fitted to. This is a
measurement-grade source, and it is the reason energy is one of the
better-founded lines in the model.

## Charges, tariffs and access rules

**National network statements** — the documents every European
infrastructure manager is legally required to publish, setting out what it
charges and on what basis. Thirty are cited for track access alone. These
are the source for [track access](/methodology/track-access),
[traction electricity pricing](/methodology/energy-pricing) and
[shunting and stabling](/methodology/facility).

**Station price lists** for the fee charged per stop. Germany's is
transcribed; seventeen countries are not yet — see
[station charges](/cost/station-charge).

## Country borders

**Marine Regions EEZ land union v4** (Flanders Marine Institute, 2024,
[DOI 10.14284/698](https://doi.org/10.14284/698), CC-BY 4.0). Ordinary
land borders are not enough for a rail network that crosses belts, straits
and tunnels: a train on the Fehmarn crossing or under the Channel is
somewhere, and that somewhere charges for it. Using maritime zones as well
as land means those segments are attributed to a country rather than
falling into an "unknown" bucket.

## Emissions

**EEA TERM 2020** for the per-mode emission factors — see
[emissions](/emissions), and note that the mode-shift assumptions layered
on top of them are ours, not the EEA's.

## Rolling stock costs

**Back-on-Track's own composition cost calibration**, built from vehicle
prices and industry sources. Documented in
[rolling stock](/methodology/compositions).

## One thing that happens exactly once

**Currency conversion and price escalation.** Sources are published in
different currencies and different years. Both conversions happen once, in
the calibration notebooks, at a pinned exchange-rate snapshot and with a
stated escalation to the 2032 evaluation year. From that point on every
number in the database is plain euros at 2032 prices — no calculation
module and no seeding script ever sees a currency or a conversion.

This is why you will not find an exchange rate anywhere in the model, and
why a figure here cannot silently drift with the euro.

## A caution about country figures

A number attached to a country is not automatically that country's own
published tariff. In the facility and route-context domains especially, it
is frequently a European average adjusted for the country's tier, because
no national figure is published. The
[methodology pages](/methodology/facility) say which is which, per domain.

<FeedbackForm />
