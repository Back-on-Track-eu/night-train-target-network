<script setup lang="ts">
import { ref, computed, nextTick, watch } from 'vue'
import Popover from 'primevue/popover'
import AppIcon from './AppIcon.vue'
import { mdiMagnify } from '@mdi/js'

// A flat option picker with the same search-in-a-popover look as
// StopSelect.vue — the gallery's country and city fields. Options carry
// their own search text so a city can match in every catalogue language
// without the picker knowing what a city is.
export interface SelectOption {
  key: string
  label: string
  /** Second line under the label — a city's country, say. */
  subtitle?: string
  /** Lower-cased search text; the label alone when omitted. */
  haystack?: string
}

const props = defineProps<{ options: SelectOption[]; placeholder: string; emptyText: string }>()
const emit = defineEmits<{ select: [key: string] }>()

const popoverRef = ref<InstanceType<typeof Popover> | null>(null)
const inputRef = ref<HTMLInputElement | null>(null)
const listRef = ref<HTMLElement | null>(null)
const filterQuery = ref('')
// Index of the keyboard-highlighted row in `filtered`; drives the same
// background the mouse hover uses, so both share one highlight.
const activeIndex = ref(0)

const filtered = computed(() => {
  const query = filterQuery.value.trim().toLowerCase()
  if (!query) return props.options
  return props.options.filter((o) => (o.haystack ?? o.label.toLowerCase()).includes(query))
})

function open(event: MouseEvent) {
  filterQuery.value = ''
  popoverRef.value?.show(event)
}

function pick(option: SelectOption) {
  emit('select', option.key)
  filterQuery.value = ''
  popoverRef.value?.hide()
}

function scrollActiveIntoView() {
  nextTick(() => {
    listRef.value?.querySelectorAll('button')[activeIndex.value]?.scrollIntoView({
      block: 'nearest',
    })
  })
}

// Move the highlight by `delta`, wrapping around.
function move(delta: number) {
  const n = filtered.value.length
  if (!n) return
  activeIndex.value = (activeIndex.value + delta + n) % n
  scrollActiveIntoView()
}

function onEnter() {
  const option = filtered.value[activeIndex.value]
  if (option) pick(option)
}

function onShow() {
  activeIndex.value = 0
  nextTick(() => inputRef.value?.focus())
}

// Reset the highlight to the top whenever the filter changes.
watch(filtered, () => {
  activeIndex.value = 0
})
</script>

<template>
  <span class="inline-flex cursor-pointer" @click="open">
    <slot />
  </span>
  <Popover
    ref="popoverRef"
    :pt="{
      root: { class: 'option-select-overlay search-popover !p-0 !rounded-xl !shadow-2xl' },
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
        :placeholder="placeholder"
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
    <div ref="listRef" class="search-popover-list thin-scroll overflow-y-auto p-1.5">
      <p v-if="!filtered.length" class="px-4 py-3 text-base text-primary-50/70">
        {{ emptyText }}
      </p>
      <button
        v-for="(o, i) in filtered"
        :key="o.key"
        class="block w-full cursor-pointer rounded-lg px-4 py-3 text-left text-base text-primary-50 transition-colors"
        :class="i === activeIndex ? 'bg-[#2b2e4a]' : ''"
        @mouseenter="activeIndex = i"
        @click="pick(o)"
      >
        <span class="block truncate">{{ o.label }}</span>
        <span v-if="o.subtitle" class="block truncate text-xs text-primary-50/60">{{
          o.subtitle
        }}</span>
      </button>
    </div>
  </Popover>
</template>

<style>
.option-select-overlay {
  background: #23263d !important;
  border: 1px solid var(--p-primary-50) !important;
}
</style>
