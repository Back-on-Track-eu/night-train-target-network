---
title: How terrain and timetable buffers were calibrated
description: The domain with no sourced values at all, and why it is published anyway.
---

# How terrain and timetable buffers were calibrated

This domain supplies the per-country factors that shape a
[timetable](/routing): the schedule buffer, the terrain difficulty, the
minimum dwell floor, and high-speed line access.

## Provenance, without softening it

**No value in this domain is sourced from a document.** The breakdown is:

- **47** taken from a pan-European statistic
- **102** derived by documented arithmetic
- **131** assumed, each with a stated low–high band
- **5** registered sources, none of which is a per-country tariff

This is the weakest-founded domain in the model. There is no equivalent of
a network statement for "how much slack does this country's timetable
carry" — infrastructure managers do not publish it.

## What was used instead

**Observed timetables.** The buffer calibration works backwards from real
night train schedules in the Open Night Train Database: comparing the
scheduled time between stops against the technical minimum reveals how
much margin each country's timetabling practice actually carries. That is
an inference from evidence, not a citation, which is why it is classified
as derived rather than sourced.

For countries with too little observed night train service to infer from —
most of them — a pan-European value is used, adjusted for the country's
tier.

## Why publish it rather than omit it

Because a timetable has to have buffers. Running the model with none would
produce journey times no railway would accept and understate every
time-based cost — the drivers, the crew, the locomotive hire. An assumed
buffer with a stated band is more useful and more honest than a pretended
absence.

But it does mean that where a result is sensitive to schedule slack, it is
sensitive to the least-evidenced part of the model. If you are comparing
two routes whose difference comes down to journey time, that difference is
resting on this page.

## How it would improve

Access to infrastructure managers' own timetable planning parameters would
replace nearly all of it. Failing that, more observed night train
timetables in more countries would move values from _assumed_ to
_derived_ — which is one of the more valuable things the Open Night Train
Database can grow into.

<FeedbackForm />
