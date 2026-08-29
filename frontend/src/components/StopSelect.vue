<script setup lang="ts">
import { ref, computed, nextTick, watch } from 'vue'
import Popover from 'primevue/popover'
import AppIcon from './AppIcon.vue'
import { mdiMagnify } from '@mdi/js'
import { useI18n } from 'vue-i18n'
import type { Stop } from '@/types/api'

const props = defineProps<{ stops: Stop[]; disabledIds?: Set<string> }>()
const emit = defineEmits<{ select: [stop: Stop] }>()

const { t } = useI18n()
const popoverRef = ref<InstanceType<typeof Popover> | null>(null)
const inputRef = ref<HTMLInputElement | null>(null)
const listRef = ref<HTMLElement | null>(null)
const filterQuery = ref('')
// Index of the keyboard-highlighted row in `filtered`; drives the same
// background the mouse hover uses, so both share one highlight.
const activeIndex = ref(0)

const filtered = computed(() =>
  props.stops.filter(
    (s) => !filterQuery.value || s.name.toLowerCase().includes(filterQuery.value.toLowerCase()),
  ),
)

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
        {{ stop.name }}
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
