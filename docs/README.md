# docs/

Cross-cutting documents. Anything describing **one part** of the system lives
in a README next to that part's code instead — `backend/api/README.md`,
`backend/adapters/proposal/README.md`, `backend/models/route/routing/README.md`,
`backend/models/infrastructure/stops/README.md`, and so on. That way a
document is edited by whoever edits the code it describes, and a folder that
disappears takes its documentation with it.

| Document | What it is | Audience |
|---|---|---|
| [`MODEL.md`](MODEL.md) | Every model, formula, parameter and source. **Generated** from the code's own registries by `backend/scripts/generate_model_docs.py` — never edit the marked blocks by hand. | Anyone asking what the tool computes |
| [`STAGING_DEPLOY_NOTES.md`](STAGING_DEPLOY_NOTES.md) | Non-obvious steps when redeploying staging, starting with wiping the routing graph cache. | Whoever redeploys |
| [`FRONTEND_API_HANDOVER_2026-08-07.md`](FRONTEND_API_HANDOVER_2026-08-07.md) | The API *diff* from the proposals refactor, endpoint by endpoint, with build status per item. The *spec* is `backend/api/README.md`. | Frontend |
| [`PARKED_WORK.md`](PARKED_WORK.md) | Designs that are agreed and worked out but not implemented, kept out of the live READMEs so those describe only what exists. | Anyone picking up new work |

`PROPOSALS_DESIGN.md` was removed on 2026-08-29. It was the pre-implementation
design (2026-08-01) and had been folded into
[`backend/adapters/proposal/README.md`](../backend/adapters/proposal/README.md)
on 2026-08-07, which has since been the live document — the copy in `docs/`
had been describing a shape the code no longer had. Recoverable from git
history if a piece of the original rationale is ever wanted.
