<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  classColor,
  classInk,
  LOCO_LENGTH_M,
  SERVICE_COLOR,
  type Formation,
} from '@/lib/compositionFormation'

// Platform-display drawing of one composition: every vehicle to scale, each
// coach filled by the classes it carries and numbered by its position.
//
// Only the SELECTED coach is labelled with its type id. Printing all fourteen
// at 1.9 px/m ran the labels into each other — a 26 m coach is 49 px wide and
// "LR-SEATPOD" needs more than that — so the label moved to where there is
// room for it: a single line above the drawing, for the coach being pointed
// at. Amenities are not drawn on the vehicles either, for the same reason;
// they belong to the inspector, which the parent renders under the drawing.
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
const BODY_Y = 5
const BODY_H = 40
const BAND_Y = 10
const BAND_H = 30
// Glyph width of the 9px label face — a long type id is still clipped, but
// only the selected coach carries one, so it has its neighbours' room too.
const LABEL_CHAR_PX = 5.0
const HEIGHT = 62
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

    // The selected coach may borrow its neighbours' width for its label.
    const maxChars = Math.floor((width * 3) / LABEL_CHAR_PX)
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

// Hover previews, click pins. Without the pin a reader cannot move the
// pointer down to read the inspector without losing what they selected —
// which is exactly what made the old hover-only behaviour feel broken.
const hovered = ref<number | null>(null)
const shown = computed(() => hovered.value ?? props.selected)

const shownVehicle = computed(
  () => vehicles.value.find((v) => v.position !== null && v.position === shown.value) ?? null,
)

function pick(position: number | null) {
  if (position === null) return
  emit('select', position)
}
</script>

<template>
  <div class="flex flex-col gap-1">
    <!-- The label line: one coach at a time, where there is room to read it.
         Reserved even when nothing is selected, so the drawing does not jump
         as the pointer moves across it. -->
    <p class="h-4 text-[11px] leading-4 text-primary-50/70">
      <template v-if="shownVehicle">
        <b class="font-semibold text-primary-50">{{ shownVehicle.label }}</b>
        <span class="text-primary-50/50"> · {{ shownVehicle.title }}</span>
      </template>
    </p>
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
          @mouseenter="hovered = vehicle.position"
          @mouseleave="hovered = null"
          @blur="hovered = null"
          @focus="hovered = vehicle.position"
          @click="pick(vehicle.position)"
          @keydown.enter.prevent="pick(vehicle.position)"
          @keydown.space.prevent="pick(vehicle.position)"
        >
          <title>{{ vehicle.title }}</title>

          <rect
            :x="vehicle.x + 1"
            :y="BODY_Y"
            :width="vehicle.width - 2"
            :height="BODY_H"
            rx="5"
            :class="
              vehicle.position === null
                ? 'fill-primary-50/25 stroke-primary-50/30'
                : shown === vehicle.position
                  ? 'fill-primary-50/15 stroke-primary-50'
                  : selected === vehicle.position
                    ? 'fill-primary-50/10 stroke-primary-50/60'
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
              shown === vehicle.position
                ? 'fill-primary-50 text-[10px] font-bold'
                : 'fill-primary-50/50 text-[10px]'
            "
          >
            {{ vehicle.position }}
          </text>
        </g>
      </svg>
    </div>
  </div>
</template>
