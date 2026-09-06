<script setup lang="ts">
import { onActivated, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  mdiChevronDown,
  mdiMapMarkerPath,
  mdiPlus,
  mdiScaleBalance,
  mdiTrainCarPassenger,
} from '@mdi/js'
import AppIcon from '@/components/AppIcon.vue'
import { ctaButtonClass } from '@/lib/ctaButtonClass'

const { t } = useI18n()

const emit = defineEmits<{ create: []; browse: [] }>()

// Back-on-Track's general position paper — the source behind both the emission
// figure and the 300-route goal the pitch quotes.
const POSITION_PAPER_URL = 'https://back-on-track.eu/back-on-track-europes-general-position-paper/'

// The three readers the pitch addresses, in the order the copy builds them up:
// someone who wants a train, someone who knows how trains are run, someone who
// decides what gets funded. Keys resolve to gallery.audience.<key>.* strings.
const AUDIENCES = [
  { key: 'traveller', icon: mdiMapMarkerPath },
  { key: 'expert', icon: mdiTrainCarPassenger },
  { key: 'policy', icon: mdiScaleBalance },
] as const

// Collapsed on arrival: the opening band is the pitch, and a visitor who wants
// the detail asks for it. Lives in a kept-alive subtree, so the choice survives
// a there-and-back trip to a proposal.
const expanded = ref(false)
const panel = ref<HTMLElement | null>(null)
const clip = ref<HTMLElement | null>(null)

// Air kept above the heading in the one case the panel cannot fit whole.
const PANEL_TOP_MARGIN_PX = 24

function toggleStory(): void {
  expanded.value = !expanded.value
  alignPanel()
}

// Parks the panel's bottom edge on the fold: opening it reveals the whole panel
// and closing it puts the page back where it started, and neither shows the
// gallery underneath. The content is clipped rather than unmounted, so its
// scrollHeight is already the height the panel is animating towards — no need to
// wait out the transition to measure it, and the scroll runs alongside it.
function alignPanel(): void {
  const el = panel.value
  if (!el) return
  const top = el.getBoundingClientRect().top + window.scrollY
  const row = toggle.value?.offsetHeight ?? 0
  const height = row + (expanded.value ? (clip.value?.scrollHeight ?? 0) : 0)
  // A panel taller than the viewport can't have both edges on screen; showing
  // the heading beats showing the last paragraph.
  const target = Math.min(top + height - window.innerHeight, top - PANEL_TOP_MARGIN_PX)
  window.scrollTo({ top: Math.max(0, target), behavior: 'smooth' })
}

// --- Opening band sizing ----------------------------------------------------
// The band fills the viewport below whatever sits above it (App.vue's header,
// the API status banner, the page padding) MINUS the collapsed "how it works"
// row, so a fresh visitor sees the pitch and that row together without
// scrolling. Measured rather than hardcoded: the header carries a background
// image and the status banner comes and goes, so neither offset is a constant.
const hero = ref<HTMLElement | null>(null)
const toggle = ref<HTMLElement | null>(null)
const heroMinHeight = ref('100vh')
let observer: ResizeObserver | null = null

// The gap-6 between the two bands, plus the same again as air below the row so
// it doesn't sit flush against the fold.
const INTRO_TAIL_PX = 48

function measureHero(): void {
  if (!hero.value) return
  const top = hero.value.getBoundingClientRect().top + window.scrollY
  // The toggle, not the panel: its height is the same open or closed, so
  // expanding the panel doesn't retroactively shrink the band above it.
  const row = toggle.value?.offsetHeight ?? 0
  const reserved = Math.max(0, Math.round(top) + row + INTRO_TAIL_PX)
  heroMinHeight.value = `calc(100vh - ${reserved}px)`
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
  <div class="flex w-full flex-col gap-6">
    <!-- Opening band: the statement and both ways into the tool on the left,
         the argument on the right. Sized so the "how it works" row below still
         lands above the fold — see measureHero. -->
    <section ref="hero" class="flex w-full flex-col" :style="{ minHeight: heroMinHeight }">
      <!-- my-auto centres the row in the band while items-start keeps the two
           columns aligned to each other, so the lead-in and the first block
           heading share a line. Centring the columns individually would break
           that line the moment one side outgrew the other. -->
      <div class="my-auto flex items-start gap-12 px-24">
        <div class="flex w-2/5 shrink-0 flex-col items-start gap-6">
          <div class="flex flex-col gap-3">
            <p class="text-base font-semibold text-primary-50/60">
              {{ t('gallery.welcome.lead') }}
            </p>
            <h1 class="text-4xl font-light text-white">{{ t('gallery.heading') }}</h1>
          </div>

          <!-- Both entry points together: contribute one, or read the rest.
               Centred on each other rather than flush left, so the pill and the
               link below it read as one stack; the chevron sits under its label,
               pointing down the page, which is where it goes. -->
          <div class="flex flex-col items-center gap-3">
            <button type="button" :class="ctaButtonClass" @click="emit('create')">
              <AppIcon :path="mdiPlus" :size="18" />
              {{ t('gallery.cta.create') }}
            </button>
            <button
              type="button"
              class="flex cursor-pointer flex-col items-center gap-0.5 text-sm text-primary-50/60 transition hover:text-primary-50"
              @click="emit('browse')"
            >
              {{ t('gallery.welcome.browse') }}
              <AppIcon :path="mdiChevronDown" :size="20" />
            </button>
          </div>
        </div>

        <div class="flex flex-1 flex-col gap-6">
          <div>
            <h2 class="text-base font-semibold text-primary-50">
              {{ t('gallery.welcome.case.title') }}
            </h2>
            <!-- i18n-t rather than a plain <p>: the emission figure has to
                 carry its source, and splitting the sentence to get an <a> in
                 would leave the copy untranslatable as one unit. -->
            <i18n-t
              keypath="gallery.welcome.case.body"
              tag="p"
              class="mt-1.5 text-sm leading-relaxed text-primary-50/70"
            >
              <template #source>
                <a
                  :href="POSITION_PAPER_URL"
                  target="_blank"
                  rel="noopener"
                  class="underline underline-offset-2 transition hover:text-primary-50"
                >
                  {{ t('gallery.welcome.case.source') }}
                </a>
              </template>
            </i18n-t>
          </div>

          <div>
            <h2 class="text-base font-semibold text-primary-50">
              {{ t('gallery.welcome.scale.title') }}
            </h2>
            <p class="mt-1.5 text-sm leading-relaxed text-primary-50/70">
              {{ t('gallery.welcome.scale.body') }}
            </p>
          </div>

          <div>
            <h2 class="text-base font-semibold text-primary-50">
              {{ t('gallery.welcome.network.title') }}
            </h2>
            <p class="mt-1.5 text-sm leading-relaxed text-primary-50/70">
              {{ t('gallery.welcome.network.body') }}
            </p>
          </div>
        </div>
      </div>
    </section>

    <!-- Who the tool is for, and what happens to what they submit — collapsed by
         default so the pitch above stays the page's whole first impression, but
         sitting above the fold so it is visibly there to open. -->
    <section ref="panel" class="px-24">
      <div class="overflow-hidden rounded-xl border border-primary-50/15">
        <button
          ref="toggle"
          type="button"
          class="flex w-full cursor-pointer items-center justify-between gap-6 px-6 py-4 text-left transition hover:bg-primary-50/5"
          :aria-expanded="expanded"
          aria-controls="landing-story"
          @click="toggleStory"
        >
          <span class="text-xl font-light text-white">{{ t('gallery.audience.title') }}</span>
          <span class="flex shrink-0 items-center gap-1.5 text-sm text-primary-50/60">
            {{ t('gallery.audience.toggle') }}
            <AppIcon
              :path="mdiChevronDown"
              :size="20"
              class="transition-transform duration-300"
              :class="expanded ? 'rotate-180' : ''"
            />
          </span>
        </button>

        <!-- 0fr -> 1fr animates the panel open without measuring its height, so
             editing the copy never means re-tuning a max-height. `inert` when
             closed keeps the collapsed content out of the tab order; the
             `|| undefined` is what removes the attribute rather than rendering
             inert="false", which the browser would still honour. -->
        <div
          id="landing-story"
          class="grid transition-[grid-template-rows] duration-300 ease-out"
          :class="expanded ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'"
          :inert="!expanded || undefined"
        >
          <div ref="clip" class="overflow-hidden">
            <div class="flex flex-col gap-8 border-t border-primary-50/10 px-6 py-6">
              <div class="grid gap-4 md:grid-cols-3">
                <div
                  v-for="audience in AUDIENCES"
                  :key="audience.key"
                  class="flex flex-col gap-3 rounded-xl bg-primary-50/5 p-5"
                >
                  <AppIcon :path="audience.icon" :size="24" class="text-primary-50/50" />
                  <p class="text-sm font-semibold text-primary-50">
                    {{ t(`gallery.audience.${audience.key}.title`) }}
                  </p>
                  <p class="text-sm leading-relaxed text-primary-50/70">
                    {{ t(`gallery.audience.${audience.key}.body`) }}
                  </p>
                </div>
              </div>

              <div class="flex flex-col gap-3 text-sm leading-relaxed text-primary-50/70">
                <p>
                  <span class="font-semibold text-primary-50">{{
                    t('gallery.story.crowd.label')
                  }}</span>
                  {{ t('gallery.story.crowd.body') }}
                </p>
                <p>
                  <span class="font-semibold text-primary-50">{{
                    t('gallery.story.outcome.label')
                  }}</span>
                  {{ t('gallery.story.outcome.body') }}
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>
