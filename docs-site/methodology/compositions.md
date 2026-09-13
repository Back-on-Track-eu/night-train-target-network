---
title: Rolling stock calibration
description: How coach and locomotive costs were built, and the one figure with no source.
---

# Rolling stock calibration

A composition is the train itself: how many coaches of which types, what
locomotive pulls them, how many places of each class it offers. It determines
the train's weight and length, which drive [energy](/cost/energy) and parts
of the [track access charge](/cost/tac), and its purchase price, which drives
[write-off](/cost/coach-amortisation) and [financing](/cost/financing).

## How coach prices were built

The calibration builds a **cost per
metre of vehicle**, separately for new-build and refurbished families, and
applies it to the actual vehicle length. Sleeping cars, couchettes, seated
coaches and catering vehicles each carry their own fit-out cost on top.

Prices are stated at the 2032 evaluation year, escalated from their source
year exactly once in the calibration. See [data sources](/sources/).

## Where the prices come from

There is no network statement for rolling stock. Vehicle prices are
commercial, so the calibration triangulates from what is on the public
record: audited accounts and annual reports (ÖBB, Italo, ELL, RDC),
procurement awards and orders (Trafikverket's night train tender, Norske
tog's FLIRT Nordic Express, the Caledonian Sleeper Mk5 order, Trenitalia's
Intercity Notte framework, ÖBB's Nightjet orders), studies (the UIC Night
Trains 2.0 study, Ramboll's Nachtzugstudie for the BMDV, Steer and KCW for DG
MOVE), and trade press where a contract value was reported but never
published.

Crew pay is built the same way, from collective agreements where they exist
(DB with EVG, SJ's Seko scale) and from salary aggregators where they do not.
Escalation to 2032 uses the ECB's Eurosystem staff projections.

Every one of these is listed, with a link where a public one exists, under
[rolling stock and operating costs](/sources/#rolling-stock-and-operating-costs).

## Class allocation

Some costs belong to the whole train rather than to one class of
accommodation: the locomotive, the track access charge, the cleaning.

The model splits these costs per class mostly by how much of the train's length and weight
each class occupies, so a sleeper berth carries more of the shared cost than
a seat. Dining and service space is split evenly per place instead, because
everyone has equal access to it.

<FeedbackForm />
