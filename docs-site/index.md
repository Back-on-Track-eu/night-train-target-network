---
layout: home

hero:
  name: How the model works
  text: Every number, and where it comes from
  tagline: >
    This tool estimates what a European night train route would cost to run,
    what it might earn, and the gap between them. These pages explain how —
    the data, the formulas, and the assumptions we have not yet replaced with
    measurements.
  actions:
    - theme: brand
      text: How to read our numbers
      link: /reading-the-numbers
    - theme: alt
      text: What it costs
      link: /cost/total-cost
    - theme: alt
      text: Open the tool
      # See the nav comment in .vitepress/config.ts — same reason.
      link: /../
      target: _blank

features:
  - title: The cost side is the modelled half
    details: >
      Staff, rolling stock, track access charges, traction electricity,
      station and parking fees — each is computed from a documented formula
      over parameters calibrated against national network statements and
      measured energy runs. This is the part of the model we defend.
  - title: The revenue side is an input, not a forecast
    details: >
      Passenger numbers and fares are set by you, not predicted. The demand
      model is still a placeholder: a flat 70% load factor and flat per-kilometre
      fares. Every revenue and subsidy figure inherits that.
  - title: Nothing here is transcribed by hand
    details: >
      The formulas, parameter tables, standard values and version history on
      this site are generated from the same code that computes the tool's
      results. If a page disagreed with the model, the build would fail.
---
