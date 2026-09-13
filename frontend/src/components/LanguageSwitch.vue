<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useStore } from '@/stores/store'
import { UI_LANGUAGES, type UiLanguage } from '@/lib/uiLanguages'

// Order and availability live in lib/uiLanguages.ts — this component only
// renders them: live locales switch on click, announced ones are greyed out and
// explain themselves through the "coming soon" bubble.
const store = useStore()
const { t } = useI18n()

function select(lang: UiLanguage): void {
  if (lang.available) store.setLocale(lang.code)
}
</script>

<template>
  <nav class="flex items-center gap-2.5 text-[13.5px] leading-none">
    <template v-for="lang in UI_LANGUAGES" :key="lang.code">
      <button
        v-if="lang.available"
        type="button"
        class="lang text-white transition-colors hover:text-[var(--color-pure-green)]"
        :class="{ underline: store.locale === lang.code }"
        :aria-label="t('header.switchLanguageAria', { language: lang.name })"
        :aria-current="store.locale === lang.code ? 'true' : undefined"
        @click="select(lang)"
      >
        {{ lang.name }}
      </button>
      <span
        v-else
        class="lang coming-soon relative cursor-default text-white/45"
        :data-tip="t('header.comingSoon')"
        aria-disabled="true"
        tabindex="0"
      >
        {{ lang.name }}
        <span class="sr-only">— {{ t('header.comingSoon') }}</span>
      </span>
    </template>
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

/* The bubble hangs below the 42px utility bar, over the brand image — the bar
   never clips it. Pointer-events stay off so it cannot swallow a hover. */
.coming-soon::after {
  content: attr(data-tip);
  position: absolute;
  top: calc(100% + 10px);
  left: 50%;
  transform: translateX(-50%);
  padding: 3px 7px;
  border-radius: 3px;
  background: var(--color-sapphire);
  color: #fff;
  font-size: 11px;
  font-weight: 400;
  white-space: nowrap;
  opacity: 0;
  transition: opacity 120ms ease;
  pointer-events: none;
}

.coming-soon:hover::after,
.coming-soon:focus-visible::after {
  opacity: 1;
}
</style>
