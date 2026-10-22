<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { mdiWeatherNight } from '@mdi/js'
import AppIcon from '@/components/AppIcon.vue'
import GalleryHistogram from '@/components/GalleryHistogram.vue'
import InfoHint from '@/components/InfoHint.vue'
import { CORRIDOR_COLORS } from '@/lib/galleryMap'
import {
  GALLERY_MEASURES,
  isTypicalNightTrain,
  normalizeRanges,
  typicalNightTrainRanges,
  type Bounds,
  type GalleryMeasure,
  type GalleryRanges,
} from '@/lib/galleryRanges'
import { TYPICAL_NIGHT_TRAIN } from '@/lib/typicalNightTrain'
import type { DistributionsSection } from '@/types/api'

// The gallery's range filters, all four measures at once (one
// GalleryHistogram each), under the "typical night trains" preset. The body
// only: Gallery.vue puts it in a popover behind the ranges chip on a desktop
// and in the Filters sheet on a phone, and GalleryRangesChip.vue names what is
// in effect while it is closed.
//
// The preset is not a stored switch: it is on exactly while the ranges equal
// it (isTypicalNightTrain), so editing any range turns it off by itself, and
// turning it off clears every range.
const props = defineProps<{
  ranges: GalleryRanges
  distributions: DistributionsSection | null
  status: 'idle' | 'loading' | 'failed'
}>()
const emit = defineEmits<{
  (e: 'update:ranges', ranges: GalleryRanges): void
  (e: 'retry'): void
}>()

const { t } = useI18n()

// --- the preset ----------------------------------------------------------------
const presetOn = computed(() => isTypicalNightTrain(props.ranges))
const presetHint = computed(() =>
  t('gallery.filter.typicalHint', {
    minKm: TYPICAL_NIGHT_TRAIN.distanceKm.min,
    maxKm: TYPICAL_NIGHT_TRAIN.distanceKm.max,
    minH: TYPICAL_NIGHT_TRAIN.timeH.min,
    maxH: TYPICAL_NIGHT_TRAIN.timeH.max,
    minKmh: TYPICAL_NIGHT_TRAIN.avgSpeedKmh.min,
  }),
)
function togglePreset(): void {
  emit('update:ranges', presetOn.value ? {} : typicalNightTrainRanges())
}

function commit(measure: GalleryMeasure, bounds: Bounds): void {
  emit('update:ranges', normalizeRanges({ ...props.ranges, [measure]: bounds }))
}
</script>

<template>
  <section class="flex flex-col gap-4" :aria-label="t('gallery.distribution.title')">
    <!-- The preset, in the ownership pill's idiom; the bounds and what it
         leaves alone behind the app's ⓘ overlay. -->
    <span class="flex items-center gap-1">
      <button
        type="button"
        class="flex cursor-pointer items-center gap-1.5 rounded-full border border-primary-50/20 px-3 py-1.5 text-sm transition"
        :class="
          presetOn
            ? 'bg-primary-50/15 font-semibold text-primary-50'
            : 'text-primary-50/60 hover:text-primary-50'
        "
        :aria-pressed="presetOn"
        @click="togglePreset"
      >
        <AppIcon :path="mdiWeatherNight" :size="16" />
        {{ t('gallery.filter.typical') }}
      </button>
      <InfoHint :text="presetHint" />
    </span>

    <div class="grid grid-cols-1 gap-x-8 gap-y-5 lg:grid-cols-2">
      <GalleryHistogram
        v-for="measure in GALLERY_MEASURES"
        :key="measure"
        :measure="measure"
        :bounds="ranges[measure] ?? {}"
        :data="distributions?.[measure] ?? null"
        :status="status"
        @update:bounds="commit(measure, $event)"
        @retry="emit('retry')"
      />
    </div>

    <div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-primary-50/60">
      <span class="flex items-center gap-1.5 whitespace-nowrap">
        <i
          class="inline-block h-2.5 w-2.5 rounded-sm"
          :style="{ backgroundColor: CORRIDOR_COLORS.proposed }"
        />
        {{ t('gallery.map.legend.proposed') }}
      </span>
      <span class="flex items-center gap-1.5 whitespace-nowrap">
        <i
          class="inline-block h-2.5 w-2.5 rounded-sm"
          :style="{ backgroundColor: CORRIDOR_COLORS.existing }"
        />
        {{ t('gallery.distribution.existingAlways') }}
      </span>
      <span v-if="distributions?.total_distance_km.unknown.n_existing" class="whitespace-nowrap">
        {{
          t(
            'gallery.distribution.unknownExisting',
            distributions.total_distance_km.unknown.n_existing,
          )
        }}
      </span>
    </div>
  </section>
</template>
