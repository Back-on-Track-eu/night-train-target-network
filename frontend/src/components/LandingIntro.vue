<script setup lang="ts">
import { onActivated, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { mdiPlus } from '@mdi/js'
import AppIcon from '@/components/AppIcon.vue'
import { ctaButtonClass } from '@/lib/ctaButtonClass'

const { t } = useI18n()

const emit = defineEmits<{ create: []; browse: [] }>()

// Where the pitch sends the curious: Back-on-Track's reports and studies as
// a whole (the 300-connection target, the passenger and emission figures
// all live there), rather than one paper — the pitch is an invitation, not
// a citation.
const STUDIES_URL = 'https://back-on-track.eu/reports-and-studies/'

// The documentation site: a separate static site served at /docs/ on this
// origin, so plain anchors and root-relative paths, not router links. Its
// landing page is the About page, so that is the bare /docs/ link.
const DOCS_ABOUT_URL = '/docs/'

// The three quieter buttons next to the one filled call to action. Same shape
// so the row reads as one set, one weight down so "suggest a route" stays the
// obvious thing to do.
const quietButtonClass =
  'flex cursor-pointer items-center gap-1.5 rounded-full border border-primary-50/20 px-5 py-2 text-sm text-primary-50/70 transition hover:border-primary-50/40 hover:text-primary-50'

// --- Opening band sizing ----------------------------------------------------
// The band fills the viewport below whatever sits above it (App.vue's header,
// the API status banner, the page padding), so a fresh visitor sees the pitch
// and nothing else. Measured rather than hardcoded: the header carries a
// background image and the status banner comes and goes, so neither offset is
// a constant.
const hero = ref<HTMLElement | null>(null)
const heroMinHeight = ref('100vh')
let observer: ResizeObserver | null = null

function measureHero(): void {
  if (!hero.value) return
  const top = hero.value.getBoundingClientRect().top + window.scrollY
  heroMinHeight.value = `calc(100vh - ${Math.max(0, Math.round(top))}px)`
}

onMounted(() => {
  measureHero()
  // Watches the whole document rather than the band itself: what moves it is
  // everything ABOVE changing height (header image loading, status banner
  // appearing), which an observer on the band would never see.
  observer = new ResizeObserver(measureHero)
  observer.observe(document.body)
  window.addEventListener('resize', measureHero)
})

onBeforeUnmount(() => {
  observer?.disconnect()
  observer = null
  window.removeEventListener('resize', measureHero)
})

// The gallery around this component is kept alive (App.vue), so coming back
// re-activates rather than re-mounts it — and the layout above can have changed
// in the meantime.
onActivated(measureHero)
</script>

<template>
  <!-- Opening band: the statement on the left, the argument and every way
       onward on the right. Sized to fill the viewport — see measureHero. -->
  <section ref="hero" class="flex w-full flex-col" :style="{ minHeight: heroMinHeight }">
    <!-- my-auto centres the block in the band. A grid rather than a flex row:
         the headline must sit level with the middle of the PARAGRAPH, and in a
         two-column flex layout it centred on the whole right column — paragraph
         plus the button row beneath it — which put it a line or two too low.
         With the buttons as a second grid row (starting in the second column
         so they stay under the paragraph), items-center on the first row
         centres the statement on the text alone. 2:3 keeps the previous
         column split. -->
    <div class="my-auto grid grid-cols-[2fr_3fr] gap-x-12 gap-y-8 px-24">
      <h1 class="self-center text-4xl font-light text-white">{{ t('gallery.heading') }}</h1>

      <!-- i18n-t rather than a plain <p>: the pitch's last sentence carries
           its source as a link ({source} in the copy), and splitting the
           sentence to get an <a> in would leave it untranslatable as one
           unit. The copy carries the launch gate's press facts
           (backend/api/gate_page.py) in a lighter voice — keep the facts in
           step with the gate when either changes. -->
      <i18n-t
        keypath="gallery.welcome.pitch"
        tag="p"
        class="self-center text-sm leading-relaxed text-primary-50/70"
      >
        <template #source>
          <a
            :href="STUDIES_URL"
            target="_blank"
            rel="noopener"
            class="underline underline-offset-2 transition hover:text-primary-50"
          >
            {{ t('gallery.welcome.source') }}
          </a>
        </template>
      </i18n-t>

      <!-- Every way into the site: contribute one, read the others, or read
           up. The About button leaves the SPA for the static site at
           /docs/, hence anchors rather than router links. -->
      <div class="col-start-2 flex flex-wrap items-center gap-3">
        <button type="button" :class="ctaButtonClass" @click="emit('create')">
          <AppIcon :path="mdiPlus" :size="18" />
          {{ t('gallery.cta.create') }}
        </button>
        <button type="button" :class="quietButtonClass" @click="emit('browse')">
          {{ t('gallery.welcome.browse') }}
        </button>
        <a :href="DOCS_ABOUT_URL" target="_blank" rel="noopener" :class="quietButtonClass">
          {{ t('gallery.welcome.about') }}
        </a>
      </div>
    </div>
  </section>
</template>
