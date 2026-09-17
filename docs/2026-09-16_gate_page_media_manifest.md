# Gate page — launch press text and media gallery (2026-09-16)

The public `/gate` countdown page now carries the launch press release and
one slideshow box: the 22-second walkthrough video, then eight builder
screenshots, advancing on its own.
Backend only: no schema change, no migration, no model version, no env
change, no Caddyfile change. Rebuild and deploy the api image — the media
is fetched from Drive at build (see "Where the media lives").

Two decisions taken with David on 2026-09-16:

- **The date.** The press text as delivered said "21 September"; InnoTrans
  2026 opens on the 22nd and `LAUNCH` is 22 September, 10:00 CEST. The page
  now derives every date it states from `gate_page.LAUNCH`, so the text
  reads "22 September" and nothing on the page can drift from the countdown.
- **The figures.** "About 150 connections today, 300 by 2032" replaces the
  earlier "100 lines in 2025, 300 by 2035" — the press release wins, and
  `test_76` pins the new wording.

## Files

### Backend

- `backend/api/gate_media/` — **gitignored, not in this zip.** Eight
  screenshots as `<stem>.jpg`, `walkthrough.mp4` (1080p H.264, no audio —
  the source track was silence, 899 KB), `walkthrough-poster.jpg`; 1.6 MB
  as `gate_media.zip` on Drive, id `1h6emMrrtPAqTvZkHK96DRDtybMVdOKxl`.
- `backend/scripts/fetch_gate_media.py` — **new.** Downloads that zip
  (`GATE_MEDIA_FILE_ID`, code default like `EEZ_LAND_UNION_FILE_ID`) and
  unpacks it flat into `api/gate_media/`, taking only the names
  `gate_page.media_files()` lists wherever they sit in the archive, never
  overwriting a local file (`--force` does). Stdlib only, so it runs on the
  image's python before the venv is on PATH; exit 1 on any failure, which
  the Dockerfile turns into a warning.
- `backend/docker/Dockerfile` — `RUN python scripts/fetch_gate_media.py ||
  echo WARNING…` after `COPY . .`. Build time because the server compose
  files skip the entrypoint, and because no request should depend on Drive.
- `backend/.dockerignore` — `!scripts/fetch_gate_media.py` (scripts/ is
  otherwise excluded from the image).
- `.gitignore` — `backend/api/gate_media/`.
- `backend/docker/.env.example` — commented `GATE_MEDIA_FILE_ID` in the
  Drive section, default documented as living in the script.
- `backend/DEVELOPMENT.md` — host-run API: fetch once with `uv run`. Stems: `landing`, `sketch`,
  `evaluating`, `evaluated`, `proposal`, `scenarios`, `infrastructure`,
  `composition`.
- `backend/api/gate_page.py` — rewritten. `LAUNCH` gains a tz name (`CEST`);
  `launch_day()` / `launch_when()` feed the `<title>`, meta description,
  hero and press text. `GALLERY` (tuple of `GalleryItem(stem, caption)`),
  `VIDEO`, `SLIDE_SECONDS`, `MEDIA_DIR`, `MEDIA_URL` and `media_files()` are
  the one place the page, the tests and the handovers refer to. Press text
  in three sections with two attributed quotes, the position-paper link
  under the first. One slideshow (`<section class="show">`, 3:2 stage,
  prev/next, dots, "n / 9"): the video first (`muted playsinline controls`,
  poster, **no** `autoplay` attribute — the script starts it when its slide
  is up and moves on at `ended`), then the screenshots, each held
  `SLIDE_SECONDS` (6). Any tap on the controls stops the timer; a
  reduced-motion preference means nothing moves by itself. Without
  JavaScript the slides are laid out one after the other with their
  captions. `page_html()` takes a `media_dir` and renders a slide only when
  its file is there — no files, no section — so a failed fetch degrades to
  the text. Code box, countdown and the swap-at-zero handler unchanged.
- `backend/api/gate.py` — `GET /gate/media/<path:filename>` via
  `send_from_directory(MEDIA_DIR, …, max_age=86400)`: `public, max-age`,
  Range requests honoured (206), anything outside the directory 404.
  Module docstring lists the endpoint and notes that `REQUEST_LOG_EXCLUDED_ENDPOINTS`
  covers it by blueprint prefix.
- `.gitattributes` — `*.mp4 binary`.

### Tests

- `backend/tests/test_76_gate_page.py` (stdlib + pytest fixtures, 23
  tests) — dates derived from `LAUNCH` and no other September day typed;
  press-text figures and the two attributions; with a full `tmp_path`
  media dir: one slideshow, video first, every screenshot once, video muted
  with poster and without `autoplay`, no "22 seconds", nothing from another
  origin; with an empty dir: no section at all; with one file removed: that
  slide skipped; the position-paper link under the first section; the fetch
  script's `unpack()` flattens a prefixed zip, ignores strays and never
  overwrites unless forced. The on-disk check ("exactly the listed files,
  nothing else") skips on a checkout without the media. The slideshow
  script was exercised in jsdom (dots, prev/next wrap, advance on `ended`,
  advance after the hold).
- `backend/tests/test_75_gate_api.py` (+4, live API) — every file
  `media_files()` lists answers 200; media carries `max-age` while the page
  stays `no-store`; the video answers `Range: bytes=0-1023` with 206 (these
  three skip when the stack's page has no slideshow, i.e. the image was
  built without Drive access); `gate.py`, `%2e%2e/gate.py`, `..%2fgate.py`,
  `missing.jpg` are 404.

### Docs

- `backend/api/README.md` — new "Testing gate" section (four endpoints, how
  the page is assembled, how to swap a screenshot) + TOC entry.
- `backend/tests/README.md` — rows for `test_75_gate_api` and `test_76_gate_page`.
- `docs/DEPLOY_HANDOVER.md` — §20 and the "Last update" line: image rebuild
  only, two verification curls, why `/gate/media/*` reaches the api through
  `@open` ahead of `@assets`.
- `docs/FRONTEND_HANDOVER.md` — §23: the page shows Bjarne's UI; how to
  replace a stale screenshot; captions quote no figures on purpose.

## Where the media lives

One `gate_media.zip` on Drive (link-shared). The image build fetches it;
a developer fetches it once:

```powershell
cd backend
uv run python scripts\fetch_gate_media.py
```

Until then `/gate` renders without the slideshow, and `test_76`'s on-disk
check skips. To publish new media: rebuild the zip from the folder (the
prefix inside the archive does not matter — `unpack()` flattens), upload it
as a **new version of the same Drive file** (Manage versions) so the id
survives, then rebuild the api image (`--no-cache` if nothing else in
`backend/` changed).

## Regenerating the media

From the originals (`Media data/`), with ffmpeg and Pillow:

```bash
ffmpeg -i 260916_pp_builder_8.mp4 -vf "scale=1920:-2,crop=1920:896:0:92" \
  -c:v libx264 -preset slow -crf 23 -pix_fmt yuv420p -an -movflags +faststart walkthrough.mp4
ffmpeg -i walkthrough.mp4 -ss 10 -frames:v 1 -q:v 4 walkthrough-poster.jpg   # then resize to 1280 px
# screenshots: re-save at JPEG q84 progressive, metadata stripped
```

The crop removes the recording's letterbox (`cropdetect`); the audio track
was −91 dB throughout, so `-an` loses nothing.

## Rollout

1. Extract at repo root, `git status --short` should list only the files above
   (`api/gate_media/` must NOT appear — it is ignored).
2. `cd backend && uv run python scripts/fetch_gate_media.py` — this is also
   the end-to-end check of the Drive upload; expect ten `+` lines.
3. `uv run ruff format --check . && uv run ruff check .`
4. `uv run pytest tests/test_76_gate_page.py` — no stack needed, 23 pass.
5. Stack up, rebuilt (`docker compose ... up -d --build api`; watch the build
   log for the fetch), then `uv run pytest tests/test_75_gate_api.py`.
6. Look at `http://localhost:5050/gate` once — the tests cannot judge layout.
7. Commit as `feat` (gate.py, gate_page.py, fetch_gate_media.py, Dockerfile,
   .dockerignore, .gitignore, .gitattributes, .env.example), `test`
   (test_75, test_76), `docs` (READMEs, DEVELOPMENT.md, handovers, this file).
8. CI: no version constant is gated by these paths; ruff and the integration
   job are the only checks that see this change. The CI image build fetches
   from Drive too — if that ever fails, the media tests skip rather than fail.
9. After the staging deploy, run the two curls in `DEPLOY_HANDOVER.md` §20.
