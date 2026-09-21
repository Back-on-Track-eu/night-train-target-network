<script setup lang="ts">
import { computed, ref, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import Popover from 'primevue/popover'
import AppIcon from '@/components/AppIcon.vue'
import AppSpinner from '@/components/AppSpinner.vue'
import CountryFlags from '@/components/CountryFlags.vue'
import { useStore } from '@/stores/store'
import { useToastStore } from '@/stores/toastStore'
import { useLocaleFormat } from '@/composables/useLocaleFormat'
import { formatEur } from '@/lib/money'
import { likeProposal, unlikeProposal } from '@/lib/proposalsApi'
import { useApiFailure } from '@/composables/useApiFailure'
import type { ProposalSummary } from '@/types/api'
import {
  mdiAccountGroupOutline,
  mdiArrowLeftRight,
  mdiCashMultiple,
  mdiCommentOutline,
  mdiLeaf,
  mdiSpeedometerMedium,
  mdiThumbUp,
  mdiThumbUpOutline,
  mdiTrainCarPassenger,
} from '@mdi/js'

const props = defineProps<{
  proposal: ProposalSummary
  // Stops the active gallery search targeted (A-to-B from/to, or the single
  // by-station stop). Any that fall strictly between origin and destination are
  // pinned as always-visible itinerary anchors so the card shows why it matched.
  highlightStopIds?: string[]
}>()

const emit = defineEmits<{ select: [proposalId: number]; discuss: [proposalId: number] }>()

const { t } = useI18n()
const store = useStore()
const { locale, formatInt, formatDate } = useLocaleFormat()
const { report } = useApiFailure()

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

// --- The figures --------------------------------------------------------
// One two-column grid, filled in a fixed order — distance | speed,
// composition | trips per year, CO₂ saved | subsidy per tonne — so the same
// fact sits in the same corner on every card and the list can be read down
// a column instead of re-parsed card by card: the route's physics on the
// first row, what runs and who rides on the second, climate and its price on
// the third. Every value is kept to ONE line: a figure that wraps breaks the
// alignment the grid exists for.
//
// Composition is proposals-only. An existing (ONTD) row carries whatever the
// catalogue names, but nothing in the app can pick, change or show it — so the
// label there is information without a use.
const compositionLabel = computed(() =>
  props.proposal.source === 'proposal' ? props.proposal.composition_id : null,
)

// A proposal row the gallery's chosen scenario has no figures for: not
// evaluable on that network ("error", with the member's code) or not yet
// backfilled ("missing"). The row itself is as real as any other — same
// identity, same stops, same place in the list — only its numbers are
// null, so the figure grid gives way to one line saying why. Never true on
// the base projection.
const withoutFigures = computed(
  () => props.proposal.source === 'proposal' && props.proposal.status !== 'ok',
)
const noFiguresKey = computed(() =>
  props.proposal.source === 'proposal' && props.proposal.status === 'error'
    ? 'notEvaluable'
    : 'notYetEvaluated',
)

// Each stat carries a stable `key`: it identifies the cell for v-for AND selects
// the explanation shown in the shared popover below. (The v-for used to key on
// `icon`, which is a path string, not an identity.)
const stats = computed(() => {
  const p = props.proposal
  if (withoutFigures.value) return []
  const list = [
    {
      key: 'distance',
      icon: mdiArrowLeftRight,
      value: t('gallery.card.km', { value: formatInt(p.total_distance_km) }),
    },
    { key: 'speed', icon: mdiSpeedometerMedium, value: `${formatInt(p.avg_speed_kmh)} km/h` },
  ]
  // Everything past the first row is proposal-only: composition is known from
  // publish, the rest is null until the proposal has an evaluation snapshot.
  if (compositionLabel.value) {
    list.push({ key: 'composition', icon: mdiTrainCarPassenger, value: compositionLabel.value })
  }
  if (p.source === 'proposal' && p.demand_trips_per_year != null) {
    list.push({
      key: 'demand',
      icon: mdiAccountGroupOutline,
      value: t('gallery.card.demandPerYear', { value: formatInt(p.demand_trips_per_year) }),
    })
  }
  if (p.source === 'proposal' && p.co2_savings_t_per_year != null) {
    list.push({
      key: 'co2',
      icon: mdiLeaf,
      value: t('gallery.card.co2PerYear', { value: formatInt(p.co2_savings_t_per_year) }),
    })
  }
  // Straight after the saving it prices — the two are one argument.
  if (p.source === 'proposal' && p.subsidy_eur_per_t_co2 != null) {
    list.push({
      key: 'subsidyPerTCo2',
      icon: mdiCashMultiple,
      value: t('gallery.card.subsidyPerTCo2', {
        value: formatEur(p.subsidy_eur_per_t_co2, locale.value),
      }),
    })
  }
  return list
})

// --- Authoring dates -------------------------------------------------------
// Proposals only (an ONTD row has no author and no history). "Updated" is left
// off when it would repeat the creation date, which is the common case — a
// proposal published once and never revised should not carry the same date
// twice.
const dateLine = computed(() => {
  const p = props.proposal
  if (p.source !== 'proposal') return null
  const created = formatDate(p.created_at)
  const updated = formatDate(p.updated_at)
  if (!created) return null
  const parts = [t('gallery.card.created', { date: created })]
  if (updated && updated !== created) parts.push(t('gallery.card.updated', { date: updated }))
  return parts.join(' · ')
})

// --- Stat explanation popover ----------------------------------------------
// One Popover for every stat AND for the comment count, driven by the hovered
// item's key — engagement is explained the same way a KPI is. Same
// hover-intent shape as CostPanel.vue's cost-factor popover: open on enter,
// stay open while the cursor is over the panel itself, close on a short delay
// once it has left both — so moving from the row into the panel doesn't
// flicker-close it. `openKey` skips a redundant show() for the same row.
const statPopover = ref<InstanceType<typeof Popover> | null>(null)
const activeStatKey = ref<string | null>(null)
const openStatKey = ref<string | null>(null)
let closeTimer: ReturnType<typeof setTimeout> | null = null

function cancelClose() {
  if (closeTimer !== null) {
    clearTimeout(closeTimer)
    closeTimer = null
  }
}

function openStat(key: string, event: Event) {
  cancelClose()
  if (openStatKey.value === key) return
  activeStatKey.value = key
  statPopover.value?.show(event)
}

function scheduleClose() {
  cancelClose()
  closeTimer = setTimeout(() => statPopover.value?.hide(), 150)
}

// A card can be unmounted mid-delay (the gallery replaces the list on every
// filter change), so the pending timer must not outlive it.
onBeforeUnmount(cancelClose)

const activeStat = computed(() => {
  const key = activeStatKey.value
  if (!key) return null
  return {
    title: t(`gallery.card.stat.${key}.title`),
    body: t(`gallery.card.stat.${key}.body`),
  }
})

// Defined once at setup rather than as an inline :pt literal, which would
// allocate a fresh passthrough object (and fresh handler identities) on every
// render of every card in the list. Same convention as Gallery.vue's selectPt.
const statPopoverPt = {
  root: {
    class:
      'z-50 !rounded-xl !border !border-primary-50/20 !bg-sapphire-100 !shadow-xl before:!hidden after:!hidden',
    onMouseenter: cancelClose,
    onMouseleave: scheduleClose,
  },
  content: { class: '!p-4 !bg-transparent' },
}

// --- Footer: proposer (proposals) vs ONTD catalog link (existing trains) ----
const ontdUrl = computed(() =>
  props.proposal.source === 'existing' ? props.proposal.ontd_url : null,
)
const proposerName = computed(() => {
  const p = props.proposal
  if (p.source !== 'proposal') return null
  return p.is_guest ? t('gallery.card.guest') : p.display_name
})

// --- Whole-card click → the card's own destination. A proposal opens in
// ProposalViewport display mode (via @select); an existing (ONTD) train has no
// stored proposal, so it leaves for its back-on-track.eu catalogue entry — the
// same target as the footer link, which stops propagation so a click on it
// navigates once rather than twice. The like button stops propagation too.
const isClickable = computed(() => props.proposal.source === 'proposal' || !!ontdUrl.value)
// An existing train leaves the app, a proposal opens a view inside it — the two
// are announced accordingly.
const cardRole = computed(() => {
  if (!isClickable.value) return undefined
  return props.proposal.source === 'existing' ? 'link' : 'button'
})
function onCardClick() {
  if (props.proposal.source === 'proposal') {
    emit('select', props.proposal.proposal_id)
  } else if (ontdUrl.value) {
    window.open(ontdUrl.value, '_blank', 'noopener,noreferrer')
  }
}

// Liking requires a registered account (not guest, not logged out) — an info
// toast explains why otherwise. Initial liked-by-me state is unknown without
// an extra per-card fetch (the gallery list only carries the total count), so
// it starts false and self-corrects from the server's response on first
// click — an already-liked proposal's first click just re-confirms the like
// (idempotent) and syncs the icon, rather than actually toggling it off.
const toastStore = useToastStore()
const likeCount = ref(props.proposal.source === 'proposal' ? props.proposal.likes_count : 0)
// Read-only, unlike the like count: the card has no comment box, so this is
// the list's pointer to a discussion that lives in the proposal view.
const commentCount = computed(() =>
  props.proposal.source === 'proposal' ? props.proposal.comments_count : 0,
)
const likedByMe = ref(false)
const likeBusy = ref(false)

// The comment count is a link into the thread, not just a figure: the gallery
// routes to the proposal's discussion rather than to the top of its page.
function onCommentsClick() {
  if (props.proposal.source !== 'proposal') return
  emit('discuss', props.proposal.proposal_id)
}

async function onLikeClick() {
  if (props.proposal.source !== 'proposal') return
  if (store.authChoice !== 'user') {
    toastStore.addToast('info', t('gallery.card.loginToLike'))
    return
  }
  if (likeBusy.value) return
  likeBusy.value = true
  try {
    const result = likedByMe.value
      ? await unlikeProposal(props.proposal.proposal_id, store.authHeaders())
      : await likeProposal(props.proposal.proposal_id, store.authHeaders())
    likeCount.value = result.count
    likedByMe.value = result.liked_by_me
  } catch (err) {
    // The card has nowhere sensible to put inline copy, so this failure always
    // toasts — including the 429 the like endpoint really does rate-limit.
    report(err, { fallbackKey: 'errors.likeFailed', force: 'toast' })
  } finally {
    likeBusy.value = false
  }
}

// Alphabetical, as the summary carries them. Itinerary order used to come from
// the per-proposal route fetch the gallery no longer makes (the map now rides
// the list request), and is not worth one request per card on its own. The
// discs themselves are CountryFlags.vue, shared with the route stats panel.
const flagCountries = computed(() => props.proposal.countries)
</script>

<template>
  <!-- One bold thing per card: the route. Everything else is ranked by colour
       and size rather than weight — the previous card set the itinerary, every
       figure and both counts in semibold, which left nothing for the eye to
       land on first. -->
  <article
    class="group flex flex-col gap-2.5 overflow-hidden rounded-xl bg-primary-50/5 p-4 transition-colors duration-500 hover:bg-primary-50/[0.07]"
    :class="isClickable ? 'cursor-pointer' : ''"
    :role="cardRole"
    :tabindex="isClickable ? 0 : undefined"
    @click="onCardClick"
    @keydown.enter="onCardClick"
    @keydown.space.prevent="onCardClick"
  >
    <!-- Itinerary. Between anchors we show "(N stops)" while idle; on hover it
         fades out and the actual intermediate stops slide in from above. The
         intermediate names are the quietest text on the card: they are context
         for the route, not a second headline. -->
    <div class="flex flex-col items-center px-1 text-center leading-tight">
      <!-- The countries belong to the itinerary, not to the proposer: they say
           what the route crosses, so they head the stop list rather than
           sitting in the metadata foot. -->
      <CountryFlags :countries="flagCountries" class="mb-1.5" />
      <template v-for="(anchor, i) in itinerary.anchors" :key="`a-${i}`">
        <span
          class="text-base text-primary-50"
          :class="anchor.highlighted ? 'font-medium' : 'font-bold'"
          >{{ anchor.name }}</span
        >
        <template v-if="i < itinerary.segments.length && itinerary.segments[i].length">
          <span
            class="max-h-5 overflow-hidden py-0.5 text-xs font-normal text-primary-50/35 opacity-100 transition-all duration-300 group-hover:max-h-0 group-hover:py-0 group-hover:opacity-0"
            >{{ t('gallery.card.stops', itinerary.segments[i].length) }}</span
          >
          <span
            v-for="s in itinerary.segments[i]"
            :key="s.stop_id"
            class="max-h-0 -translate-y-2 overflow-hidden whitespace-nowrap py-0 text-xs font-normal text-primary-50/55 opacity-0 transition-all duration-300 group-hover:max-h-5 group-hover:translate-y-0 group-hover:py-0.5 group-hover:opacity-100"
            >{{ s.stop_name }}</span
          >
        </template>
      </template>
    </div>

    <!-- The figures, in a fixed two-column grid rather than a wrapping row.
         Values in tabular figures at one weight, icons dimmed to a third — the
         number is the content, the icon only says which number it is. This is
         the card's one rule: below it everything is metadata. -->
    <p
      v-if="withoutFigures"
      class="border-t border-primary-50/10 pt-2.5 text-xs text-primary-50/45"
    >
      {{ t(`gallery.card.${noFiguresKey}`) }}
    </p>
    <div v-else class="grid grid-cols-2 gap-x-3 gap-y-1.5 border-t border-primary-50/10 pt-2.5">
      <!-- w-fit so the hover target is the stat itself, not the full grid cell
           — otherwise the popover opens from empty space beside it. -->
      <div
        v-for="stat in stats"
        :key="stat.key"
        class="flex w-fit cursor-help items-center gap-2"
        @mouseenter="openStat(stat.key, $event)"
        @mouseleave="scheduleClose"
      >
        <AppIcon :path="stat.icon" :size="16" class="shrink-0 text-primary-50/35" />
        <span class="whitespace-nowrap text-sm tabular-nums text-primary-50/85">{{
          stat.value
        }}</span>
      </div>
    </div>

    <!-- Foot: who and when on the left, engagement on the right, behind a
         second hairline so the figures above close off cleanly. All of it is
         metadata, so all of it is small and dim; the two counts are the only
         interactive part. -->
    <div class="flex items-end justify-between gap-3 border-t border-primary-50/10 pt-2.5">
      <div class="flex min-w-0 items-center gap-2.5">
        <div class="flex min-w-0 flex-col gap-0.5">
          <!-- Where a proposal names its proposer, an existing train names
               itself as one — the card's only marker of which kind it is.
               Plain text, not a link: the whole card already leaves for the
               catalogue entry, so a nested link would just be a second way to
               do the same thing. -->
          <span
            v-if="ontdUrl"
            class="w-fit rounded-full bg-primary-50/10 px-2 py-0.5 text-[0.65rem] font-medium uppercase tracking-wider text-primary-50/60"
          >
            {{ t('gallery.card.existing') }}
          </span>
          <template v-else>
            <span class="truncate text-xs text-primary-50/55">
              {{ t('gallery.card.proposedBy', { name: proposerName }) }}
            </span>
            <span v-if="dateLine" class="truncate text-[0.7rem] text-primary-50/35">
              {{ dateLine }}
            </span>
          </template>
        </div>
      </div>

      <!-- Two identically built icon-then-count buttons: same box, same icon
           size, the number always to the RIGHT of its icon, on one baseline.
           Comments open the thread, likes toggle. -->
      <div v-if="proposal.source === 'proposal'" class="flex shrink-0 items-center gap-1">
        <button
          type="button"
          class="flex h-8 cursor-pointer items-center gap-1.5 rounded-full px-2 text-primary-50/55 transition hover:bg-primary-50/10 hover:text-primary-50"
          :aria-label="t('gallery.card.comments')"
          @click.stop="onCommentsClick"
          @mouseenter="openStat('comments', $event)"
          @mouseleave="scheduleClose"
        >
          <AppIcon :path="mdiCommentOutline" :size="18" />
          <span class="text-sm tabular-nums">{{ commentCount }}</span>
        </button>
        <button
          type="button"
          :disabled="likeBusy"
          :aria-label="t('gallery.card.like')"
          class="flex h-8 cursor-pointer items-center gap-1.5 rounded-full px-2 transition hover:bg-primary-50/10 disabled:cursor-not-allowed"
          :class="likedByMe ? 'text-primary-50' : 'text-primary-50/55 hover:text-primary-50'"
          @click.stop="onLikeClick"
        >
          <!-- likeBusy guarded double-clicks but drove no visual state, so the
               button looked inert for the whole round trip. -->
          <AppSpinner v-if="likeBusy" :size="18" />
          <AppIcon v-else :path="likedByMe ? mdiThumbUp : mdiThumbUpOutline" :size="18" />
          <span class="text-sm tabular-nums">{{ likeCount }}</span>
        </button>
      </div>
    </div>

    <!-- What each figure denominates. PrimeVue teleports this to body, so it
         sits above the card and its own hover keeps it open (see openStat). -->
    <Popover
      ref="statPopover"
      :pt="statPopoverPt"
      @show="openStatKey = activeStatKey"
      @hide="openStatKey = null"
    >
      <div v-if="activeStat" class="flex max-w-xs flex-col gap-1" @click.stop>
        <h4 class="text-sm font-bold text-primary-50">{{ activeStat.title }}</h4>
        <p class="text-xs leading-relaxed text-primary-50/70">{{ activeStat.body }}</p>
      </div>
    </Popover>
  </article>
</template>
