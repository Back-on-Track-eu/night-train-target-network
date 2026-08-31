import {
  mdiSeatPassenger,
  mdiBedOutline,
  mdiBed,
  mdiBunkBedOutline,
  mdiWifi,
  mdiBike,
  mdiAirConditioner,
  mdiPowerSocketEu,
} from '@mdi/js'
import type {
  ClassEntry,
  CoachType,
  Composition,
  CompositionDescriptions,
  OnboardEquipment,
} from '@/types/api'

// Accommodation classes in fixed order, each with a structurally distinct
// glyph. Three of the four are beds, so fill alone cannot separate them at
// 20px: mdiBed (Sleeper) and mdiBedOutline (Capsule) were the same shape,
// which made the NEW family — the only one carrying both — unreadable.
export const CLASS_ICONS: readonly [string, string][] = [
  ['Seat', mdiSeatPassenger],
  ['Couchette', mdiBedOutline],
  ['Sleeper', mdiBed],
  ['Capsule', mdiBunkBedOutline],
]

// Brand palette (back-on-track.eu/graphics), ordered as a comfort ramp so the
// formation reads left-to-right without the legend: sky blue → yellow-green →
// sulphur yellow → pure green.
export const CLASS_COLORS: Record<string, string> = {
  Seat: '#7db5d9',
  Couchette: '#92d051',
  Capsule: '#eaf044',
  Sleeper: '#008f39',
}

export const SERVICE_COLOR = '#2b2e4a'

const DARK_INK = '#1d1e33'
const LIGHT_INK = '#f1f3f6'

/** Perceived brightness of a #rrggbb fill (ITU-R BT.601 coefficients). */
function brightness(hex: string): number {
  const value = parseInt(hex.slice(1), 16)
  const r = (value >> 16) & 255
  const g = (value >> 8) & 255
  const b = value & 255
  return (r * 299 + g * 587 + b * 114) / 255000
}

// [equipment flag, glyph, i18n key under proposal.composition.equipment] —
// the same order wherever amenities are shown: card, overlay, and on each
// coach in the formation drawing.
export const AMENITY_ICONS: readonly [keyof OnboardEquipment, string, string][] = [
  ['has_wifi', mdiWifi, 'wifi'],
  ['has_bikes', mdiBike, 'bikes'],
  ['has_climatization', mdiAirConditioner, 'aircon'],
  ['has_plugs', mdiPowerSocketEu, 'plugs'],
]

export function classColor(classMain: string): string {
  return CLASS_COLORS[classMain] ?? SERVICE_COLOR
}

/** Text colour for a label printed ON a class fill — the palette spans light
 *  yellows and a dark green, so the ink follows the fill rather than being
 *  fixed. */
export function classInk(classMain: string): string {
  return brightness(classColor(classMain)) > 0.6 ? DARK_INK : LIGHT_INK
}

const CLASS_ICON_BY_NAME = Object.fromEntries(CLASS_ICONS) as Record<string, string | undefined>

export function classIcon(classMain: string): string | undefined {
  return CLASS_ICON_BY_NAME[classMain]
}

// Drawing-only assumption: the payload carries no locomotive length (only
// n_locos), and a Vectron measures 18.98 m over buffers. Replace this with the
// served value once loco types gain a length_m field.
export const LOCO_LENGTH_M = 19

export interface FormationSection {
  classMain: string
  // Section label with the redundant "<coach_type_id> - " prefix stripped.
  label: string
  places: number
  // Share of the coach's places, i.e. the width this section is drawn at.
  share: number
}

export interface FormationCoach {
  position: number
  coachTypeId: string
  type: CoachType
  sections: FormationSection[]
  // A coach without places — dining or baggage; drawn without a class band.
  isService: boolean
}

export interface Formation {
  locos: number
  coaches: FormationCoach[]
  // Coaches only, as served in routing.total_length_m.
  coachLengthM: number
  // Including the locomotives, at LOCO_LENGTH_M each.
  totalLengthM: number
}

const classOrder = CLASS_ICONS.map(([cls]) => cls)

/** Index the class catalog by coach type — the response groups it by
 *  class_main, but a formation is drawn coach by coach. */
function sectionsByCoachType(
  classes: Record<string, ClassEntry[]>,
): Record<string, { classMain: string; entry: ClassEntry }[]> {
  const index: Record<string, { classMain: string; entry: ClassEntry }[]> = {}
  for (const [classMain, entries] of Object.entries(classes)) {
    for (const entry of entries) {
      ;(index[entry.coach_type_id] ??= []).push({ classMain, entry })
    }
  }
  return index
}

/** Resolve a composition's ordered coach list into drawable coaches, each
 *  carrying the class sections it is made of. Coach types missing from the
 *  catalog are skipped rather than drawn at a guessed length. */
export function buildFormation(
  composition: Composition,
  coachTypes: Record<string, CoachType>,
  classes: Record<string, ClassEntry[]>,
): Formation {
  const index = sectionsByCoachType(classes)
  const coaches: FormationCoach[] = []

  for (const { position, coach_type_id } of composition.coaches.list) {
    const type = coachTypes[coach_type_id]
    if (!type) continue

    const sections = (index[coach_type_id] ?? [])
      .map(({ classMain, entry }) => ({
        classMain,
        label: entry.class_id.startsWith(`${coach_type_id} - `)
          ? entry.class_id.slice(coach_type_id.length + 3)
          : entry.class_id,
        places: entry.places,
        share: type.places_total > 0 ? entry.places / type.places_total : 0,
      }))
      .sort((a, b) => classOrder.indexOf(a.classMain) - classOrder.indexOf(b.classMain))

    coaches.push({
      position,
      coachTypeId: coach_type_id,
      type,
      sections,
      isService: type.places_total === 0,
    })
  }

  const coachLengthM = coaches.reduce((sum, c) => sum + c.type.length_m, 0)
  return {
    locos: composition.routing.n_locos,
    coaches,
    coachLengthM,
    totalLengthM: coachLengthM + composition.routing.n_locos * LOCO_LENGTH_M,
  }
}

/** Field documentation the backend ships with the payload, used as the
 *  overlay's tooltips (same treatment as the cost-factor popover's texts). */
export function describeField(
  descriptions: CompositionDescriptions,
  section: string,
  field: string,
): string | undefined {
  return descriptions.compositions[section]?.[field]
}
