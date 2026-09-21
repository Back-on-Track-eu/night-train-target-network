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

Purchase prices stay at the **2026 contract basis** and are deliberately
not escalated: rolling stock for a 2032 network is bought now, and the
write-off and financing run off the contract price — carrying it to 2032 as
well would count inflation twice. The recurring rates on this page (pay,
lease) are 2032 money like every other cost in the tool; see
[price basis](/price-basis) for the rule and its exceptions, and
[data sources](/sources/) for the sources.

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

## The selected composition on a route {#selected-composition}

<!-- Linked from the Train operation tab's ⓘ overlays
     (frontend/src/lib/docsLinks.ts, DOCS_DETAIL_PANEL). -->

The Train operation tab shows the composition a proposal's figures were
computed with and, below it, what one trip costs to run, in three receipts:
the rakes and their upkeep, the locomotive hours, and the people on board.
Fleet euros are annual breakdown leaves divided by the year's departures;
locomotive and staff euros are per single trip, because the two directions
differ in running time and in where the duty boundaries fall.

## Comparing compositions on one route {#composition-comparison}

Every composition in the catalogue is evaluated on the route under the
selected scenario — so the figures in the comparison table are comparable
with each other and with nothing else. Trainsets come first: it is the
first thing that changes when the schedule does. The two density columns
are metres and tonnes per place, the physical price of comfort; they
replace the catalogue's indicative unit costs, which said the same thing
about every route.

## Class allocation

Some costs belong to the whole train rather than to one class of
accommodation: the locomotive, the track access charge, the cleaning.

The model splits these costs per class mostly by how much of the train's length and weight
each class occupies, so a sleeper berth carries more of the shared cost than
a seat. Dining and service space is split evenly per place instead, because
everyone has equal access to it.

<FeedbackForm />
