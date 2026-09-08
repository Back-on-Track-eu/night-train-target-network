---
title: Scenarios
description: What the infrastructure and timetable scenarios do — and what they do not yet do.
---

# Scenarios

A proposal is always computed against a scenario: an assumption about what
the railway looks like and how the timetable is built. The tool offers a
grid of them, and one thing about that grid needs saying up front.

## The grid

Two infrastructure states — **2026** (today's network) and **2032** (the
network as planned upgrades would leave it) — crossed with three timetable
treatments: a baseline, one adding high-speed running where available, and
one applying timetable optimisation.

## The part you need to know

**The two infrastructure columns are currently identical in the database.**

The 2032 scenario is wired end to end — it has its own scenario record,
its own routing graph key, and its own place in the interface — but the
upgraded network data behind it has not yet been built. Selecting 2032
today does not change the track your train runs on, and therefore does not
change your result.

We are saying this here because the interface offers the choice, and a
reader who picks 2032 will reasonably assume it did something. It does
not, yet.

## Why scenarios exist at all

Because the alternative is worse. Without a scenario pinned to each
result, a proposal computed last month and one computed today could differ
because the underlying parameters moved, with nothing recording that they
had. Every stored proposal names the scenario it was computed against, and
scenario records are immutable — so two results are comparable exactly
when they name the same scenario.

That machinery is real and working even while one axis of the grid is not
yet populated. When the 2032 network data lands, results computed against
it will be distinguishable from 2026 results rather than silently
replacing them.

<FeedbackForm />
