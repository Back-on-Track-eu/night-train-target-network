# Frontend handover — language bar (2026-09-13)

Scope: header utility bar only. No backend, schema, model or deployment change —
nothing to migrate, reseed or bump; a normal frontend build ships it.

## What changed

The bar now reads **English · Deutsch · Français · Nederlands · Italiano ·
Español · Polski**. English is the only live locale: it is white, underlined
while active, turns BoT green on hover and switches the app language on click.
Every other language is rendered at 45 % white with a default cursor and
announces itself as "Coming soon" in a small bubble below the bar on hover or
keyboard focus (screen readers get the same wording appended to the label).

Order and availability are data, not markup: `frontend/src/lib/uiLanguages.ts`
holds the list, and both the bar and the store's `restoreLocale()` read it. A
persisted language is therefore only restored while its locale file exists —
before, that was a hard-coded `stored === 'en'` guard.

## Enabling a language later (German is next)

1. Add `frontend/src/i18n/locales/de.json` — full key parity with `en.json`.
2. Register it in `frontend/src/i18n/index.ts` (`messages: { en, de }`).
3. Add `'de'` to `Locale` / `SUPPORTED` in `frontend/src/lib/localeStorage.ts`
   (already present for German; needed for any further language).
4. Flip `available: true` for that entry in `frontend/src/lib/uiLanguages.ts`
   and update `uiLanguages.test.ts`, which asserts the live set.

No component edit is needed — the bar renders whatever the list says. The
"coming soon" string lives at `header.comingSoon` in `en.json`.

## Checks run

`npm run lint`, `npm run format:check`, `npm run type-check`, `npx vitest run`
(22 files, 285 tests) — all green, including the four new `uiLanguages` cases.
