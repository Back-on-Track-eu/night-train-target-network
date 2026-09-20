# Gallery — duplicate loads on a cold start (2026-09-20)

Frontend only, one file. Two watchers added this round each fired a full
`POST /api/proposals` right after the gallery's own first load, and every
new request cancels the one in flight ("newest wins"), so a cold start paid
for two or three sequential loads before anything rendered.

| Cause                                                                                                                                            | Fix                                                                                                                             |
| ------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------- |
| Phase C: `galleryScenarioId` resolves `null → base` when `GET /api/scenarios` returns, and was watched                                           | The reload watcher now watches the derived `scenarioVariantId` — `null` before and on the base, so that resolution is no change |
| Phase 2: `App.vue`'s `restoreAuth()` runs after the gallery mounts, so `store.userId` goes `null → id` on boot and the identity watcher reloaded | The watcher reloads only on a change from one identity to another (the guest merge); `null → id` and `id → null` are ignored    |
| A `?scenario=` link could not be resolved before the first load                                                                                  | `onMounted` awaits `fetchScenarios()` when the link carries one, like it already does for stops                                 |

## Files touched

- `frontend/src/components/Gallery.vue` — the three changes above.

## Gates

prettier, eslint, vue-tsc, 332 vitest cases, `vite build` — green.

## Your run

`cd frontend && npm run ci && npm run build`, then a hard reload of
`/gallery` with the network tab open: exactly one `POST /api/proposals`
(the second one that appears a moment later is page 2 from the sentinel,
`offset: 20`, and is expected).

If a single request is still slow, `admin.request_log` says which part:

```sql
SELECT occurred_at, duration_ms, response_bytes
FROM admin.request_log
WHERE endpoint = 'proposals.list_proposals'
ORDER BY request_id DESC LIMIT 10;
```

Above ~500 ms per request the suspect is `map_lines` (the corridor
aggregation over the whole filtered set, ONTD corridors included); a
request with `include: ["summaries"]` only, compared against the full one,
puts a number on it.
