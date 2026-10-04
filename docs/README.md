# `docs/` — what lives here

The documentation of this project sits next to what it describes: every
package has its README, the public model documentation is `docs-site/`,
and the API contract is `backend/api/README.md` with its TypeScript mirror
`frontend/src/types/api.ts`. This folder holds only what belongs to no
single package:

| File                                | What it is                                                                                                                                                                                                                                                                                                                              | Maintained                            |
| ----------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------- |
| `MODEL.md`                          | The whole calculation model in one file — formulas, parameters, standard values, emission factors — **generated** from the model's own registries by `backend/scripts/generate_model_docs.py` (hand-written prose between the generated blocks). CI fails when it is out of date.                                                       | regenerate after a model change       |
| `DEPLOY_HANDOVER.md`                | Living handover to the server side: deploy order per batch, standing gotchas (§5), capacity. Newest entries at the end.                                                                                                                                                                                                                 | in the same PR as the change          |
| `PARKED_WORK.md`                    | Designs that are agreed and worked out but not built, kept out of the live READMEs so those describe only what exists.                                                                                                                                                                                                                  | when something is parked or picked up |
| `ROUTE_CACHE_LAPTOP_RUNBOOK.md`     | Operator procedure: route-cache precompute overnight on a laptop, upload by pgAdmin.                                                                                                                                                                                                                                                    | when the procedure changes            |
| `2026-09-18_manual_demand_guide.md` | The decision record (D1–D31) and reference values behind DEMAND 0.1.0, which ~25 code comments cite by number. `backend/models/demand/README.md` is the current description; this file stays until the decisions are folded in there together with the next `DEMAND_MODEL_VERSION` bump (moving it means touching version-gated files). | frozen                                |
| `bot-logo.png`                      | The logo the root README and the gate page use.                                                                                                                                                                                                                                                                                         | —                                     |

## What does not go here

- **Per-delivery manifests.** The note that accompanies a batch — what
  changed, how it was verified, rollout steps — goes into the pull request
  description. Its durable facts go where they are read: a contract into
  the package README, a deploy step into `DEPLOY_HANDOVER.md`, a decision
  with its reason into a comment at the place it governs.
- **Sketches and design mock-ups.** They are the spec while a feature is
  being built and obsolete the day it ships; git history keeps them.
- **Plans.** Same rule: once built, the decisions move into the README of
  the package that implements them (the WP18 family plan became
  `backend/models/family/README.md`, "Design decisions").
- **Letters to a single contributor.** Those stay with their data
  (`backend/models/infrastructure/stops/charges/HANDOVER.md`) and disappear
  when the task is done.

Seventy such files were removed on 2026-10-04 after checking, file by
file, that what they recorded is in the READMEs, the handover or the code
comments; the few facts that were not were carried over in the same change.
