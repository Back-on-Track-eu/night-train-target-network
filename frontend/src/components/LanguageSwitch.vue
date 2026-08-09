<script setup lang="ts">
import { useStore } from '@/stores/store'

// back-on-track.eu lists these seven UI languages, each written in its own
// language (endonyms — never translated). Multi-language is disabled for now:
// only English is active and underlined; the rest are shown for visual parity.
// Clicking has no effect, but hovering still behaves like BoT (hand cursor +
// green), so it reads as a real switcher. de.json is kept for when it's
// re-enabled.
const LANGUAGES = [
  { code: 'en', name: 'English' },
  { code: 'fr', name: 'Français' },
  { code: 'de', name: 'Deutsch' },
  { code: 'nl', name: 'Nederlands' },
  { code: 'it', name: 'Italiano' },
  { code: 'es', name: 'Español' },
  { code: 'pl', name: 'Polski' },
] as const

const store = useStore()
</script>

<template>
  <nav class="flex items-center gap-2.5 text-[13.5px] leading-none">
    <span
      v-for="lang in LANGUAGES"
      :key="lang.code"
      class="lang cursor-pointer text-white transition-colors"
      :class="{ underline: store.locale === lang.code }"
      :aria-current="store.locale === lang.code ? 'true' : undefined"
    >
      {{ lang.name }}
    </span>
  </nav>
</template>

<style scoped>
/* Match back-on-track.eu exactly: "Mark Pro Regular" faux-bolded (see the
   regular-only @font-face in style.css) — the synthetic bold is lighter than
   the true Mark Pro Bold face. */
.lang {
  font-family: 'Mark Pro Regular', 'Mark Pro', sans-serif;
  font-weight: 700;
}

/* Hover turns the label BoT's green (--nv-primary-accent on their site), even
   though a click is a no-op while multi-language is disabled. */
.lang:hover {
  color: var(--color-pure-green);
}
</style>
