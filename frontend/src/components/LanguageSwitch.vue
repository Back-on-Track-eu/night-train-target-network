<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useStore } from '@/stores/store'
import type { Locale } from '@/lib/localeStorage'

// Endonyms — a language's own name is never translated. Only the languages
// with a locale file in i18n/locales/ belong here; listing one without
// messages would switch the UI to untranslated fallback English.
const LANGUAGES: { code: Locale; name: string }[] = [
  { code: 'en', name: 'English' },
  { code: 'de', name: 'Deutsch' },
]

const { t } = useI18n()
const store = useStore()
</script>

<template>
  <nav class="flex items-center gap-2.5 text-[13.5px] leading-none">
    <button
      v-for="lang in LANGUAGES"
      :key="lang.code"
      type="button"
      class="lang cursor-pointer text-white transition-colors"
      :class="{ underline: store.locale === lang.code }"
      :aria-current="store.locale === lang.code ? 'true' : undefined"
      :aria-label="t('header.switchLanguageAria', { language: lang.name })"
      @click="store.setLocale(lang.code)"
    >
      {{ lang.name }}
    </button>
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

/* Hover turns the label BoT's green (--nv-primary-accent on their site). */
.lang:hover {
  color: var(--color-pure-green);
}
</style>
