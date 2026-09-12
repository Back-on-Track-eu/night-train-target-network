---
title: Terrain and buffer calibration
description: The domain with no sourced values at all, and why it is published anyway.
---

# Terrain and buffer calibration

This domain supplies the per-country factors that shape a
[timetable](/routing): the schedule buffer, the terrain difficulty, the
minimum dwell floor, and high-speed line access.

## Provenance

No value in this domain is sourced from a document. The breakdown is:

- **47** taken from a pan-European statistic
- **102** derived by documented arithmetic
- **131** assumed, each with a stated low-high band
- **5** registered sources, none of which is a per-country tariff

This is the weakest-founded domain in the model. There is no equivalent of a
network statement for how much slack a country's timetable carries, because
infrastructure managers do not publish it.

The five registered sources are listed under
[terrain and buffers](/sources/#terrain-and-buffers): the European
Commission's rail market monitoring report, a UIC leaflet on recovery
margins, the Open Night Train Database's observed timings, and an internal
corridor topography assessment.

## What was used instead

**Observed timetables.** The buffer calibration works backwards from real
night train schedules in the Open Night Train Database: comparing the
scheduled time between stops against the technical minimum shows how much
margin each country's timetabling practice carries. That is an inference from
evidence rather than a citation, which is why it is classified as derived
rather than sourced.

For countries with too little observed night train service to infer from, and
that is most of them, a pan-European value is used, adjusted for the
country's tier.

## Why publish it rather than omit it

A timetable has to have buffers. Running the model with none would produce
journey times no railway would accept and would understate every time-based
cost: the drivers, the crew, the locomotive hire. An assumed buffer with a
stated band is more useful than a pretended absence.

It does mean that where a result is sensitive to schedule slack, it is
sensitive to the least-evidenced part of the model. If two routes differ
mainly in journey time, that difference rests on this page.

## How it would improve

Access to infrastructure managers' own timetable planning parameters would
replace nearly all of it. Failing that, more observed night train timetables
in more countries would move values from assumed to derived, which is one of
the more valuable things the Open Night Train Database can grow into.

<FeedbackForm />
