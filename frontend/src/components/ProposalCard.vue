<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Avatar from 'primevue/avatar'
import AvatarGroup from 'primevue/avatargroup'
import { useStore } from '@/stores/store'
import type { ProposalSummary } from '@/types/api'

const props = defineProps<{
  proposal: ProposalSummary
  flash?: boolean
  // Countries in itinerary order; falls back to the summary's alphabetical list.
  orderedCountries?: string[]
}>()

const { t } = useI18n()
const store = useStore()

// Summaries carry stop_ids only (in travel order); resolve display names from
// the loaded stop list, falling back to the id (existing/ONTD rows may carry
// stop ids outside the curated list).
const nameById = computed(() => new Map(store.stops.map((s) => [s.stop_id, s.name])))
const stopName = (id: string): string => nameById.value.get(id) ?? id

const stopIds = computed(() => props.proposal.stop_ids)
const origin = computed(() => (stopIds.value.length ? stopName(stopIds.value[0]) : ''))
const destination = computed(() =>
  stopIds.value.length ? stopName(stopIds.value[stopIds.value.length - 1]) : '',
)
const intermediateStops = computed(() =>
  stopIds.value.slice(1, -1).map((id) => ({ stop_id: id, stop_name: stopName(id) })),
)

// Footer differs by source: a user proposal shows its proposer; an existing
// (ONTD) train links out to its catalog page.
const ontdUrl = computed(() =>
  props.proposal.source === 'existing' ? props.proposal.ontd_url : null,
)
const proposerLabel = computed(() =>
  props.proposal.source === 'proposal' ? `#${props.proposal.user_id}` : null,
)

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
    :class="flash ? 'bg-primary-50/20' : 'bg-primary-50/5'"
  >
    <!-- Upper half: itinerary (centered) with the country flags in the top-right
         corner. On hover the dash collapses and the intermediate stops grow in,
         pushing the destination down. -->
    <div class="relative">
      <div class="absolute right-0 top-0">
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
      </div>

      <div class="flex flex-col items-center px-8 text-center">
        <span class="text-base font-bold text-primary-50">{{ origin }}</span>
        <span
          class="max-h-6 overflow-hidden text-primary-50/40 opacity-100 transition-all duration-300 group-hover:max-h-0 group-hover:opacity-0"
          >—</span
        >
        <span
          v-for="s in intermediateStops"
          :key="s.stop_id"
          class="max-h-0 overflow-hidden whitespace-nowrap text-sm font-semibold text-primary-50/80 opacity-0 transition-all duration-300 group-hover:max-h-6 group-hover:opacity-100"
          >{{ s.stop_name }}</span
        >
        <span class="text-base font-bold text-primary-50">{{ destination }}</span>
      </div>
    </div>

    <!-- Lower half: distance (left) · proposer (right) -->
    <div class="mt-auto flex items-end justify-between gap-2 border-t border-primary-50/10 pt-3">
      <div class="flex gap-2 text-sm">
        <span class="text-primary-50/50">{{ t('gallery.card.distance') }}</span>
        <span class="text-primary-50">{{
          t('gallery.card.km', { value: proposal.total_distance_km })
        }}</span>
      </div>
      <a
        v-if="ontdUrl"
        :href="ontdUrl"
        target="_blank"
        rel="noopener noreferrer"
        class="text-xs text-primary-50/60 underline-offset-2 hover:underline"
      >
        {{ t('gallery.card.existing') }}
      </a>
      <span v-else class="text-xs text-primary-50/40">
        {{ t('gallery.card.proposedBy', { name: proposerLabel }) }}
      </span>
    </div>
  </article>
</template>

<style>
/* AvatarGroup laid out vertically with the discs overlapping (top-right of the
   card). Overrides PrimeVue's default horizontal spacing. */
.flag-group {
  display: flex;
  flex-direction: column;
}
.flag-group .p-avatar {
  margin: 0 !important;
}
.flag-group .p-avatar + .p-avatar {
  margin-top: -0.5rem !important;
}
.flag-group .p-avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
</style>
