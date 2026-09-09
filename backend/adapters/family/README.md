# adapters/family — persistence for the proposal family

Everything in the `family` schema is derived from the pins and can be
rebuilt: it is cache, never state. `scripts/refresh_proposals.py` flushes
it on every version bump; a fresh database starts with it empty.

| module | table | holds |
|---|---|---|
| `document_cache.py` | `family.documents` | one serialised §2.5 document per family key (`models/family/key.py`), TTL-bounded |
| *(B2b)* `member_cache.py` | `family.members` | today `proposals.compute_cache_pointer` / `_result` (`adapters/proposal/compute_cache.py`) — one member payload per resolved request, the member cache behind `compute_proposal()` and the views endpoint |

Both follow the same discipline as the existing compute cache: UNLOGGED
tables, TTL enforced on **read** (an expired-but-unswept row is a miss,
never a stale hit), upserts that refresh `created_at`, a sampled sweep on
the write path rather than a scheduler, and `flush()` as a plain
`TRUNCATE`. One TTL for both (`COMPUTE_CACHE_TTL_HOURS`), so a document
never outlives the members it was assembled from.

## Why documents and members are two caches

A family build never writes its 72 members into the member cache: the
client reads the summary of every member from the document and the full
views of one or two. Writing 72 × ~700 KB of views nobody asked for
would cost more than the family itself. So the document cache holds what
every client needs (summaries, compact routes, geometry once), and the
member cache fills lazily with the members whose views someone opened —
served from there on the next open, and shared with publish, refresh and
compare, which all go through `compute_proposal()`.

## Versions

`family_key()` folds `ROUTE_BUILDER_VERSION`, `CALC_VERSION` and
`family_serialize.FAMILY_DOCUMENT_FORMAT` into the key, so neither a
changed number nor a changed document shape can ever be served from an
old row — the key simply stops matching and the sweep drops them. The two
version columns on the row are informational, for a targeted manual
sweep. The member cache guards versions on read instead
(`compute_proposal()` compares the stored payload's versions to the
running ones) — same outcome, different mechanism, because its key is
the request alone.
