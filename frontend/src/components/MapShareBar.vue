<script setup lang="ts">
// The floating action pill over the proposal map: like, and share.
//
// Both halves belong to the proposal as a whole rather than to any panel below,
// which is why they sit on the map instead of inside the discussion — the like
// button used to live in CommentSection and moved here.
//
// Like state is injected, not fetched: the discussion thread reads the same
// GET /engagements response (see composables/useProposalEngagement.ts), so a
// click here updates the count there too.
//
// What the share channels can and cannot do is documented in lib/shareLinks.ts.
// The short version: Signal has no prefilled-text URL scheme and is reachable
// only through the OS share sheet, and the preview image comes from the Open
// Graph tags of the shared URL (api/proposal_share.py), never from these links.

import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Popover from 'primevue/popover'
import AppIcon from '@/components/AppIcon.vue'
import AppSpinner from '@/components/AppSpinner.vue'
import {
  mdiThumbUp,
  mdiThumbUpOutline,
  mdiShareVariant,
  mdiLinkVariant,
  mdiEmailOutline,
  mdiWhatsapp,
  mdiExportVariant,
} from '@mdi/js'
import { useToastStore } from '@/stores/toastStore'
import { useLocaleFormat } from '@/composables/useLocaleFormat'
import { useProposalEngagement } from '@/composables/useProposalEngagement'
import { API_BASE_URL } from '@/lib/apiBase'
import {
  buildShareUrls,
  canUseShareSheet,
  mailtoHref,
  whatsappHref,
  type RouteFacts,
} from '@/lib/shareLinks'

const props = defineProps<{
  proposalId: number
  /** First and last stop of the outbound route — the message names them. */
  origin: string
  destination: string
  /** Real computed figures, or null before a route exists; see routeFacts(). */
  facts: RouteFacts | null
}>()

const { t } = useI18n()
const { formatInt } = useLocaleFormat()
const toastStore = useToastStore()
const { likes, likeBusy, toggleLike } = useProposalEngagement()

const popoverRef = ref<InstanceType<typeof Popover> | null>(null)

// Computed once, not reactive: a browser does not grow a share sheet mid-session.
const hasShareSheet = canUseShareSheet()

const urls = computed(() => buildShareUrls(props.proposalId, window.location.origin, API_BASE_URL))

// The message body, without the link. The channels append it differently — and
// navigator.share() takes `url` as its own field, so a URL inside the text
// would show up twice in the share target.
const sentence = computed(() => {
  const names = { origin: props.origin, destination: props.destination }
  if (!props.facts) return t('proposal.share.messagePlain', names)
  return t('proposal.share.message', {
    ...names,
    km: formatInt(props.facts.km),
    stops: t('proposal.share.stopsCount', props.facts.stops),
    countries: t('proposal.share.countriesCount', props.facts.countries),
  })
})

const emailSubject = computed(() =>
  t('proposal.share.emailSubject', { origin: props.origin, destination: props.destination }),
)
const emailBody = computed(
  () =>
    `${t('proposal.share.emailBody', {
      origin: props.origin,
      destination: props.destination,
    })}\n\n${urls.value.shareUrl}\n`,
)

async function onCopyLink(): Promise<void> {
  popoverRef.value?.hide()
  try {
    // The clean /proposal/<id> URL, deliberately not the /share stub: this is
    // the one that gets pasted into documents and tickets.
    await navigator.clipboard.writeText(urls.value.appUrl)
    toastStore.addToast('success', t('proposal.share.copied'))
  } catch {
    // clipboard.writeText needs a secure context and a permission that can be
    // refused; there is no fallback worth the DOM hack, so say so.
    toastStore.addToast('error', t('proposal.share.copyFailed'))
  }
}

function onShareSheet(): void {
  // Called synchronously in the handler — navigator.share() rejects if the
  // user-gesture has already been spent by an await.
  const shared = navigator.share({
    title: `${props.origin} – ${props.destination}`,
    text: sentence.value,
    url: urls.value.shareUrl,
  })
  popoverRef.value?.hide()
  // A dismissed sheet rejects with AbortError. Nothing failed, so say nothing.
  shared.catch(() => {})
}

const pillButtonClass =
  'flex h-9 w-9 cursor-pointer items-center justify-center rounded-full text-primary-50/70 transition hover:bg-primary-50/10 hover:text-primary-50 disabled:cursor-not-allowed'
const menuItemClass =
  'flex w-full cursor-pointer items-center gap-3 rounded-lg px-3 py-2 text-sm text-primary-50/85 transition hover:bg-primary-50/10 hover:text-primary-50'
</script>

<template>
  <!-- The map wrapper in ProposalViewport is `relative isolate`, so this
       positions against the map and nothing else. -->
  <div
    class="absolute bottom-3 left-3 z-10 flex items-center gap-1 rounded-full border border-primary-50/15 bg-sapphire-100/95 px-1.5 py-1 shadow-lg"
  >
    <span v-if="likes.count > 0" class="pl-2 text-sm font-semibold text-primary-50/70">
      {{ likes.count }}
    </span>
    <button
      type="button"
      :disabled="likeBusy"
      :aria-label="t('proposal.share.like')"
      :title="t('proposal.share.like')"
      :class="[pillButtonClass, likes.liked_by_me ? '!text-primary-50' : '']"
      @click="toggleLike"
    >
      <AppSpinner v-if="likeBusy" :size="18" />
      <AppIcon v-else :path="likes.liked_by_me ? mdiThumbUp : mdiThumbUpOutline" :size="21" />
    </button>

    <span class="h-5 w-px bg-primary-50/15" aria-hidden="true" />

    <button
      type="button"
      :aria-label="t('proposal.share.title')"
      :title="t('proposal.share.title')"
      :class="pillButtonClass"
      @click="popoverRef?.toggle($event)"
    >
      <AppIcon :path="mdiShareVariant" :size="20" />
    </button>

    <Popover
      ref="popoverRef"
      :pt="{
        root: { class: 'share-overlay !p-0 !rounded-xl !shadow-2xl !min-w-52' },
        content: { class: '!p-1.5 !bg-transparent' },
      }"
    >
      <div class="flex flex-col gap-0.5">
        <button type="button" :class="menuItemClass" @click="onCopyLink">
          <AppIcon :path="mdiLinkVariant" :size="18" class="shrink-0" />
          {{ t('proposal.share.copyLink') }}
        </button>

        <!-- Real links, not click handlers: the browser's own mailto and
             external-app handling is better than anything scripted here. -->
        <a
          :href="mailtoHref(emailSubject, emailBody)"
          :class="menuItemClass"
          @click="popoverRef?.hide()"
        >
          <AppIcon :path="mdiEmailOutline" :size="18" class="shrink-0" />
          {{ t('proposal.share.email') }}
        </a>

        <a
          :href="whatsappHref(`${sentence} ${urls.shareUrl}`)"
          target="_blank"
          rel="noopener noreferrer"
          :class="menuItemClass"
          @click="popoverRef?.hide()"
        >
          <AppIcon :path="mdiWhatsapp" :size="18" class="shrink-0" />
          {{ t('proposal.share.whatsapp') }}
        </a>

        <!-- The only route to Signal, and the normal one on a phone. Absent on
             desktop Firefox, where the entries above are all there is. -->
        <button v-if="hasShareSheet" type="button" :class="menuItemClass" @click="onShareSheet">
          <AppIcon :path="mdiExportVariant" :size="18" class="shrink-0" />
          {{ t('proposal.share.more') }}
        </button>
      </div>
    </Popover>
  </div>
</template>

<style>
/* Unscoped on purpose, exactly as CountrySelect/StopSelect do it: the Popover
   is teleported out of this component, so a scoped selector never reaches it —
   and without an explicit surface it keeps the Lara theme's LIGHT panel, on
   which these light-on-dark item colours are invisible. */
.share-overlay {
  background: #23263d !important;
  border: 1px solid var(--p-primary-50) !important;
}
</style>
