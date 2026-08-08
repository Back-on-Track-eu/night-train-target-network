<script setup lang="ts">
import { ref, computed, nextTick, watch } from 'vue'
import Popover from 'primevue/popover'
import AppIcon from './AppIcon.vue'
import { mdiMagnify } from '@mdi/js'
import { useI18n } from 'vue-i18n'

// Country picker with the same search-in-a-popover look as StopSelect.vue.
interface Country {
  code: string
  name: string
}

const props = defineProps<{ countries: Country[] }>()
const emit = defineEmits<{ select: [code: string] }>()

const { t } = useI18n()
const popoverRef = ref<InstanceType<typeof Popover> | null>(null)
const inputRef = ref<HTMLInputElement | null>(null)
const listRef = ref<HTMLElement | null>(null)
const filterQuery = ref('')
// Index of the keyboard-highlighted row in `filtered`; drives the same
// background the mouse hover uses, so both share one highlight.
const activeIndex = ref(0)

const filtered = computed(() =>
  props.countries.filter(
    (c) => !filterQuery.value || c.name.toLowerCase().includes(filterQuery.value.toLowerCase()),
  ),
)

function open(event: MouseEvent) {
  filterQuery.value = ''
  popoverRef.value?.show(event)
}

function pick(country: Country) {
  emit('select', country.code)
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
  const c = filtered.value[activeIndex.value]
  if (c) pick(c)
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
      root: { class: 'country-select-overlay !p-0 !rounded-xl !shadow-2xl !min-w-64' },
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
        :placeholder="t('gallery.search.countryPlaceholder')"
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
        {{ t('gallery.search.noCountries') }}
      </p>
      <button
        v-for="(c, i) in filtered"
        :key="c.code"
        class="block w-full cursor-pointer rounded-lg px-4 py-3 text-left text-base text-primary-50 transition-colors"
        :class="i === activeIndex ? 'bg-[#2b2e4a]' : ''"
        @mouseenter="activeIndex = i"
        @click="pick(c)"
      >
        {{ c.name }}
      </button>
    </div>
  </Popover>
</template>

<style>
.country-select-overlay {
  background: #23263d !important;
  border: 1px solid var(--p-primary-50) !important;
}
.country-select-overlay *::-webkit-scrollbar {
  width: 5px !important;
}
.country-select-overlay *::-webkit-scrollbar-track {
  background: transparent !important;
}
.country-select-overlay *::-webkit-scrollbar-thumb {
  background: color-mix(in srgb, var(--p-primary-50) 50%, transparent) !important;
  border-radius: 99px !important;
}
.country-select-overlay *::-webkit-scrollbar-button {
  display: none !important;
}
</style>
