<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  classColor,
  classInk,
  LOCO_LENGTH_M,
  SERVICE_COLOR,
  type Formation,
} from '@/lib/compositionFormation'

// Platform-display drawing of one composition: every vehicle to scale, each
// coach filled by the classes it carries, labelled with its type and
// position. Amenities are deliberately NOT drawn here — at this scale the
// glyphs were unreadable; they belong to the inspector line under the drawing,
// which shows them for the coach being pointed at.
const props = defineProps<{
  formation: Formation
  selected: number | null
}>()
const emit = defineEmits<{ select: [position: number] }>()

const { t } = useI18n()

// Geometry — SVG units are px at the natural size. The scale is a constant
// rather than fitted per composition, so a 6-coach train reads as shorter
// than a 14-coach one when they are compared card by card; at 1.9 px/m the
// longest catalogue train still fits the overlay without scrolling.
const PX_PER_M = 1.9
const MARGIN_X = 4
const BODY_Y = 13
const BODY_H = 40
const BAND_Y = 18
const BAND_H = 30
// Glyph width of the 8px label face — long type ids are clipped to fit.
const LABEL_CHAR_PX = 4.6
const HEIGHT = 70
// Below this a band is too narrow for even a two-digit count.
const BAND_MIN_COUNT_PX = 11

interface DrawnSection {
  x: number
  width: number
  color: string
  ink: string
  places: number
  // Whether the band is wide enough to print the count at all — a 4-berth
  // section of a mini-cabin coach is only a few pixels across.
  showPlaces: boolean
}

interface DrawnVehicle {
  key: string
  position: number | null
  label: string
  x: number
  width: number
  title: string
  sections: DrawnSection[]
  isService: boolean
}

// One left-to-right pass over locomotives and coaches, laying every vehicle
// out at its real length; nothing downstream needs to know the scale.
const vehicles = computed<DrawnVehicle[]>(() => {
  const out: DrawnVehicle[] = []
  let x = MARGIN_X

  for (let i = 0; i < props.formation.locos; i++) {
    const width = LOCO_LENGTH_M * PX_PER_M
    out.push({
      key: `loco-${i}`,
      position: null,
      label: '',
      x,
      width,
      title: t('proposal.composition.loco'),
      sections: [],
      isService: false,
    })
    x += width
  }

  for (const coach of props.formation.coaches) {
    const width = coach.type.length_m * PX_PER_M
    const inner = width - 8
    let cursor = x + 4
    const sections: DrawnSection[] = coach.sections.map((section) => {
      const sectionWidth = section.share * inner
      const drawn: DrawnSection = {
        x: cursor,
        width: sectionWidth,
        color: classColor(section.classMain),
        ink: classInk(section.classMain),
        places: section.places,
        showPlaces: sectionWidth > BAND_MIN_COUNT_PX,
      }
      cursor += sectionWidth
      return drawn
    })

    // "WLABmz (DD)" is 11 characters and would run into the neighbouring
    // coach's label at this scale.
    const maxChars = Math.floor(width / LABEL_CHAR_PX)
    const label =
      coach.coachTypeId.length > maxChars
        ? `${coach.coachTypeId.slice(0, maxChars - 1)}…`
        : coach.coachTypeId

    out.push({
      key: `coach-${coach.position}`,
      position: coach.position,
      label,
      x,
      width,
      title: `${coach.coachTypeId} · ${coach.type.length_m} m · ${coach.type.places_total} ${t('proposal.composition.places')}`,
      sections,
      isService: coach.isService,
    })
    x += width
  }

  return out
})

const width = computed(() => props.formation.totalLengthM * PX_PER_M + 2 * MARGIN_X)
</script>

<template>
  <div class="overflow-x-auto">
    <svg
      :width="width"
      :height="HEIGHT"
      :viewBox="`0 0 ${width} ${HEIGHT}`"
      class="h-auto max-w-full"
      role="img"
      :aria-label="t('proposal.composition.formation')"
    >
      <g
        v-for="vehicle in vehicles"
        :key="vehicle.key"
        :class="vehicle.position !== null ? 'cursor-pointer' : ''"
        :tabindex="vehicle.position !== null ? 0 : undefined"
        :role="vehicle.position !== null ? 'button' : undefined"
        :aria-label="vehicle.title"
        @mouseenter="vehicle.position !== null && emit('select', vehicle.position)"
        @focus="vehicle.position !== null && emit('select', vehicle.position)"
        @click="vehicle.position !== null && emit('select', vehicle.position)"
      >
        <title>{{ vehicle.title }}</title>

        <!-- Coach type above the body; the locomotive is drawn dark and unlabelled -->
        <text
          v-if="vehicle.label"
          :x="vehicle.x + vehicle.width / 2"
          :y="9"
          text-anchor="middle"
          class="fill-primary-50/60 text-[8px]"
        >
          {{ vehicle.label }}
        </text>
        <rect
          :x="vehicle.x + 1"
          :y="BODY_Y"
          :width="vehicle.width - 2"
          :height="BODY_H"
          rx="5"
          :class="
            vehicle.position === null
              ? 'fill-primary-50/25 stroke-primary-50/30'
              : selected === vehicle.position
                ? 'fill-primary-50/15 stroke-primary-50'
                : 'fill-primary-50/5 stroke-primary-50/25'
          "
        />

        <!-- Class band: one segment per accommodation section, width by places -->
        <template v-if="!vehicle.isService">
          <g v-for="(section, i) in vehicle.sections" :key="i">
            <rect
              :x="section.x"
              :y="BAND_Y"
              :width="section.width"
              :height="BAND_H"
              rx="2"
              :fill="section.color"
            />
            <text
              v-if="section.showPlaces"
              :x="section.x + section.width / 2"
              :y="BAND_Y + BAND_H / 2 + 4"
              text-anchor="middle"
              :fill="section.ink"
              class="text-[11px] font-bold"
            >
              {{ section.places }}
            </text>
          </g>
        </template>
        <rect
          v-else-if="vehicle.position !== null"
          :x="vehicle.x + 4"
          :y="BAND_Y"
          :width="vehicle.width - 8"
          :height="BAND_H"
          rx="2"
          :fill="SERVICE_COLOR"
        />

        <!-- Position number under the vehicle -->
        <text
          v-if="vehicle.position !== null"
          :x="vehicle.x + vehicle.width / 2"
          :y="HEIGHT - 5"
          text-anchor="middle"
          :class="
            selected === vehicle.position
              ? 'fill-primary-50 text-[10px] font-bold'
              : 'fill-primary-50/50 text-[10px]'
          "
        >
          {{ vehicle.position }}
        </text>
      </g>
    </svg>
  </div>
</template>
