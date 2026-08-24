# Night Train — Energy Model

This folder contains the energy consumption model for night train routes.

**Related documentation:** model layer overview — [`../README.md`](../README.md)
· evaluation model (consumes `energy_kwh`) —
[`../evaluation/README.md`](../evaluation/README.md) · onboarding guide for the
energy team — [`ONBOARDING.md`](ONBOARDING.md)

**Current status:** Dummy implementation using a flat 28.0 kWh/km factor.
The real regression-based model needs to be developed and calibrated.
That is the purpose of this workstream.

---

## What we need the energy model to do

For each country leg of a trip (a sub-segment within a single country), the model
must compute:

- `energy_kwh` — total energy consumed on this leg
- `energy_kwh_per_km` — average energy intensity

These values feed into `calc.py` which multiplies them by the country-specific
electricity price to compute the traction energy cost.

---

## Model definition

### Inputs

The following variables are available per country leg and should be explored
as potential predictors:

| Variable | Description | Unit | Source in backend |
|---|---|---|---|
| `total_weight_t` | Total gross weight of the train (locomotive + all coaches) | t | `Composition.total_weight_t` |
| `distance_km` | Distance of this country leg | km | `CountryLeg.distance_m / 1000` |
| `avg_speed_kmh` | Average speed on this leg | km/h | `CountryLeg.avg_speed_kmh` |
| `terrain_score` | Country-level terrain difficulty index (1.0 = flat, higher = more mountainous) | dimensionless | `TrackInfrastructure.terrain_score` |

### Output

| Variable | Description | Unit |
|---|---|---|
| `energy_kwh` | Energy consumed on this country leg | kWh |
| `energy_kwh_per_km` | Energy intensity | kWh/km |

### What the team needs to produce

1. A formula that predicts `energy_kwh` from the inputs above
2. The numerical coefficients for that formula, calibrated against real data
3. A validation showing how well the model fits

The formula structure is for the team to determine through data exploration.
If a different set of variables or a non-linear transformation fits better,
use that instead. Document the decision in the log below.

### Background reading on regression modelling

New to regression? These are good starting points:

- **Conceptual intro:** [Multiple Linear Regression — DigitalOcean](https://www.digitalocean.com/community/tutorials/multiple-linear-regression-python)
  — practical walkthrough with scikit-learn, good for beginners
- **scikit-learn docs:** [LinearRegression — scikit-learn](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.LinearRegression.html)
  — official reference, concise and accurate
- **Deeper guide:** [Multiple Linear Regression — mbrenndoerfer.com](https://mbrenndoerfer.com/writing/multiple-linear-regression-complete-guide-math-formulas-python-scikit-learn-implementation)
  — covers feature selection, validation, and interpretation

Once you have calibrated coefficients, enter them into `seed.py` under the relevant
composition type fields (`composition_type_energy_factor_weight` etc.) and update
`calc_energy_consumption.py` with the derived formula.

---

## How to find and calibrate the model

The task is open-ended: collect real train energy data, explore which variables
predict consumption, derive the formula structure, and calibrate the coefficients.

The suggested data source is Deutsche Bahn's Trassenfinder API — it returns energy
consumption estimates for train paths across the German rail network.
No authentication required, but a token-bucket rate limiter applies.

### Suggested approach

### Step 1 — Explore the Trassenfinder API

- [ ] Read the Trassenfinder OpenAPI documentation at https://trassenfinder.de
- [ ] Make a few manual test requests in a Jupyter notebook to understand the response structure
- [ ] Document which response fields correspond to distance, time, weight, and energy consumption

### Step 2 — Collect training data

- [ ] Write a notebook that queries multiple routes and collects for each:
  - Origin / destination station (UIC codes)
  - Train weight (use our composition data)
  - Distance (km)
  - Scheduled travel time (minutes)
  - Energy consumption from Trassenfinder response (kWh)
  - Country / terrain category
- [ ] Save results as a CSV (e.g. `backend/models/energy/notebooks/data/trassenfinder_samples.csv`)
- [ ] Aim for at least 50–100 samples across different countries and terrain types
- [ ] Include at least 10 mountainous routes (Switzerland, Austria) and 10 flat routes (Germany, France)

### Step 3 — Explore and fit the model

In a Jupyter notebook:

- [ ] Load the collected data in a notebook and explore relationships
      (scatter plots: energy vs weight, energy vs speed, energy vs terrain)
- [ ] Determine which variables are most predictive
- [ ] Choose a formula structure — the hypothesis above is a starting point,
      but adapt it if the data suggests something different
- [ ] Fit a regression (sklearn `LinearRegression` or `statsmodels.OLS`)
- [ ] Evaluate fit: R², residual plots, check for outliers
- [ ] Document the resulting formula, coefficients, and confidence intervals
- [ ] If you change the formula structure, update this README and the decisions log

### Step 4 — Validate

- [ ] Apply the calibrated coefficients to a held-out test set (20% of samples)
- [ ] Compare predicted vs actual energy — plot and compute RMSE
- [ ] Check whether the model generalises across terrain types
- [ ] Document known limitations (e.g. no regenerative braking, no elevation data)

### Step 5 — Update the backend

- [ ] Enter the calibrated coefficients into `seed.py` for the relevant composition types
- [ ] Replace the dummy implementation in `calc_energy_consumption.py` with the regression formula
- [ ] Bump `ENERGY_CALC_VERSION` in `version.py` and add a changelog entry
- [ ] Run `uv run --extra dev pytest tests/ -v` to confirm all tests still pass
- [ ] Open a PR to `backend-dev` — tag David for review

---

## Development environment setup

You do not need the full backend Docker stack to work on the energy model.
A simple Python environment with Jupyter is sufficient.

### Prerequisites

- Python 3.12
- [uv](https://docs.astral.sh/uv/) — package manager
- Git

### Setup

```bash
# Clone the repository
git clone https://github.com/Back-on-Track-eu/night-train-target-network.git
cd night-train-target-network/backend

# Install dependencies including dev group (includes jupyter)
uv sync --extra dev

# Start JupyterLab
uv run jupyter lab
```

JupyterLab opens in your browser. Navigate to `backend/models/energy/notebooks/` to find
existing notebooks, or create new ones there.

### Running scripts

```bash
cd backend
uv run python scripts/trassenfinder_collector.py
uv run python scripts/calibrate_energy.py
```

---

## Files in this folder

| File | Description |
|---|---|
| `calc_energy_consumption.py` | Main function called by `route_factory.py` — currently dummy, to be replaced |
| `version.py` | Version constant — bump when implementation changes |

## Related files

| File | Description |
|---|---|
| `backend/models/energy/notebooks/` | Jupyter notebooks for data collection, exploration, and calibration |
| `backend/models/params.py` | `CompositionType` — energy factor fields |
| `backend/models/route/trip.py` | `CountryLeg` — `distance_m`, `driving_time_min`, `energy_kwh` |

---

## Questions and coordination

Join the Signal group for questions, updates, and coordination:

👉 https://signal.group/#CjQKID4SnWmddEW6VXyJ7zbqngLWtuDu2Caey_yw6tOUEEw2EhC4scdb6HtEFZt_Of-pIu5_

---

## Decisions log

| Date | Decision | Rationale |
|---|---|---|
| 2026-06 | Use regression model over physics simulation | Simpler to calibrate, sufficient accuracy for cost modelling purposes |
| 2026-06 | Use Trassenfinder as calibration data source | No authentication required, covers European routes, free to use |
| 2026-06 | Terrain score as proxy for gradient | Elevation data not available in current routing engine; revisit when SRTM elevation integrated |
| 2026-06 | Store coefficients per composition type in DB | Different train types have different energy profiles; allows future per-type calibration |