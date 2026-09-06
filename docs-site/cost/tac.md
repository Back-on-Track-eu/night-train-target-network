---
title: 'Track access charge'
description: "What the operator pays each country's infrastructure company for using the track."
---

# Track access charge

<!-- Everything between here and the next marker is hand-written and
     survives regeneration. The generated block below carries the formula,
     the input legend and the cross-links. -->

## What this is

What the operator pays each country's infrastructure manager for the right
to run over its track. For a cross-border night train this is usually the
single largest infrastructure cost, and the most variable.

There is no European track access charge. Every country charges its own
mix, and the mixes barely resemble each other: a rate per kilometre driven
(often different at night), a rate per tonne of train weight and
kilometre, in some countries a rate per seat, a flat administrative
add-on, a fee for each stop, a share of the ticket revenue earned there,
and a surcharge for running through a congested area at peak. A country
that does not levy a term simply has no such term — it is absent, not zero.

Because night trains run across the day/night boundary, the model splits
each country run by the clock rather than pricing it entirely one way: the
share of time actually spent inside a country's night window is charged at
its night rate. The same is done for peak surcharges, with one honest
compromise — the tool knows a departure's clock time but not its day of
the week, so a Monday-to-Friday peak is charged at five-sevenths of its
value rather than pretended to be all or nothing.

This is the best-sourced part of the model: 35 values read from a named
locator in a national network statement, 10 derived by documented
arithmetic, 1 assumed with a stated band, across 30 cited documents. See
[how track access was calibrated](/methodology/track-access).

<!-- BEGIN GENERATED: formula -->
<a id="f-calc-tac_eur"></a>

What the operator pays each country's infrastructure company for using the track.

### The formula

$$ C_{TAC} = \sum_{seg}\Big[\sum_{c \in seg} \big( d_{c}\,(1{-}\nu_c)\,b_{day,c}\,\mu_c + d_{c}\,\nu_c\,b_{night,c} + d_{c}\,(\gamma_c m_{gross} + \sigma_c P + \phi_c + \kappa_c \pi_c) \big) + \sum_{stop} h_{country(stop)} + \rho_{c}\,R_{seg,c} + \sum_{x \in seg}\big(F_x + f_x n_{seg}\big)\Big] $$

| | Symbol | Meaning | Unit | Where it comes from |
|---|---|---|---|---|
| Input | `d_c` | Distance driven in this country on this segment | km | computed upstream |
| Input | `nu_c` | Share of the run in this country priced at the night rate | – | [tac_night_share](/reference/formulas#f-calc-tac_night_share) |
| Input | `b_day,c` | The country's day rate per train-kilometre | €/train-km | [track_tac_b_day](/reference/parameters#p-input_params-track_infrastructures-track_tac_b_day) |
| Input | `b_night,c` | The country's night rate per train-kilometre | €/train-km | [track_tac_b_night](/reference/parameters#p-input_params-track_infrastructures-track_tac_b_night) |
| Input | `gamma_c` | The country's rate per tonne of train weight and kilometre | €/(t·km) | [track_tac_gamma](/reference/parameters#p-input_params-track_infrastructures-track_tac_gamma) |
| Input | `m_gross` | Weight of the whole train — coaches plus locomotives | t | [loco_type_weight_t](/reference/parameters#p-input_params-loco_types-loco_type_weight_t) |
| Input | `sigma_c` | The country's rate per place and kilometre | €/(place·km) | [track_tac_seat_km](/reference/parameters#p-input_params-track_infrastructures-track_tac_seat_km) |
| Input | `P` | Places the train offers | places | computed upstream |
| Input | `phi_c` | The country's flat administrative add-on per train-kilometre | €/train-km | [track_tac_fixed_per_train_km](/reference/parameters#p-input_params-track_infrastructures-track_tac_fixed_per_train_km) |
| Input | `kappa_c` | The country's congestion surcharge per train-kilometre | €/train-km | [track_tac_congestion_surcharge_eur_km](/reference/parameters#p-input_params-track_infrastructures-track_tac_congestion_surcharge_eur_km) |
| Input | `pi_c` | Share of the run in this country falling in rush hour | – | [tac_peak_share](/reference/formulas#f-calc-tac_peak_share) |
| Input | `mu_c` | Factor the day rate is multiplied by over the rush-hour share of the run (1 outside it) | factor | [track_tac_peak_multiplier](/reference/parameters#p-input_params-track_infrastructures-track_tac_peak_multiplier) |
| Input | `h_country(stop)` | Fee for making one stop, at that stop's own country rate. A trip's first segment pays for both of its ends, since no other segment owns the starting station | €/stop | [track_tac_per_stop](/reference/parameters#p-input_params-track_infrastructures-track_tac_per_stop) |
| Input | `rho_c` | Share of the ticket revenue earned in this country that the infrastructure manager takes | fraction | [track_tac_revenue_share](/reference/parameters#p-input_params-track_infrastructures-track_tac_revenue_share) |
| Input | `R_seg,c` | Ticket revenue attributable to this segment in this country, per train run | €/trip | computed upstream |
| Input | `F_x` | Charge for crossing a separately billed link, per train | €/traverse | [passage_fixed_eur](/reference/parameters#p-input_params-passage_charges-passage_fixed_eur) |
| Input | `f_x` | Charge for crossing a separately billed link, per passenger | €/passenger | [passage_per_passenger_eur](/reference/parameters#p-input_params-passage_charges-passage_per_passenger_eur) |
| Input | `n_seg` | Passengers aboard on this segment, per train run | passengers | computed upstream |
| **Result** | `C_TAC` | Annual track access charges | €/year | — |

**Feeds into:** [infrastructure_total_eur](/cost/infrastructure-total)
<!-- END GENERATED: formula -->

<FeedbackForm />
