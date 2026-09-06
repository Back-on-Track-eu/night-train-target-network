---
title: How to read our numbers
description: Four things worth knowing before you quote a figure from this tool.
---

# How to read our numbers

Four things are easy to get wrong about this model. None of them is a
caveat we would rather you missed — each one changes what a figure means.

## The cost side is modelled. The revenue side is an assumption.

Costs are computed from documented formulas over parameters calibrated
against real sources: national network statements for track access,
measured technical runs for energy, published tariffs for stations. Those
numbers are the claim this tool makes.

Revenue is not. The demand model is version `0.0.2` and explicitly a
placeholder — a flat 70% load factor and flat fares per kilometre by
accommodation class. It does not model who would actually travel, from
where, at what price. So **ticket revenue, the net result, and any
"necessary subsidy" figure are all consequences of an assumption you can
change**, not predictions.

Treat the cost side as an estimate with real evidence behind it, and the
revenue side as a scenario you are setting yourself.

## A missing value is never a zero.

Where a country has not been calibrated, its parameter is left empty
rather than filled with a plausible-looking average. A charge that no
country levies and a charge nobody has researched yet must not look the
same, so the model distinguishes them and the tool prices an uncalibrated
country without that component rather than inventing one.

This is enforced in the code, not just intended: the seed tests assert
that an uncalibrated charge column stays indistinguishable from an
invented number.

## Per-unit figures do not add up, and cannot.

The tool can show costs per country, per connection, per route section
and per stop, normalised per train-kilometre or per place-kilometre.
**Those per-unit cells do not sum to the route's per-unit total.** This is
arithmetic, not a bug: rates over different denominators are not additive.

The identity that does hold is the weighted one — each cell's rate times
that cell's kilometres, summed, equals the route rate times the route
kilometres. If you are adding up per-kilometre numbers from a table, you
are computing something that has no meaning.

## Two "indicative" columns are display only.

The database carries a headline track access rate per train-kilometre and
a flat overnight parking rate per day. Both are shown for orientation and
comparison. **Neither is read by the cost model** — track access is
computed from each country's full component mix, and parking from the
facility calibration. A number on screen labelled indicative did not
produce the total next to it.

## Where to go next

- [What it costs](/cost/total-cost) — one page per line of the cost breakdown.
- [Model versions](/reference/versions) — what each part of the model is at today.
- [What changed](/reference/changelog) — every dated change, with the ones
  that moved published numbers marked.

<FeedbackForm />
