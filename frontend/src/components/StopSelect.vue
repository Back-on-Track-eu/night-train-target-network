<script setup lang="ts">
import { ref, computed, nextTick, watch } from 'vue'
import Popover from 'primevue/popover'
import AppIcon from './AppIcon.vue'
import { mdiMagnify } from '@mdi/js'
import { useI18n } from 'vue-i18n'
import type { Stop } from '@/types/api'

const props = defineProps<{ stops: Stop[]; disabledIds?: Set<string> }>()
const emit = defineEmits<{ select: [stop: Stop] }>()

const { t, locale } = useI18n()
const popoverRef = ref<InstanceType<typeof Popover> | null>(null)
const inputRef = ref<HTMLInputElement | null>(null)
const listRef = ref<HTMLElement | null>(null)
const filterQuery = ref('')
// Index of the keyboard-highlighted row in `filtered`; drives the same
// background the mouse hover uses, so both share one highlight.
const activeIndex = ref(0)

// One lowercase haystack per stop, built once per stops load: display name,
// Latin/ASCII forms, and the city and country names in EVERY catalog language
// (deliberately not just the UI locale — an Italian typing "Monaco" must find
// München Hbf on the English UI too). name_ascii makes the search
// diacritic-tolerant from the data side ("munchen" matches "München").
const haystacks = computed(() => {
  const map = new Map<string, string>()
  for (const s of props.stops) {
    const parts = [s.name, s.name_latin, s.name_ascii]
    if (s.city) parts.push(s.city.name, ...Object.values(s.city.names))
    if (s.country_names) parts.push(...Object.values(s.country_names))
    map.set(s.stop_id, parts.filter(Boolean).join('\u0000').toLowerCase())
  }
  return map
})

const filtered = computed(() => {
  const query = filterQuery.value.trim().toLowerCase()
  if (!query) return props.stops
  return props.stops.filter((s) => haystacks.value.get(s.stop_id)?.includes(query))
})

// Subtitle under each row: "city · country" in the current UI locale, falling
// back through English to the on-the-ground names.
function subtitle(s: Stop): string {
  const city = s.city ? s.city.names[locale.value] || s.city.names.en || s.city.name : ''
  const country = s.country_names?.[locale.value] || s.country_names?.en || s.country_code
  return city ? `${city} \u00b7 ${country}` : country
}

// Track gauge badge. Several values at break-of-gauge stations (Kaunas
// 1435 + 1520). null means the catalog found no usable track nearby — shown
// as such rather than omitted, because an unknown gauge is exactly what
// stops a stop from being checked for gauge compatibility later.
function gaugeLabel(s: Stop): string {
  if (!s.gauges_mm?.length) return t('proposal.gaugeUnknown')
  return `${s.gauges_mm.join(' \u00b7 ')} mm`
}

function open(event: MouseEvent) {
  filterQuery.value = ''
  popoverRef.value?.show(event)
}

function isDisabled(stop: Stop): boolean {
  return props.disabledIds?.has(stop.stop_id) ?? false
}

function pick(stop: Stop) {
  if (isDisabled(stop)) return
  emit('select', stop)
  filterQuery.value = ''
  popoverRef.value?.hide()
}

// First selectable (non-disabled) row — where the highlight lands on open and
// after the filter changes.
function firstEnabledIndex(): number {
  const i = filtered.value.findIndex((s) => !isDisabled(s))
  return i === -1 ? 0 : i
}

function scrollActiveIntoView() {
  nextTick(() => {
    listRef.value?.querySelectorAll('button')[activeIndex.value]?.scrollIntoView({
      block: 'nearest',
    })
  })
}

// Move the highlight by `delta`, wrapping around and skipping disabled rows.
function move(delta: number) {
  const items = filtered.value
  const n = items.length
  if (!n) return
  let i = activeIndex.value
  for (let step = 0; step < n; step++) {
    i = (i + delta + n) % n
    if (!isDisabled(items[i])) {
      activeIndex.value = i
      break
    }
  }
  scrollActiveIntoView()
}

function setActive(i: number) {
  if (!isDisabled(filtered.value[i])) activeIndex.value = i
}

function onEnter() {
  const stop = filtered.value[activeIndex.value]
  if (stop && !isDisabled(stop)) pick(stop)
}

function onShow() {
  activeIndex.value = firstEnabledIndex()
  nextTick(() => inputRef.value?.focus())
}

// Reset the highlight to the first selectable row whenever the filter changes.
watch(filtered, () => {
  activeIndex.value = firstEnabledIndex()
})
</script>

<template>
  <span class="inline-flex cursor-pointer" @click="open">
    <slot />
  </span>
  <Popover
    ref="popoverRef"
    :pt="{
      root: { class: 'stop-select-overlay !p-0 !rounded-xl !shadow-2xl !min-w-64' },
      content: { class: '!p-0 !bg-transparent' },
    }"
    @show="onShow"
  >
    <div
      class="flex items-center gap-2.5 px-3 py-3"
      style="border-bottom: 1px solid var(--p-primary-50)"
    >
      <AppIcon
        :path="mdiMagnify"
        :size="13"
        color="color-mix(in srgb, var(--p-primary-50) 70%, transparent)"
        class="shrink-0"
      />
      <input
        ref="inputRef"
        v-model="filterQuery"
        type="text"
        :placeholder="t('proposal.searchPlaceholder')"
        style="
          flex: 1;
          background: transparent;
          border: none;
          outline: none;
          box-shadow: none;
          color: var(--p-primary-50);
          font-size: 1rem;
          padding: 0;
          font-family: inherit;
        "
        @keydown.enter.prevent="onEnter"
        @keydown.down.prevent="move(1)"
        @keydown.up.prevent="move(-1)"
      />
    </div>
    <div
      ref="listRef"
      class="overflow-y-auto p-1.5"
      style="
        max-height: 20rem;
        scrollbar-width: thin;
        scrollbar-color: color-mix(in srgb, var(--p-primary-50) 50%, transparent) transparent;
      "
    >
      <p v-if="!filtered.length" class="px-4 py-3 text-base text-primary-50/70">
        {{ t('proposal.noStopsFound') }}
      </p>
      <button
        v-for="(stop, i) in filtered"
        :key="stop.stop_id"
        class="block w-full rounded-lg px-4 py-3 text-left text-base transition-colors"
        :class="[
          isDisabled(stop)
            ? 'cursor-not-allowed text-primary-50/30'
            : 'cursor-pointer text-primary-50',
          !isDisabled(stop) && i === activeIndex ? 'bg-[#2b2e4a]' : '',
        ]"
        :disabled="isDisabled(stop)"
        @mouseenter="setActive(i)"
        @click="pick(stop)"
      >
        <span class="flex items-baseline gap-3">
          <span class="min-w-0 flex-1 truncate">{{ stop.name }}</span>
          <span
            class="shrink-0 text-sm tabular-nums"
            :class="[
              isDisabled(stop) ? 'text-primary-50/20' : 'text-primary-50/50',
              stop.gauges_mm?.length ? '' : 'italic',
            ]"
            :title="t('proposal.trackGauge')"
          >
            {{ gaugeLabel(stop) }}
          </span>
        </span>
        <span
          v-if="subtitle(stop)"
          class="block text-sm"
          :class="isDisabled(stop) ? 'text-primary-50/20' : 'text-primary-50/50'"
        >
          {{ subtitle(stop) }}
        </span>
      </button>
    </div>
  </Popover>
</template>

<style>
.stop-select-overlay {
  background: #23263d !important;
  border: 1px solid var(--p-primary-50) !important;
}
.stop-select-overlay *::-webkit-scrollbar {
  width: 5px !important;
}
.stop-select-overlay *::-webkit-scrollbar-track {
  background: transparent !important;
}
.stop-select-overlay *::-webkit-scrollbar-thumb {
  background: color-mix(in srgb, var(--p-primary-50) 50%, transparent) !important;
  border-radius: 99px !important;
}
.stop-select-overlay *::-webkit-scrollbar-button {
  display: none !important;
}
</style>
