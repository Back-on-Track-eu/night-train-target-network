# Gallery — scenario panel and ownership switch on existing-only (2026-09-20)

Frontend only, no API change.

With the source switch on **Existing**, neither control applies — an ONTD
row has no owner and runs as it runs today — so both now grey out (opacity,
`disabled`, `aria-disabled`, a hover title saying why) instead of pretending.
They stay on screen: a control that vanished with the source would be a
control nobody could find again. The scenario panel also closes when it is
disabled, and its header carries a permanent "proposals only" chip.

## Files touched

- `frontend/src/components/GalleryScenarioPanel.vue` — `disabled` prop
  (greys, closes, blocks the toggle, hover hint); "proposals only" chip in
  the header.
- `frontend/src/components/Gallery.vue` — `existingOnly`; both ownership
  buttons disabled and greyed on it; `applyMine()` guards against a
  remembered intent landing after the source moved (the source-flip it used
  to do is unreachable now that the switch is disabled there).
- `frontend/src/i18n/locales/en.json`, `de.json` —
  `gallery.scenario.proposalsOnly`, `gallery.scenario.disabledHint`,
  `gallery.filter.disabledHint`.
- `frontend/README.md` — Gallery section.

## Gates

prettier, eslint, vue-tsc, 332 vitest cases, `vite build` — green.
