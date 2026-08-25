<script setup lang="ts">
// The proposal viewer's discussion thread, sitting under the evaluation.
//
// The thread itself is injected, not fetched: the like button in the map's
// action pill (MapShareBar) reads the same GET /engagements response, so
// ProposalViewport provides that state once and both consume it — see
// composables/useProposalEngagement.ts. What stays local to this component is
// everything the pill has no interest in: drafts, the inline editor, and the
// two-step delete.
//
// Every write returns the resulting row, so the thread is patched from
// responses rather than refetched. All the list/validation/timestamp logic
// lives in lib/commentThread.ts, where it is unit-testable.

import { computed, onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Textarea from 'primevue/textarea'
import AppIcon from '@/components/AppIcon.vue'
import AppSpinner from '@/components/AppSpinner.vue'
import { mdiPencilOutline, mdiTrashCanOutline } from '@mdi/js'
import { useStore } from '@/stores/store'
import { useApiFailure } from '@/composables/useApiFailure'
import { useProposalEngagement } from '@/composables/useProposalEngagement'
import { postComment, editComment, deleteComment } from '@/lib/proposalsApi'
import {
  applyDeleted,
  applyEdited,
  applyPosted,
  charsRemaining,
  commentAge,
  isOwnComment,
  validateBody,
  wasEdited,
} from '@/lib/commentThread'
import type { Comment } from '@/types/api'

const props = defineProps<{ proposalId: number }>()

const { t, locale } = useI18n()
const store = useStore()
const { describe, report } = useApiFailure()

// Shared with the map's action pill — including the reload-on-auth-change that
// keeps liked_by_me honest. The fetch and its abort slot live in the parent, so
// this component mounting and unmounting mid-load no longer costs a request.
const { comments, loadState, loadErrorMsg, canEngage, load } = useProposalEngagement()

// The header count comes from the local array, never from the response's
// `count`: after a post or delete the two would disagree until the next load.
const commentCount = computed(() => comments.value.length)

// Relative timestamps go stale while the page sits open. One shared clock,
// ticking a minute at a time — the finest granularity commentAge() reports.
const now = ref(new Date())
const clock = setInterval(() => (now.value = new Date()), 60_000)
onBeforeUnmount(() => clearInterval(clock))

function ageLabel(comment: Comment): string {
  const age = commentAge(comment.created_at, now.value)
  switch (age.unit) {
    case 'now':
      return t('proposal.comments.age.now')
    case 'minutes':
      return t('proposal.comments.age.minutes', age.value)
    case 'hours':
      return t('proposal.comments.age.hours', age.value)
    case 'days':
      return t('proposal.comments.age.days', age.value)
    case 'date':
      return new Date(comment.created_at).toLocaleDateString(locale.value, {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
      })
  }
}

// --- Compose ----------------------------------------------------------------

const draft = ref('')
const posting = ref(false)
const postErrorMsg = ref<string | null>(null)

const draftProblem = computed(() => validateBody(draft.value))
const draftRemaining = computed(() => charsRemaining(draft.value))
// The counter is noise on an empty box and only earns its place near the cap.
const showCounter = computed(() => draftRemaining.value <= 200)

async function onPost(): Promise<void> {
  if (draftProblem.value || posting.value) return
  posting.value = true
  postErrorMsg.value = null
  try {
    const posted = await postComment(props.proposalId, draft.value.trim(), store.authHeaders())
    comments.value = applyPosted(comments.value, posted)
    draft.value = ''
  } catch (err) {
    // Inline, next to the box the text is still sitting in — the draft is never
    // cleared on failure, so retrying costs nothing.
    if (!report(err, { fallbackKey: 'errors.commentFailed' })) {
      postErrorMsg.value = describe(err, 'errors.commentFailed')
    }
  } finally {
    posting.value = false
  }
}

// --- Edit -------------------------------------------------------------------

const editingId = ref<number | null>(null)
const editDraft = ref('')
const savingEdit = ref(false)
const editErrorMsg = ref<string | null>(null)

const editProblem = computed(() => validateBody(editDraft.value))

function startEdit(comment: Comment): void {
  confirmingDeleteId.value = null
  editingId.value = comment.comment_id
  editDraft.value = comment.body
  editErrorMsg.value = null
}

function cancelEdit(): void {
  editingId.value = null
  editDraft.value = ''
  editErrorMsg.value = null
}

async function onSaveEdit(comment: Comment): Promise<void> {
  if (editProblem.value || savingEdit.value) return
  savingEdit.value = true
  editErrorMsg.value = null
  try {
    const edited = await editComment(
      props.proposalId,
      comment.comment_id,
      editDraft.value.trim(),
      store.authHeaders(),
    )
    comments.value = applyEdited(comments.value, edited)
    cancelEdit()
  } catch (err) {
    if (!report(err, { fallbackKey: 'errors.commentFailed' })) {
      editErrorMsg.value = describe(err, 'errors.commentFailed')
    }
  } finally {
    savingEdit.value = false
  }
}

// --- Delete -----------------------------------------------------------------

// Two-step inline confirm rather than a modal or window.confirm: the row is
// small, the action is destructive, and a dialog for one comment is heavy.
const confirmingDeleteId = ref<number | null>(null)
const deletingId = ref<number | null>(null)

async function onDelete(comment: Comment): Promise<void> {
  if (deletingId.value !== null) return
  deletingId.value = comment.comment_id
  try {
    await deleteComment(props.proposalId, comment.comment_id, store.authHeaders())
    comments.value = applyDeleted(comments.value, comment.comment_id)
    confirmingDeleteId.value = null
  } catch (err) {
    // No inline slot survives the row it belonged to, so this one always toasts.
    report(err, { fallbackKey: 'errors.commentFailed', force: 'toast' })
  } finally {
    deletingId.value = null
  }
}

// resize-none, not resize-y: PrimeVue's auto-resize already grows the box with
// its content, and the two fighting over the height made the manual drag
// flicker. The handle was redundant as well as broken.
const inputClass =
  'w-full resize-none rounded-lg border border-primary-50/20 bg-primary-50/5 px-3 py-2 text-sm text-primary-50 placeholder:text-primary-50/40'
const primaryButtonClass =
  'flex cursor-pointer items-center gap-2 self-start rounded-lg bg-primary-500 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-primary-600 active:bg-primary-700 disabled:cursor-not-allowed disabled:bg-primary-500/40 disabled:text-white/60 disabled:shadow-none'
const quietButtonClass =
  'cursor-pointer rounded-lg px-3 py-2 text-sm text-primary-50/70 transition hover:bg-primary-50/10 hover:text-primary-50'
</script>

<template>
  <!-- Narrower than the panels above and centred: prose wants a short measure,
       and a comment stretched across the full 6xl workspace is hard to read. -->
  <section class="mx-auto flex w-full max-w-3xl flex-col gap-5 border-t border-primary-50/15 pt-8">
    <!-- Title + count only. The like button lives on the map now (MapShareBar),
         beside share: both are about the proposal as a whole, not about the
         discussion. -->
    <h3 class="text-lg font-semibold text-primary-50">
      {{ t('proposal.comments.title') }}
      <span v-if="commentCount > 0" class="font-normal text-primary-50/50">
        {{ commentCount }}
      </span>
    </h3>

    <!-- Load failed: the thread is unknown, so offer a retry rather than an
         empty state that would read as "no comments". -->
    <div v-if="loadState === 'error'" class="flex flex-wrap items-center gap-3">
      <span class="text-sm text-red-400" role="alert">
        {{ loadErrorMsg ?? t('errors.commentsLoadFailed') }}
      </span>
      <button type="button" :class="quietButtonClass" @click="load">
        {{ t('errors.retry') }}
      </button>
    </div>

    <!-- 'idle' means no proposal id yet, which this section is never mounted
         without — treated as loading rather than given a state of its own. -->
    <div v-else-if="loadState !== 'ready'" class="flex items-center gap-2 text-primary-50/60">
      <AppSpinner :size="18" />
      <span class="text-sm">{{ t('proposal.comments.loading') }}</span>
    </div>

    <template v-else>
      <p v-if="commentCount === 0" class="text-sm text-primary-50/50">
        {{ t('proposal.comments.empty') }}
      </p>

      <!-- Oldest first, as the server sends it: a discussion reads forwards. -->
      <ul v-else class="flex flex-col gap-4">
        <li
          v-for="comment in comments"
          :key="comment.comment_id"
          class="rounded-lg border border-primary-50/10 bg-primary-50/5 px-4 py-3"
        >
          <div class="flex items-baseline justify-between gap-3">
            <div class="flex flex-wrap items-baseline gap-2">
              <!-- user_name is "[deleted]" once the account is gone; the body
                   survives, which is the point of the soft reference. -->
              <span class="text-sm font-semibold text-primary-50">{{ comment.user_name }}</span>
              <span class="text-xs text-primary-50/40">{{ ageLabel(comment) }}</span>
              <span v-if="wasEdited(comment)" class="text-xs italic text-primary-50/30">
                {{ t('proposal.comments.edited') }}
              </span>
            </div>

            <!-- Own-comment controls. The server enforces authorship anyway
                 (403); this only decides whether to offer them. -->
            <div
              v-if="isOwnComment(comment, store.userId) && editingId !== comment.comment_id"
              class="flex shrink-0 items-center gap-1"
            >
              <template v-if="confirmingDeleteId === comment.comment_id">
                <span class="text-xs text-primary-50/60">{{
                  t('proposal.comments.deleteConfirm')
                }}</span>
                <button
                  type="button"
                  class="cursor-pointer rounded px-2 py-1 text-xs font-semibold text-red-400 transition hover:bg-red-400/10 disabled:cursor-not-allowed"
                  :disabled="deletingId === comment.comment_id"
                  @click="onDelete(comment)"
                >
                  {{ t('proposal.comments.deleteYes') }}
                </button>
                <button
                  type="button"
                  class="cursor-pointer rounded px-2 py-1 text-xs text-primary-50/60 transition hover:bg-primary-50/10 hover:text-primary-50"
                  @click="confirmingDeleteId = null"
                >
                  {{ t('proposal.comments.deleteNo') }}
                </button>
              </template>
              <template v-else>
                <button
                  type="button"
                  :aria-label="t('proposal.comments.edit')"
                  class="flex h-7 w-7 cursor-pointer items-center justify-center rounded text-primary-50/50 transition hover:bg-primary-50/10 hover:text-primary-50"
                  @click="startEdit(comment)"
                >
                  <AppIcon :path="mdiPencilOutline" :size="16" />
                </button>
                <button
                  type="button"
                  :aria-label="t('proposal.comments.delete')"
                  class="flex h-7 w-7 cursor-pointer items-center justify-center rounded text-primary-50/50 transition hover:bg-primary-50/10 hover:text-red-400"
                  @click="confirmingDeleteId = comment.comment_id"
                >
                  <AppIcon :path="mdiTrashCanOutline" :size="16" />
                </button>
              </template>
            </div>
          </div>

          <!-- Inline edit, in place of the body: the comment keeps its position
               in the thread while being rewritten. -->
          <div v-if="editingId === comment.comment_id" class="mt-2 flex flex-col gap-2">
            <Textarea v-model="editDraft" rows="3" auto-resize :class="inputClass" />
            <!-- Actions right-aligned under the box, message to their left.
                 ml-auto rather than justify-end so the message keeps the left
                 edge even when it is the only thing in the row. -->
            <div class="flex flex-wrap items-center gap-2">
              <span v-if="editErrorMsg" class="text-sm text-red-400" role="alert">
                {{ editErrorMsg }}
              </span>
              <div class="ml-auto flex items-center gap-2">
                <button type="button" :class="quietButtonClass" @click="cancelEdit">
                  {{ t('proposal.comments.cancel') }}
                </button>
                <button
                  type="button"
                  :class="primaryButtonClass"
                  :disabled="editProblem !== null || savingEdit"
                  @click="onSaveEdit(comment)"
                >
                  <AppSpinner v-if="savingEdit" />
                  {{ savingEdit ? t('proposal.comments.saving') : t('proposal.comments.save') }}
                </button>
              </div>
            </div>
          </div>

          <!-- whitespace-pre-wrap: the body is plain text (no markdown is
               rendered anywhere), so the author's own line breaks are all the
               structure there is. -->
          <p v-else class="mt-1.5 whitespace-pre-wrap break-words text-sm text-primary-50/85">
            {{ comment.body }}
          </p>
        </li>
      </ul>

      <!-- Composer, or the reason there isn't one. -->
      <div v-if="canEngage" class="flex flex-col gap-2">
        <Textarea
          v-model="draft"
          :placeholder="t('proposal.comments.placeholder')"
          :disabled="posting"
          rows="3"
          auto-resize
          :class="inputClass"
        />
        <!-- Post sits at the box's right edge; counter and error keep the left,
             where they read as annotations on the text rather than on the
             button. -->
        <div class="flex flex-wrap items-center gap-3">
          <span
            v-if="showCounter"
            class="text-xs"
            :class="draftRemaining < 0 ? 'text-red-400' : 'text-primary-50/50'"
          >
            {{
              draftRemaining < 0
                ? t('proposal.comments.charsOver', -draftRemaining)
                : t('proposal.comments.charsLeft', draftRemaining)
            }}
          </span>
          <span v-if="postErrorMsg" class="text-sm text-red-400" role="alert">
            {{ postErrorMsg }}
          </span>
          <button
            type="button"
            :class="`ml-auto ${primaryButtonClass}`"
            :disabled="draftProblem !== null || posting"
            @click="onPost"
          >
            <AppSpinner v-if="posting" />
            {{ posting ? t('proposal.comments.posting') : t('proposal.comments.post') }}
          </button>
        </div>
      </div>

      <div v-else class="flex flex-wrap items-center gap-3">
        <span class="text-sm text-primary-50/60">{{ t('proposal.comments.loginToComment') }}</span>
        <button
          type="button"
          :class="primaryButtonClass"
          @click="store.openAuthModal({ context: 'standalone' })"
        >
          {{ t('proposal.comments.login') }}
        </button>
      </div>
    </template>
  </section>
</template>
