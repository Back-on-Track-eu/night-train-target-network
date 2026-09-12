---
title: Rolling stock and compositions
description: How coach and locomotive costs were calibrated, and the one figure with no source.
---

# Rolling stock and compositions

A "composition" is the train itself: how many coaches of which types, what
locomotive pulls them, how many places of each class it offers. It
determines the train's weight and length, which drive
[energy](/cost/energy) and parts of the
[track access charge](/cost/tac), and its purchase price, which drives
[write-off](/cost/coach-amortisation) and
[financing](/cost/financing).

## How coach prices were built

Not as a single price per coach. Coaches differ too much in length and
fit-out for that to mean anything, so the calibration builds a **cost per
metre of vehicle**, separately for new-build and refurbished families, and
applies it to the actual vehicle length. Sleeping cars, couchettes, seated
coaches and catering vehicles each carry their own fit-out cost on top.

Prices are stated at the **2032 evaluation year**, escalated from their
source year exactly once in the calibration — see
[where the data comes from](/sources/).

## Where the prices come from

There is no network statement for rolling stock. Vehicle prices are
commercial, so the calibration triangulates from whatever is on the public
record: audited accounts and annual reports (ÖBB, Italo, ELL, RDC),
procurement awards and orders (Trafikverket's night train tender, Norske tog's
FLIRT Nordic Express, the Caledonian Sleeper Mk5 order, Trenitalia's Intercity
Notte framework, ÖBB's Nightjet orders), studies (the UIC Night Trains 2.0
study, Ramboll's Nachtzugstudie for the BMDV, Steer & KCW for DG MOVE), and
trade press where a contract value was reported but never published.

Crew pay is built the same way, from collective agreements where they exist
(DB–EVG, SJ's Seko scale) and from salary aggregators where they do not.
Escalation to 2032 uses the ECB's Eurosystem staff projections.

Every one of these is listed, with a link where a public one exists, under
[rolling stock and operating costs](/sources/#rolling-stock-and-operating-costs).
Read that list knowing what is in it: audited accounts and aggregated job-board
salaries sit side by side, and they do not deserve equal weight.

## Class allocation

Some costs belong to the whole train rather than to any one class of
accommodation: the locomotive, the track access charge, the cleaning. To
report a cost per sleeper berth or per seat, those shared costs have to be
split.

The model splits them mostly by how much of the train's length and weight
each class occupies — a sleeper berth takes more train than a seat, so it
carries more of the shared cost. Dining and service space is split evenly
per place instead, because everyone has equal access to it.

This is a modelling choice, not a measurement. A different but defensible
split would move per-class figures while leaving the route total
unchanged.

## The assumption worth naming

**Locomotive mass is assumed at 90 tonnes and has no source in this
calibration.** The code says so in as many words.

It matters because train weight enters the track access charge in every
country that levies a per-tonne-kilometre term, and it enters the energy
model's start-stop term. Ninety tonnes is a reasonable figure for a
European electric mainline locomotive, and the error is bounded — real
machines run roughly 80 to 90 tonnes — but it is a judgement, not a
datum.

## An important boundary

Composition data was imported once and the database is the source of
truth from then on. Editing a composition in the tool changes what your
proposal costs; it does not change any calibrated price.

<FeedbackForm />
