<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Avatar from 'primevue/avatar'
import AvatarGroup from 'primevue/avatargroup'
import AppIcon from '@/components/AppIcon.vue'
import { useStore } from '@/stores/store'
import { useLocaleFormat } from '@/composables/useLocaleFormat'
import type { ProposalSummary } from '@/types/api'
import {
  mdiArrowLeftRight,
  mdiLeaf,
  mdiSpeedometerMedium,
  mdiThumbUpOutline,
  mdiTrainCarPassenger,
} from '@mdi/js'

const props = defineProps<{
  proposal: ProposalSummary
  flash?: boolean
  // Countries in itinerary order; falls back to the summary's alphabetical list.
  orderedCountries?: string[]
  // Stops the active gallery search targeted (A-to-B from/to, or the single
  // by-station stop). Any that fall strictly between origin and destination are
  // pinned as always-visible itinerary anchors so the card shows why it matched.
  highlightStopIds?: string[]
}>()

const emit = defineEmits<{ select: [proposalId: number] }>()

const { t } = useI18n()
const store = useStore()
const { formatInt } = useLocaleFormat()

// Summaries carry stop_ids only (in travel order); resolve display names from
// the loaded stop list, falling back to the id (existing/ONTD rows may carry
// stop ids outside the curated list).
const nameById = computed(() => new Map(store.stops.map((s) => [s.stop_id, s.name])))
const stopName = (id: string): string => nameById.value.get(id) ?? id

const stopIds = computed(() => props.proposal.stop_ids)

// Anchor indices into stop_ids: origin, destination, and any searched stops that
// land strictly between them. Everything between two anchors is that segment's
// collapsible "(N stops)" run.
const anchorIndices = computed(() => {
  const ids = stopIds.value
  if (ids.length <= 1) return ids.length ? [0] : []
  const last = ids.length - 1
  const highlighted = new Set(props.highlightStopIds ?? [])
  const mids = ids
    .map((id, i) => ({ id, i }))
    .filter(({ id, i }) => i > 0 && i < last && highlighted.has(id))
    .map(({ i }) => i)
  return [0, ...mids, last]
})

// Interleaved itinerary: anchors[i] then segments[i] (the intermediate stops
// between anchors[i] and anchors[i+1]); segments.length === anchors.length - 1.
const itinerary = computed(() => {
  const ids = stopIds.value
  const idxs = anchorIndices.value
  const anchors = idxs.map((idx, pos) => ({
    id: ids[idx],
    name: stopName(ids[idx]),
    // Endpoints (origin/destination) are bold; a pinned searched stop is the
    // same colour but less bold.
    highlighted: pos !== 0 && pos !== idxs.length - 1,
  }))
  const segments: { stop_id: string; stop_name: string }[][] = []
  for (let k = 0; k < idxs.length - 1; k++) {
    segments.push(
      ids.slice(idxs[k] + 1, idxs[k + 1]).map((id) => ({ stop_id: id, stop_name: stopName(id) })),
    )
  }
  return { anchors, segments }
})

// --- Lower-half stats (icon/value pairs, RouteStatsCard style) --------------
const compositionLabel = computed(
  () =>
    store.compositions.find((c) => c.composition_id === props.proposal.composition_id)
      ?.composition_id ?? props.proposal.composition_id,
)

const stats = computed(() => {
  const p = props.proposal
  const list = [
    {
      icon: mdiArrowLeftRight,
      value: t('gallery.card.km', { value: formatInt(p.total_distance_km) }),
    },
    { icon: mdiSpeedometerMedium, value: `${formatInt(p.avg_speed_kmh)} km/h` },
    { icon: mdiTrainCarPassenger, value: compositionLabel.value },
  ]
  // co2 savings is a proposal-only KPI and null without an evaluation snapshot.
  if (p.source === 'proposal' && p.co2_savings_t_per_year != null) {
    list.push({
      icon: mdiLeaf,
      value: t('gallery.card.co2PerYear', { value: formatInt(p.co2_savings_t_per_year) }),
    })
  }
  return list
})

// --- Footer: proposer (proposals) vs ONTD catalog link (existing trains) ----
const ontdUrl = computed(() =>
  props.proposal.source === 'existing' ? props.proposal.ontd_url : null,
)
const proposerName = computed(() => {
  const p = props.proposal
  if (p.source !== 'proposal') return null
  return p.is_guest ? t('gallery.card.guest') : p.display_name
})

// --- Whole-card click → open the proposal in ProposalViewport display mode.
// Existing (ONTD) trains have no stored proposal to open, so only proposal
// cards are clickable; the ONTD link / like button stop propagation.
const isClickable = computed(() => props.proposal.source === 'proposal')
function onCardClick() {
  if (props.proposal.source === 'proposal') emit('select', props.proposal.proposal_id)
}

// #TODO: wire the like button to POST/DELETE /api/proposal/<id>/like — NOT
// IMPLEMENTED YET. For now a click only surfaces a transient "not implemented"
// hint and fires no network request.
const likeHintVisible = ref(false)
let likeHintTimer: ReturnType<typeof setTimeout> | null = null
function onLikeClick() {
  likeHintVisible.value = true
  if (likeHintTimer) clearTimeout(likeHintTimer)
  likeHintTimer = setTimeout(() => (likeHintVisible.value = false), 1800)
}
onBeforeUnmount(() => {
  if (likeHintTimer) clearTimeout(likeHintTimer)
})

// Flags shown in itinerary order when available (the summary's own list is
// alphabetical).
const flagCountries = computed(() =>
  props.orderedCountries?.length ? props.orderedCountries : props.proposal.countries,
)
const flagUrl = (code: string) => `/flags/${code.toLowerCase()}.svg`

// Circular flag SVGs are vendored under public/flags/. Any country without a
// vendored flag (image load fails) falls back to its code shown as a label.
const failedFlags = ref(new Set<string>())
function markFailed(code: string) {
  failedFlags.value = new Set(failedFlags.value).add(code)
}
function avatarPt(code: string) {
  return {
    root: {
      class: 'overflow-hidden rounded-full',
      style:
        'width:1.55rem;height:1.55rem;border:2px solid #1e2038;font-size:0.65rem;background:#2b2e4a;color:var(--p-primary-50);',
    },
    image: { onError: () => markFailed(code) },
  }
}
</script>

<template>
  <article
    class="group flex flex-col gap-3 overflow-hidden rounded-xl p-4 transition-colors duration-500"
    :class="[flash ? 'bg-primary-50/20' : 'bg-primary-50/5', isClickable ? 'cursor-pointer' : '']"
    :role="isClickable ? 'button' : undefined"
    :tabindex="isClickable ? 0 : undefined"
    @click="onCardClick"
    @keydown.enter="onCardClick"
    @keydown.space.prevent="onCardClick"
  >
    <!-- Upper half: itinerary (centered). Between anchors we show "(N stops)"
         while idle; on hover it fades out and the actual intermediate stops
         slide in from above. -->
    <div class="flex flex-col items-center px-2 text-center">
      <template v-for="(anchor, i) in itinerary.anchors" :key="`a-${i}`">
        <span
          class="text-base text-primary-50"
          :class="anchor.highlighted ? 'font-semibold' : 'font-bold'"
          >{{ anchor.name }}</span
        >
        <template v-if="i < itinerary.segments.length && itinerary.segments[i].length">
          <span
            class="max-h-6 overflow-hidden text-sm text-primary-50/40 opacity-100 transition-all duration-300 group-hover:max-h-0 group-hover:opacity-0"
            >{{ t('gallery.card.stops', itinerary.segments[i].length) }}</span
          >
          <span
            v-for="s in itinerary.segments[i]"
            :key="s.stop_id"
            class="max-h-0 -translate-y-2 overflow-hidden whitespace-nowrap text-sm font-semibold text-primary-50/80 opacity-0 transition-all duration-300 group-hover:max-h-6 group-hover:translate-y-0 group-hover:opacity-100"
            >{{ s.stop_name }}</span
          >
        </template>
      </template>
    </div>

    <!-- Lower half: stat pairs (left) · flags + like + proposer (right) -->
    <div class="mt-auto flex items-start justify-between gap-3 border-t border-primary-50/10 pt-3">
      <div class="flex flex-col gap-2 text-primary-50/70">
        <div v-for="stat in stats" :key="stat.icon" class="flex items-center gap-2">
          <AppIcon :path="stat.icon" :size="18" />
          <span class="text-sm font-semibold text-primary-50/80">{{ stat.value }}</span>
        </div>
      </div>

      <div class="flex flex-col items-end gap-2">
        <AvatarGroup class="flag-group">
          <Avatar
            v-for="c in flagCountries"
            :key="c"
            :image="failedFlags.has(c) ? undefined : flagUrl(c)"
            :label="failedFlags.has(c) ? c : undefined"
            shape="circle"
            :pt="avatarPt(c)"
          />
        </AvatarGroup>

        <!-- Like button — proposal-only, not yet wired (see #TODO above). -->
        <div v-if="proposal.source === 'proposal'" class="flex items-center gap-2">
          <span v-if="likeHintVisible" class="whitespace-nowrap text-xs text-primary-50/50">{{
            t('gallery.card.notImplemented')
          }}</span>
          <button
            type="button"
            :aria-label="t('gallery.card.like')"
            class="flex h-9 w-9 cursor-pointer items-center justify-center rounded-full text-primary-50/70 transition hover:bg-primary-50/10 hover:text-primary-50"
            @click.stop="onLikeClick"
          >
            <AppIcon :path="mdiThumbUpOutline" :size="22" />
          </button>
        </div>

        <a
          v-if="ontdUrl"
          :href="ontdUrl"
          target="_blank"
          rel="noopener noreferrer"
          class="text-xs text-primary-50/60 underline-offset-2 hover:underline"
          @click.stop
        >
          {{ t('gallery.card.existing') }}
        </a>
        <span v-else class="text-xs text-primary-50/40">
          {{ t('gallery.card.proposedBy', { name: proposerName }) }}
        </span>
      </div>
    </div>
  </article>
</template>

<style>
/* Circular flag images fill their avatar disc; AvatarGroup keeps its default
   horizontal overlap. */
.flag-group .p-avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
</style>
