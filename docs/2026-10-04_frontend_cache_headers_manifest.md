# Frontend cache headers — manifest (2026-10-04)

Fix for the "new release only after a reload" effect seen on staging right
after PR #74: the frontend's nginx sent no `Cache-Control`, browsers cached
`index.html` heuristically, and an address-bar visit reused a copy that
still named the previous bundle's hashed files. In-app navigation then
stayed inside the old bundle; only a page reload revalidated `index.html`.

No backend change, no version bump, no migration. Ships with the next
frontend image build.

## Files

- `frontend/nginx.conf` — server-level `add_header Cache-Control "no-cache"`
  (revalidate everything; nginx's ETag turns that into a 304), plus a regex
  location `^/(docs/)?assets/` with
  `public, max-age=31536000, immutable` for the content-hashed Vite and
  VitePress output. Comments explain why. CRLF kept.
- `frontend/README.md` — new "Production image" subsection under Dev Setup
  naming the two cache rules.
- `docs/DEPLOY_HANDOVER.md` — §24: symptom, cause, the two rules, how to
  verify on the edge host, when the section stops applying.
- `docs/2026-10-04_frontend_cache_headers_manifest.md` — this file.

## Verified

Config loaded in nginx 1.24 against a minimal tree with the app at `/`,
the docs at `/docs/` and hashed files under both `assets/` directories:

| path                      | status | Cache-Control                            |
| ------------------------- | ------ | ---------------------------------------- |
| `/`, `/gallery`, `/index.html` | 200 | `no-cache` (+ ETag)                   |
| `/assets/index-abc.js`    | 200    | `public, max-age=31536000, immutable`    |
| `/docs/`                  | 200    | `no-cache`                               |
| `/docs/assets/app-123.js` | 200    | `public, max-age=31536000, immutable`    |
| `/docs/nonsense`          | 404    | — (VitePress 404 page, as before)        |
| `/favicon.ico`            | 200    | `no-cache`                               |
| `/gallery` with `If-None-Match` | 304 | revalidation is free                 |

## After the deploy

```powershell
(Invoke-WebRequest -UseBasicParsing -Method Head -Uri "https://staging.targetnetwork.back-on-track.eu/gallery").Headers["Cache-Control"]
```

Expect `no-cache`. Then the hashed bundle named in the page must say
`public, max-age=31536000, immutable`.
