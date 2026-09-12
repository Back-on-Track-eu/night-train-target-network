---
title: Energy calibration
description: Fitted against Deutsche Bahn Trassenfinder runs, and the one term that was not measured.
---

# Energy calibration

How much electricity a night train draws is, unusually for this model, a
measured quantity rather than a tariff read off a page.

## The source

**[Deutsche Bahn Trassenfinder](https://trassenfinder.de)** returns the
technical energy consumption of a specified train over a specified route.
Querying it systematically across many routes, train weights, lengths and
speed profiles produced the dataset the model is fitted to.

## The shape of the model

Consumption on a country leg is the sum of four physically meaningful terms:

- **start-stop energy**, proportional to the train's mass, the cost of
  getting a heavy train moving again after each stop
- **rolling resistance**, per tonne-kilometre over the distance run
- **air resistance**, rising with train length and with the _square_ of
  average speed, which is why a faster schedule costs disproportionately more
  to run
- **on-board supply** for the running time: locomotive systems plus heating,
  air conditioning and lighting in the coaches

Fitting to real runs rather than assuming a flat rate per kilometre is what
makes energy depend on the composition. A longer, heavier train genuinely
costs more to move, where a flat factor would charge every train the same.

## Coach hotel power is an assumption

The Trassenfinder queries were run with hotel power switched off, so the
dataset contains no observation of what it costs to keep a sleeping train
warm, lit and ventilated all night. That figure, around 15 kW per coach, was
added afterwards from engineering judgement.

It matters more for a night train than for a day service, because the load
runs for the whole journey regardless of speed and a night journey is long.
This is the single most valuable measurement that could improve the energy
model.

## Train weight

The model's train weight is **coaches at 80% load, excluding the
locomotive**. Trassenfinder's own figure excludes the traction unit, so the
calibration data was collected on that basis, and the locomotive's own
resistance is folded into the fitted per-kilometre constant rather than
counted as mass.

Changing the weight definition without refitting the model would double-count
the locomotive.

## What this replaced

Until version 1.1.0 the model used a flat 28 kWh per kilometre for every
train. The calibrated model gives a fleet-weighted intensity of about
9.2 kWh/km, roughly a third of the placeholder. Traction energy costs fell by
about two thirds when it landed, and every cost total containing them moved
with it.

<FeedbackForm />
