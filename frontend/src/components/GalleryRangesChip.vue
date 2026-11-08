<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { mdiChevronDown, mdiClose, mdiWeatherNight } from '@mdi/js'
import AppIcon from '@/components/AppIcon.vue'
import { useLocaleFormat } from '@/composables/useLocaleFormat'
import {
  GALLERY_MEASURES,
  isEmptyBounds,
  isTypicalNightTrain,
  type GalleryRanges,
} from '@/lib/galleryRanges'

// The closed state of the range filters, in the gallery's chip row: what is
// in effect, in as few words as a chip holds — the preset's name, "any
// length" when nothing is set, else the ranges themselves (the first two in
// words, a count for the rest) with an ✕ that clears them all. Clicking it
// opens or closes GalleryDistribution.vue under the search bar. `bar` drops
// the outline: the chip is then a suffix of the search bar, after a rule.
const props = defineProps<{ ranges: GalleryRanges; open?: boolean; bar?: boolean }>()
const emit = defineEmits<{ open: []; clear: [] }>()

const { t } = useI18n()
const { formatInt } = useLocaleFormat()

const presetOn = computed(() => isTypicalNightTrain(props.ranges))

const set = computed(() =>
  GALLERY_MEASURES.filter((key) => !isEmptyBounds(props.ranges[key])).map((key) => {
    const b = props.ranges[key]!
    const u = t(`gallery.distribution.unit.${key}`)
    const value =
      b.min !== undefined && b.max !== undefined
        ? `${formatInt(b.min)}–${formatInt(b.max)} ${u}`
        : b.min !== undefined
          ? `≥ ${formatInt(b.min)} ${u}`
          : `≤ ${formatInt(b.max!)} ${u}`
    const name = t(`gallery.distribution.measure.${key}`).replace(/\s*\(.*\)$/, '')
    return { name, value }
  }),
)

// One range is named in full; several show their values only.
const label = computed(() => {
  if (set.value.length === 1) return `${set.value[0].name} ${set.value[0].value}`
  return set.value
    .slice(0, 2)
    .map((r) => r.value)
    .join(' · ')
})
const more = computed(() => Math.max(0, set.value.length - 2))
</script>

<template>
  <span
    v-if="!presetOn && set.length"
    class="flex items-center gap-1.5 rounded-full border border-transparent bg-primary-50/15 pr-0.5 pl-3 text-sm leading-none whitespace-nowrap text-primary-50"
    :class="bar ? 'mx-1 h-9' : 'h-7.5'"
  >
    <AppIcon :path="mdiWeatherNight" :size="16" class="text-primary-50/70" />
    <button
      type="button"
      class="flex cursor-pointer items-center gap-1.5 tabular-nums"
      :aria-expanded="open"
      @click="emit('open')"
    >
      {{ label }}
      <span v-if="more" class="rounded-full bg-primary-50/15 px-1.5 text-xs">+{{ more }}</span>
    </button>
    <button
      type="button"
      class="flex h-6 w-6 cursor-pointer items-center justify-center rounded-full text-primary-50/70 transition hover:bg-primary-50/15 hover:text-primary-50"
      :aria-label="t('gallery.distribution.clearAll')"
      @click="emit('clear')"
    >
      <AppIcon :path="mdiClose" :size="14" />
    </button>
  </span>
  <button
    v-else
    type="button"
    class="flex cursor-pointer items-center gap-1.5 rounded-full px-3 text-sm leading-none whitespace-nowrap text-primary-50 transition hover:bg-primary-50/10"
    :class="
      bar
        ? 'h-11 px-3.5'
        : ['h-7.5 border', presetOn ? 'border-primary-50/20' : 'border-dashed border-primary-50/35']
    "
    :aria-expanded="open"
    @click="emit('open')"
  >
    <AppIcon :path="mdiWeatherNight" :size="16" class="text-primary-50/70" />
    {{ presetOn ? t('gallery.filter.typical') : t('gallery.distribution.anyLength') }}
    <AppIcon
      :path="mdiChevronDown"
      :size="16"
      class="text-primary-50/60 transition-transform"
      :class="open ? 'rotate-180' : ''"
    />
  </button>
</template>
