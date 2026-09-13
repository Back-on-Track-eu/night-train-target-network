---
title: Energy calibration
description: Fitted against Deutsche Bahn Trassenfinder runs, and the one term that was not measured.
---

# Energy calibration

How much electricity a night train draws was measured for this model.

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

## Train weight

The model's train weight is **coaches at 80% load, excluding the
locomotive**. Trassenfinder's own figure excludes the traction unit, so the
calibration data was collected on that basis, and the locomotive's own
resistance is folded into the fitted per-kilometre constant.

<FeedbackForm />
