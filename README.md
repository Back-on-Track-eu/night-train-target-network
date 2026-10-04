<p align="center">
  <a href="https://back-on-track.eu"><img src="docs/bot-logo.png" alt="Back-on-Track" width="130"/></a>
</p>

# Night Train Target Network

An open-source initiative by [Back-on-Track.eu](https://back-on-track.eu) to
design and evaluate a European night train target network that could
realistically be implemented by 2032 — and the tool the community designs it
with.

**▶ Use the tool: [targetnetwork.back-on-track.eu](https://targetnetwork.back-on-track.eu)**
— draw a night train on the real rail network, pick a train concept, and see
what it would cost, earn and save. No account needed.

**▶ How the numbers come about: [targetnetwork.back-on-track.eu/docs](https://targetnetwork.back-on-track.eu/docs/)**
— every formula, every parameter, where the data comes from and what is
still assumed, plus the [product updates and the launch report](https://targetnetwork.back-on-track.eu/docs/updates/2026-09).

## Vision

Back-on-Track wants to put a serious, evidence-based night train network
proposal in front of the European Commission (DG MOVE) and other key
political stakeholders. The study needs to answer three core questions:

- **Which routes should be part of the network — in addition to the ones
  that exist today?** Based on future demand potential, including passengers
  likely to shift from air travel.
- **How much public subsidy is needed** — per route and for the network as a
  whole — to create the framework conditions under which operators can run
  economically sustainable services? And how do politically determined
  conditions constrain the offer?
- **Which night train concepts work best** on which routes or parts of the
  network? And how could new concepts boost demand?

To build broad acceptance for the results from the start, we draw on
Back-on-Track's community of members, lobbyists, experts and politicians to
crowdsource route and train concept ideas, evaluate them transparently, and
use the strongest proposals as the foundation for the target network.

## How we get to the study results

1. **Prepare the model** — the data and the cost/revenue model used to
   evaluate the economic feasibility of individual routes and the full
   network. _Done for a first generation; it keeps being refined with the
   community's feedback._
2. **Crowdsource ideas — current phase.** The tool opened to the public on
   22 September 2026: community members design routes (timetables,
   geography), pick a train composition, and see cost, revenue and demand
   results against other members' submissions.
3. **Select the best proposals** — the most economically sound suggestions
   form the basis of the target network, with further adjustments, additions
   or optimisation.
4. **Evaluate the network** — answer the three core questions above and
   publish the results (study paper, interactive map, etc.).
5. **Close the loop** — share results back with the community and the wider
   public, crediting contributions.

Each submitted route is scored on: potential shift from air travel (flights,
seats, seat-km), CO₂e reduction, subsidy needed per shifted seat-km, and
subsidy needed per tonne of CO₂e avoided.

## This repository

The technical side of the project — one monorepo, deployed as two images:

| Part                 | Where                      | What                                                                                                                                                                                                                                |
| -------------------- | -------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Backend API          | [`backend/`](backend/)     | Python 3.12 / Flask: route building on a self-hosted [OpenRailRouting](https://github.com/geofabrik/OpenRailRouting) graph, timetable, demand, cost/revenue/emissions evaluation, proposals, gallery, feedback. PostgreSQL/PostGIS. |
| Frontend             | [`frontend/`](frontend/)   | Vue 3 / TypeScript / PrimeVue / MapLibre: the proposal builder and the gallery.                                                                                                                                                     |
| Public documentation | [`docs-site/`](docs-site/) | VitePress site served at `/docs/` on the same origin — the model documentation (cost pages generated from the model's own formula registry), data sources, product updates, reports.                                                |
| Deployment           | [`deploy/`](deploy/)       | Docker Compose stacks: [`deploy/coolify/`](deploy/coolify/) is what the project's server builds (Coolify, since September 2026); `deploy/bot-server-app/` is the earlier lane, kept as the manual fallback.                         |

Data lives in a PostgreSQL/PostGIS database on Back-on-Track's server; the
calibration inputs (stop catalogue, charges, routing graph) are hosted on
the working group's Drive and fetched at build or seed time — large data is
never committed here.

## Environments

|                                    | URL                                                                      | Deployed from                          |
| ---------------------------------- | ------------------------------------------------------------------------ | -------------------------------------- |
| **Production**                     | [targetnetwork.back-on-track.eu](https://targetnetwork.back-on-track.eu) | every merge to the `production` branch |
| **Staging** (internal, basic-auth) | `staging.targetnetwork.back-on-track.eu`                                 | every merge to the `staging` branch    |

Both serve the documentation site at `/docs/`; it ships inside the frontend
image. There is no `main` branch: all work lands in `staging` via pull
request, and `staging` is merged into `production` once tested. Merges
deploy automatically through Coolify — [`deploy/coolify/README.md`](deploy/coolify/README.md)
describes the apps, the one-time setup and the environment variables;
[`deploy/bot-server-app/README.md`](deploy/bot-server-app/README.md) has a
one-command local rehearsal of the production stack (`./local.sh`).

## Running the app locally

The easiest way to get the frontend (and the backend API it talks to) running
on your machine — no Python setup required.

**Prerequisites**

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) — installed and running
- [Git](https://git-scm.com/downloads)

**1. Clone the repository**

```bash
git clone https://github.com/Back-on-Track-eu/night-train-target-network.git
cd night-train-target-network
```

**2. Create your `.env` file**

One shared `.env` configures the whole backend — the main stack, the
devcontainer, the standalone database stack, and all host-run scripts and
tests. The defaults work out of the box, and every port lives there too:

```bash
cp backend/docker/.env.example backend/docker/.env
```

**3. Start everything**

```bash
docker compose -f backend/docker/docker-compose.yml -f .devcontainer/docker-compose.yml up --build
```

(`.devcontainer/docker-compose.yml` is an overlay on the backend stack —
listing both files is required.)

This builds and starts the Postgres/PostGIS database, the OpenRailRouting
engine, the Flask backend API, the Vue frontend and the documentation site's
dev server. The first run takes a few minutes (routing graph + image builds);
subsequent runs are fast.

**4. Open the app**

- Frontend: [http://localhost:5173](http://localhost:5173) (`FRONTEND_HOST_PORT`)
- Documentation: [http://localhost:5173/docs/](http://localhost:5173/docs/)
- Backend API health check: [http://localhost:5050/api/health](http://localhost:5050/api/health) (`API_HOST_PORT`)

**Stopping it**

```bash
docker compose -f backend/docker/docker-compose.yml -f .devcontainer/docker-compose.yml down
```

Add `-v` to also wipe the database volume for a clean slate.

Working on the frontend day-to-day (VS Code, hot reload, troubleshooting)? See
[`.devcontainer/DEVELOPMENT.md`](.devcontainer/DEVELOPMENT.md). Working on the
backend instead? See [`backend/DEVELOPMENT.md`](backend/DEVELOPMENT.md).

## Documentation map

| Topic                                                                    | Document                                                                                                                                                                                       |
| ------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **The model, for readers** — formulas, parameters, sources, assumptions  | the documentation site: [live](https://targetnetwork.back-on-track.eu/docs/) · source in [`docs-site/`](docs-site/) · the same content as one generated file, [`docs/MODEL.md`](docs/MODEL.md) |
| Contributor conventions (code style, structure, CI, parameter placement) | [`AGENTS.md`](AGENTS.md)                                                                                                                                                                       |
| Backend developer setup (PyCharm, Docker, tests)                         | [`backend/DEVELOPMENT.md`](backend/DEVELOPMENT.md)                                                                                                                                             |
| Frontend developer setup (VS Code, Dev Container)                        | [`.devcontainer/DEVELOPMENT.md`](.devcontainer/DEVELOPMENT.md)                                                                                                                                 |
| API reference — every endpoint, request/response shapes                  | [`backend/api/README.md`](backend/api/README.md)                                                                                                                                               |
| Domain model layer — pipeline, objects, conventions                      | [`backend/models/README.md`](backend/models/README.md)                                                                                                                                         |
| Evaluation model — cost/revenue calculation, views, allocation           | [`backend/models/evaluation/README.md`](backend/models/evaluation/README.md)                                                                                                                   |
| Proposal family — one compute for every scenario × composition           | [`backend/models/family/README.md`](backend/models/family/README.md)                                                                                                                           |
| Proposals, gallery and compute cache                                     | [`backend/adapters/proposal/README.md`](backend/adapters/proposal/README.md)                                                                                                                   |
| Demand model                                                             | [`backend/models/demand/README.md`](backend/models/demand/README.md)                                                                                                                           |
| Energy model — status and calibration                                    | [`backend/models/energy/README.md`](backend/models/energy/README.md)                                                                                                                           |
| Composition catalogue and its cost calibration                           | [`backend/models/compositions/calib/catalog/README.md`](backend/models/compositions/calib/catalog/README.md) · [`CALIBRATION.md`](backend/models/compositions/calib/CALIBRATION.md)            |
| Stop catalogue — classification pipeline and station charges             | [`backend/models/infrastructure/stops/README.md`](backend/models/infrastructure/stops/README.md)                                                                                               |
| Routing infrastructure — OpenRailRouting setup, graphs, route cache      | [`backend/models/route/routing/README.md`](backend/models/route/routing/README.md) · [`docs/ROUTE_CACHE_LAPTOP_RUNBOOK.md`](docs/ROUTE_CACHE_LAPTOP_RUNBOOK.md)                                |
| Database layer — schemas, seeding, migrations, data tasks                | [`backend/db/README.md`](backend/db/README.md)                                                                                                                                                 |
| Test suite — layout and every test's purpose                             | [`backend/tests/README.md`](backend/tests/README.md)                                                                                                                                           |
| Frontend — stack, structure, conventions                                 | [`frontend/README.md`](frontend/README.md)                                                                                                                                                     |
| Documentation site — conventions, reports and product updates            | [`docs-site/reports/README.md`](docs-site/reports/README.md)                                                                                                                                   |
| Server environments, deploy pipelines, operational handover              | [`deploy/coolify/README.md`](deploy/coolify/README.md) · [`docs/DEPLOY_HANDOVER.md`](docs/DEPLOY_HANDOVER.md)                                                                                  |
| Designs agreed but not built                                             | [`docs/PARKED_WORK.md`](docs/PARKED_WORK.md)                                                                                                                                                   |

What belongs in [`docs/`](docs/) and what does not is in
[`docs/README.md`](docs/README.md).

## Data and attribution

- Track geometry, distances and countries crossed come from
  **OpenStreetMap** (© OpenStreetMap contributors, ODbL), routed on a
  self-hosted OpenRailRouting graph; the stop catalogue is derived from the
  same data.
- Existing night trains come from Back-on-Track's
  [Open Night Train Database](https://back-on-track.eu/night-train-database).
- Country outlines in the app and the reports are Natural Earth (public
  domain); map tiles are CARTO's Positron style on OpenStreetMap data.
- Every calibrated parameter names its source on the documentation site
  ([data sources](https://targetnetwork.back-on-track.eu/docs/sources/)).

## Contributing

Contributions of any kind — code, data, route ideas, documentation — are very
welcome! Route ideas go straight into [the tool](https://targetnetwork.back-on-track.eu);
corrections to a parameter or a formula through the feedback form on every
documentation page.

For code and data, please **send a short email before you start working on
something**, so we can avoid duplicate effort and keep contributions aligned
with the overall direction:

👨 **Current project lead: David Wedekind**

📧 **targetnetwork-wg@back-on-track.eu**

The basic workflow:

1. Always pull freshly from `staging` before starting any work (there is no `main`).
2. Do your work on your own branch.
3. Open a pull request targeting `staging` when ready — it is reviewed by the
   project lead. Merging into `staging` deploys to the staging environment
   automatically.
4. Keep branch lifetimes short: merge within **days, not months**.

## License

- **Code** (backend, frontend, deployment, the documentation site's
  components): **GNU General Public License v3.0 or later**
  (`GPL-3.0-or-later`) — see [`LICENSE`](LICENSE).
- **Content** — the model documentation, the reports and product updates on
  the documentation site, the charts and the generated `docs/MODEL.md`:
  [**Creative Commons Attribution 4.0**](https://creativecommons.org/licenses/by/4.0/)
  (CC BY 4.0). Quote, reproduce and build on it; credit "Back-on-Track —
  Night Train Target Network" and link to the source.
- **Not covered:** third-party data, which keeps its own terms (see above),
  and the Back-on-Track name and logo.

---

Questions before diving in? Reach out to the email above.
