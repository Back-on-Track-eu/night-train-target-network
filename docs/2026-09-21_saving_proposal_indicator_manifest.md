# "Saving proposal…" on the ownership pill — manifest and handover

Date: 2026-09-21 · Scope: **frontend only.** No backend change, no version
bump. One new i18n key.

## What changed

The ownership pill beside the Gallery link now shows the save itself. While
a publish is out — the automatic save after a calculation, an explicit
save, a Recalculate, the silent composition save — the dot gives way to a
spinner and the pill reads **Saving proposal…**; when the response lands it
settles into *Your proposal · changes are saved automatically* (or the copy
state). For a brand-new proposal this is the first time the pill appears at
all: before, nothing was on screen between the result and the saved state.

## Updates by file

| File | Change |
|---|---|
| `frontend/src/components/OwnershipLine.vue` | Optional `saving` prop; a spinner + label branch (`role="status"`) ahead of the two ownership states; header comment says why the pill may show before a stored proposal exists. |
| `frontend/src/components/ProposalViewport.vue` | The pill renders while `publishPhase !== 'idle'` as well, and passes it as `saving`. Contains today's earlier viewport changes — extract after those zips. |
| `frontend/src/i18n/locales/en.json`, `de.json` | `proposal.ownership.saving`. 897 keys each, in parity. |

## Deployment handover

Frontend image only. No environment variable, no migration, no cache flush.

## Verification (Node 22)

`vue-tsc --noEmit` clean · `eslint .` clean · `prettier --check` clean ·
`vitest run` **376 passed** · `vite build` OK.

## Commit split

- `feat(builder): show "Saving proposal…" on the ownership pill while a save is out` — all files.
- `docs: saving indicator manifest` — this file.
