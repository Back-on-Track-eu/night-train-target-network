// One proposal's engagement state — likes and the comment thread — shared by
// every part of the viewer that shows it.
//
// Two consumers exist: the like button in the map's action pill (MapShareBar)
// and the discussion thread (CommentSection). They read the same
// GET /engagements response, so this is provided ONCE by ProposalViewport and
// injected by both. A plain composable called twice would give each its own
// state: two identical requests per page open, and two like counts free to
// disagree the moment one of them is clicked.
//
// Deliberately not a module-level singleton keyed by proposal id — that state
// would outlive the page visit — and deliberately not props/emits through
// ProposalViewport, which is already ~2100 lines.
//
// Living in the parent has a second benefit: the fetch no longer hangs off a
// conditionally-mounted child. CommentSection used to mount, unmount and
// remount while a stored proposal loaded (display -> loading -> display),
// firing the request twice and aborting the first.

import {
  computed,
  inject,
  onBeforeUnmount,
  onMounted,
  provide,
  ref,
  watch,
  type ComputedRef,
  type InjectionKey,
  type Ref,
} from 'vue'
import { useStore } from '@/stores/store'
import { useApiFailure } from '@/composables/useApiFailure'
import { createAbortSlot } from '@/lib/apiClient'
import { asApiFailure } from '@/lib/apiError'
import { fetchEngagements, likeProposal, unlikeProposal } from '@/lib/proposalsApi'
import type { Comment, LikeResponse } from '@/types/api'

export interface ProposalEngagement {
  comments: Ref<Comment[]>
  likes: Ref<LikeResponse>
  loadState: Ref<'idle' | 'loading' | 'ready' | 'error'>
  loadErrorMsg: Ref<string | null>
  likeBusy: Ref<boolean>
  /** Whether the current visitor may like or comment — see canEngage below. */
  canEngage: ComputedRef<boolean>
  load: () => Promise<void>
  toggleLike: () => Promise<void>
}

const ENGAGEMENT_KEY: InjectionKey<ProposalEngagement> = Symbol('proposalEngagement')

/**
 * Create the state and make it available to descendants. Call once, from the
 * component that owns the proposal (ProposalViewport).
 *
 * proposalId is null until a proposal has been published or loaded; nothing is
 * fetched while it is.
 */
export function provideProposalEngagement(proposalId: Ref<number | null>): ProposalEngagement {
  const store = useStore()
  const { describe, report } = useApiFailure()

  const comments = ref<Comment[]>([])
  const likes = ref<LikeResponse>({ count: 0, liked_by_me: false })
  const loadState = ref<'idle' | 'loading' | 'ready' | 'error'>('idle')
  const loadErrorMsg = ref<string | null>(null)
  const likeBusy = ref(false)

  // Engaging needs a REGISTERED account, not merely a token — the same bar the
  // gallery's like button sets, even though the API's floor is a guest token. A
  // public thread attached to a throwaway identity is a moderation problem, and
  // there are no moderation tools.
  const canEngage = computed(() => store.authChoice === 'user')

  const loadSlot = createAbortSlot()

  async function load(): Promise<void> {
    const id = proposalId.value
    if (id === null) {
      loadState.value = 'idle'
      return
    }
    loadState.value = 'loading'
    loadErrorMsg.value = null
    try {
      // Auth headers even though the endpoint is open: without them the server
      // cannot say whether THIS user liked the proposal.
      const json = await fetchEngagements(id, store.authHeaders(), loadSlot.begin())
      comments.value = json.comments.items
      likes.value = json.likes
      loadState.value = 'ready'
    } catch (err) {
      // A superseded/unmounted load is not a failure and must not paint an error.
      if (asApiFailure(err)?.kind === 'canceled') return
      loadState.value = 'error'
      if (!report(err, { fallbackKey: 'errors.commentsLoadFailed' })) {
        loadErrorMsg.value = describe(err, 'errors.commentsLoadFailed')
      }
    }
  }

  async function toggleLike(): Promise<void> {
    if (!canEngage.value) {
      store.openAuthModal({ context: 'standalone' })
      return
    }
    const id = proposalId.value
    if (id === null || likeBusy.value) return
    likeBusy.value = true
    try {
      likes.value = likes.value.liked_by_me
        ? await unlikeProposal(id, store.authHeaders())
        : await likeProposal(id, store.authHeaders())
    } catch (err) {
      report(err, { fallbackKey: 'errors.likeFailed', force: 'toast' })
    } finally {
      likeBusy.value = false
    }
  }

  onMounted(load)
  // The id appears (first publish) or changes under us when router.replace()
  // patches this instance rather than remounting it — see AGENTS.md on why
  // /proposal-builder and /proposal/:id share one component.
  watch(proposalId, load)
  // Identity changes make `liked_by_me` stale, so the thread has to be re-read.
  // This is not only the login/logout case: App.vue restores the remembered
  // token in ITS onMounted, which Vue runs AFTER every child's, so on a page
  // load the first fetch above genuinely goes out unauthenticated and comes
  // back with liked_by_me false. Without this watch a reload shows a liked
  // proposal as unliked — exactly the bug the gallery card has to live with.
  watch(() => store.authToken, load)
  onBeforeUnmount(() => loadSlot.cancel())

  const engagement: ProposalEngagement = {
    comments,
    likes,
    loadState,
    loadErrorMsg,
    likeBusy,
    canEngage,
    load,
    toggleLike,
  }
  provide(ENGAGEMENT_KEY, engagement)
  return engagement
}

/** Read the provided state. Throws rather than silently returning empty
 *  state — a consumer mounted outside ProposalViewport is a wiring bug, and
 *  an always-zero like count is the kind of thing that ships unnoticed. */
export function useProposalEngagement(): ProposalEngagement {
  const engagement = inject(ENGAGEMENT_KEY, null)
  if (engagement === null) {
    throw new Error(
      'useProposalEngagement() needs an ancestor calling provideProposalEngagement().',
    )
  }
  return engagement
}
