---
title: Stop catalogue
description: Which stations exist in the tool, where they came from, and what is known about each.
---

# Stop catalogue

Every station you can plan through comes from a fixed catalogue of about
1,200 stops. It is a deliberate selection rather than every station in
Europe, and how it was built explains both what you can plan and what you
cannot.

## How a station gets in

The catalogue is the union of two sets.

**Stations existing night trains already serve**, taken from the Open Night
Train Database and matched to OpenStreetMap. If a night train stops there
today, it is here.

**Places a night train network arguably should reach**: larger urban areas
currently without night train service, plus tourism and ferry destinations a
night train would plausibly serve.

Each stop records which of the two it is, in a provenance field visible in
the tool ("existing night train stop", "urban area currently without night
train service", and so on). That field answers why one station is offered and
another is not.

## What is known about each stop

Coordinates and country, from OpenStreetMap. Names in several languages, plus
a Latin transliteration and a diacritic-free form, so that searching for
"Zurich" finds "Zürich" and a search in one language finds a station named in
another. The UIC station code where OpenStreetMap has it, which is the join
key to national station tariff documents. The track gauges available.

## Station charges

Every stop carries a charge for calling there, and this is the least sourced
part of the model.

Germany's station price list is transcribed. Everywhere else falls back to a
single flat rate per call, with seventeen countries outstanding. Their
tariffs are public and simply have not been read into the database yet.

For a route whose stops are mostly outside Germany, the
[station charge](/cost/station-charge) line is one number applied everywhere.
That is neither zero nor invented, but it is not a national tariff either.

## Why the catalogue is fixed

Stations are not created on demand. Planning through a station the catalogue
does not contain would mean inventing its coordinates, its charges and its
country, and results computed against an invented station would silently
differ from results computed against a real one. A fixed, versioned catalogue
is what makes two runs of the same proposal comparable.

It also means a station you expect may be absent. That is a gap in the
catalogue rather than a judgement about the station, and it is worth
reporting below.

<FeedbackForm />
