---
title: The stop catalogue
description: Which stations exist in the tool, where they came from, and what is known about each.
---

# The stop catalogue

Every station you can plan through comes from a fixed catalogue of about
1,200 stops. It is not "every station in Europe" — it is a deliberate
selection, and knowing how it was built explains both what you can plan
and what you cannot.

## How a station gets in

The catalogue is the union of two sets:

**Stations existing night trains already serve**, taken from the Open
Night Train Database and matched to OpenStreetMap. If a night train stops
there today, it is here.

**Places a night train network arguably should reach** — larger urban
areas currently without night train service, plus tourism and ferry
destinations that a night train would plausibly serve.

Each stop records which of these it is, in a provenance field you can see
in the tool: "existing night train stop", "urban area currently without
night train service", and so on. That field is not decoration — it is the
honest answer to "why is this station offered and that one not".

## What is known about each stop

Coordinates and country, from OpenStreetMap. Names in several languages,
plus a Latin transliteration and a diacritic-free form so that searching
for "Zurich" finds "Zürich" and searching in one language finds a station
named in another. The UIC station code where OpenStreetMap has it, which
is the join key to national station tariff documents. The track gauges
available.

## Station charges: the weak spot

Every stop carries a charge for calling there — and this is the least
sourced part of the whole model.

**Germany's station price list is transcribed.** Everywhere else falls
back to a single flat rate per call. Seventeen countries are outstanding.
Their tariffs are public; they simply have not been read into the
database yet.

The consequence is worth stating plainly: for a route whose stops are
mostly outside Germany, the [station charge](/cost/station-charge) line is
a placeholder. It is not zero, and it is not invented — it is one number
applied everywhere, which is a different kind of wrong from either.

## Why the catalogue is fixed rather than growing

Stations are not minted on demand. If you could plan through a station the
catalogue does not contain, the tool would have to invent its coordinates,
its charges and its country — and results computed against an invented
station would silently differ from results computed against a real one.
Keeping the catalogue fixed and versioned is what makes two runs of the
same proposal comparable.

It also means a station you expect may genuinely be absent. That is a gap
in the catalogue, not a judgement about the station, and it is exactly the
kind of thing worth reporting below.

<FeedbackForm />
