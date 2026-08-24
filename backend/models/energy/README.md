# Night Train — Energy Model

This folder contains the energy consumption model for night train routes.

**Related documentation:** model layer overview — [`../README.md`](../README.md)
· evaluation model (consumes `energy_kwh`) —
[`../evaluation/README.md`](../evaluation/README.md) · onboarding guide for the
energy team — [`ONBOARDING.md`](ONBOARDING.md)

**Current status:** Dummy implementation using a flat 28.0 kWh/km factor.
Training data collection from Trassenfinder is complete for Germany — 1,184
samples across 148 routes and 8 compositions. The candidate regression in
`calib/02_energy_calibration.ipynb` predates that collection and has not been
refitted, so nothing is wired into the backend yet. See
[`calib/README.md`](calib/README.md).

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
- [ ] Save results as a CSV (e.g. `backend/models/energy/calib/data/samples_ontd.csv`)
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

JupyterLab opens in your browser. Navigate to `backend/models/energy/calib/` to find
the calibration notebooks.

### Running scripts

```bash
cd backend
uv run python scripts/trassenfinder_collector.py
uv run python scripts/calibrate_energy.py
```

---

## Data collection

`calib/01_source_extraction.ipynb` builds the training dataset. It runs
top to bottom with no manual steps — restart the kernel and run all cells.
Roughly 1,500 collection requests plus ~230 for the pre-flight, 30–50 minutes.

### Two route sources

| Source | Routes queried | Collected | What it is |
|---|---|---|---|
| `ontd` | 95 | 95 | Real German night-train segments from the ONTD workbook — station to station, as operated |
| `synthetic` | 100 | 53 | Generated station pairs, sampled for geographic and length diversity |

The generated set loses 47 routes: 7 to invalid DS100 codes and 40 to genuine
routing failures on branch lines a `D4` locomotive-hauled train cannot reach.
The two samples nonetheless agree within 1% on fleet-weighted kWh/km per
composition, so they pool — see [`calib/README.md`](calib/README.md).

The two cover different parts of the design space. ONTD segments are mostly
short (median 78 km air distance) because night trains stop often; the
generated set is mostly long (median 355 km) and spreads across N-S, E-W and
diagonal axes. Running both tests whether coefficients fitted on operational
segments hold on arbitrary station pairs. If they diverge, the fit is picking
up something about how night trains are routed rather than about moving a
train, and the sources should not be pooled.

The generated set is a robustness check, not evidence about real night-train
routing — its pairs were sampled for diversity, not drawn from timetables.

### Stages

| Stage | What it does |
|---|---|
| Setup | Loads compositions and both sources, normalises to a common schema, applies `DS100_CORRECTIONS`, drops routes without a DS100 |
| Payload | Builds the `spfv_lok` request template, held constant across both sources |
| Query function | One request per route × composition, with error bodies preserved |
| Pre-flight | Resolves each station's `mutter` flag once across both sources, and drops routes whose DS100 is not a Betriebsstelle |
| Collection | Each source queried independently against all 8 compositions |
| Save | Per-source CSVs plus a combined file carrying a `source` column |
| Compare | Coverage and kWh/km by distance band, per source |
| Quality check | Completeness verified from disk |

**`mutter` is a property of the station, not a request option.** Trassenfinder
rejects a Mutterbetriebsstelle sent as a child and a child sent as a mother,
both with HTTP 400 and no indication which end is wrong. The pre-flight
resolves this once per station rather than per request.

### Data files

Committed inputs live in `calib/sources/`; everything the notebooks write lives
in `calib/data/` and `calib/seed/`, both gitignored.

| File | Contents |
|---|---|
| `calib/sources/routes_ontd.csv` | German night-train segments from the ONTD workbook |
| `calib/sources/routes_synthetic.csv` | The generated station pairs |
| `calib/sources/compositions.csv` | The 8 standard compositions, with Trassenfinder locomotive numbers |
| `calib/data/samples_ontd.csv` | ONTD training set — one row per segment × composition |
| `calib/data/samples_synthetic.csv` | Generated-pair results |
| `calib/data/samples_all.csv` | Both, with a `source` column |
| `calib/data/failures_*.csv` | Requests that could not be completed, with the API message |
| `calib/seed/energy_coefficients.csv` | What the database reads |

`samples_*.csv` cannot be rebuilt at seed time — they are ~1,560 Trassenfinder
calls — so they travel through Drive and `calib/data_sources.py` fetches them on
first use. Set `ENERGY_DRIVE_FOLDER_ID` in `backend/docker/.env`. See
[`calib/README.md`](calib/README.md).

### Known data-quality issues in the ONTD extract

Report upstream rather than patching in the notebook:

- Lörrach Autoreisezug Terminal has no `start_ds100` — the segment is dropped
- Köln Süd is exported as `KKSU`, which is not a valid Betriebsstelle; corrected
  to `KKS` via `DS100_CORRECTIONS`
- Düsseldorf Hbf → Köln Süd has no `travel_duration_min`

## Files in this folder

| File | Description |
|---|---|
| `calc_energy_consumption.py` | Main function called by `route_factory.py` — currently dummy, to be replaced |
| `model.py` | Version constant, description, changelog, formula registry |
| `calib/` | Collection and calibration — notebooks, sources, generated data and seed |

## Related files

| File | Description |
|---|---|
| `backend/models/energy/calib/` | Collection and calibration notebooks — see its own README |
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
| 2026-08 | Resolve each station's `mutter` flag in a pre-flight pass | The flag is a property of the Betriebsstelle, not a request option. Hard-coding `mutter: True` lost 40 of 96 segments to HTTP 400, biased towards short segments. Resolving once per station costs ~60 requests and removes all retries from the main loop |
| 2026-08 | Correct DS100 codes in the notebook, not the source CSV | Keeps the correction visible next to the code that needs it and leaves the ONTD extract as delivered, so upstream fixes can be dropped in without a merge conflict |
| 2026-08 | Query notebook restructured as a linear run-all pipeline | The exploratory version defined the query function twice and ran the collection loop twice, so a top-to-bottom run silently used the wrong definition |
| 2026-08 | Move notebooks and data into `calib/`, matching the other model packages | `energy/` was the only domain with `notebooks/` and an ad-hoc `data/{raw,processed,finished}` split. Personal filenames (`Regression_model_LS`, `Energy_model_Helena`) stop being findable once their authors move on; numbered stage names do not |
| 2026-08 | Trassenfinder samples travel through Drive, not git | `01` is ~1,560 API calls over 30–50 minutes, so unlike every other calib package `seed.py` cannot regenerate them. `data_sources.ensure_local()` fetches them on first use, mirroring the ONTD seed pattern. Route lists stay committed under `calib/sources/` because they are curated input, not bulk output |
| 2026-08 | Collect a second, generated route sample alongside ONTD | ONTD segments are short by construction (real night trains stop often), leaving the long-distance range thin. Generated pairs extend it and act as an out-of-sample check on whether the fit describes moving a train or how night trains happen to be routed. Kept in separate files with a `source` column so pooling stays a deliberate choice |
| 2026-06 | Store coefficients per composition type in DB | Different train types have different energy profiles; allows future per-type calibration |