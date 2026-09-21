<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { apiUrl } from '../lib/apiBase'

// The general feedback form — the whole content of /docs/feedback. Its
// per-page sibling, FeedbackForm.vue, asks about the page it sits on and
// therefore fixes category and sub_category; here the reader says what the
// feedback is about, so both are chosen, from the taxonomy the backend
// serves at GET /api/feedback/categories.
//
// IDENTITY. The backend takes a bearer token over anything the body claims
// and resolves the account's address itself (api/feedback.py), so "reply to
// my account address" means sending the token and no email — the form never
// needs to know the address. Only a registered account has one: a guest row
// is exactly a user row without an email, so a guest is asked for one like
// an anonymous reader.

const SUBJECT_MAX = 200
const QUERY_MAX = 120
// A route's input parameters, one per line (the app's routingFeedbackContext);
// the app caps at 1,500, this is the page's own ceiling for hand-made links.
const CONTEXT_MAX = 2_000
const AUTH_COOKIE = 'nt_auth'

/**
 * Deep links carry a short alias, not the protocol strings, so the taxonomy
 * wording can change on the backend without breaking a link someone has
 * already sent on — only this map moves with it. The app links here as
 *   ?topic=missing-stop&q=<what was typed>                (empty stop search)
 *   ?topic=composition                                    (gallery button)
 *   ?topic=routing|timetable&q=<A → B>&context=<inputs>   (map action pill)
 *   ?topic=<panel>&q=<panel · A → B>&context=<inputs>     (result panels)
 * `lead` opens the message: what the reader is asked to describe, or what
 * already happened.
 */
interface Topic {
  category: string
  subCategory: string
  subject: string
  lead: (query: string) => string
}
const TOPICS: Record<string, Topic> = {
  'missing-stop': {
    category: 'Route or timetable',
    subCategory: 'Missing stop / suggest new stop',
    subject: 'Missing stop',
    lead: (query) => (query ? `I searched the stop list for “${query}” and found nothing.` : ''),
  },
  composition: {
    category: 'Compositions',
    subCategory: 'Suggest a new composition',
    subject: 'New composition',
    // A form to fill rather than a question: what the catalogue needs to
    // seat, weigh and price a formation, in the order the calibration
    // records it (backend/models/compositions/calib/catalog).
    lead: () =>
      'I would like to suggest a train composition that is missing from the ' +
      'catalogue. What I know about it:\n\n' +
      'Name / example operator (a real train it resembles): \n' +
      'Locomotive (type, max speed, electric/multi-system): \n' +
      'Coaches, in order, with type and count (seat / couchette / sleeper / capsule / catering): \n' +
      'Places per class: \n' +
      'Total length (m) and mass (t): \n' +
      'Max speed (km/h) and whether it may use high-speed lines: \n' +
      'New build or refurbished, and the year: \n' +
      'Catering on board (dining car, trolley, none): \n' +
      'Purchase or lease price, if known, and its source: \n' +
      'Why this formation belongs in the target network: \n' +
      'Sources (links, documents): ',
  },
  routing: {
    category: 'Route or timetable',
    subCategory: 'Routing / track geometry',
    subject: 'Routing',
    lead: () =>
      'What looks wrong with this route? For example a detour, a line it avoids but ' +
      'should take, a border it should not cross, or a distance far from reality.',
  },
  timetable: {
    category: 'Route or timetable',
    subCategory: 'Schedule / timetable / frequency',
    subject: 'Timetable',
    lead: () =>
      'What looks wrong with this timetable? For example a departure or arrival at ' +
      'an unrealistic hour, a leg much faster or slower than reality, or the night ' +
      'falling on the wrong section.',
  },
  // The builder's result panels — one "report a problem" icon each. The
  // sub-categories are the backend's _RESULT_PANEL_SUB_CATEGORIES verbatim.
  ...resultPanels({
    kpis: ['Scenario and main figures', 'Main figures'],
    compare: ['Scenario comparison', 'Scenario comparison'],
    breakdown: ['Cost and revenue breakdown', 'Cost and revenue'],
    'details-demand': ['Details — Demand', 'Details / Demand'],
    'details-supply': ['Details — Supply', 'Details / Supply'],
    'details-operation': ['Details — Train operation', 'Details / Train operation'],
    'details-infrastructure': ['Details — Infrastructure', 'Details / Infrastructure'],
    'details-overhead': ['Details — Overhead', 'Details / Overhead'],
  }),
}

function resultPanels(panels: Record<string, [subCategory: string, subject: string]>) {
  const lead =
    'What looks wrong in this panel? Name the figure and, if you can, what you ' +
    'expected instead and why. The route and its inputs are attached below.'
  return Object.fromEntries(
    Object.entries(panels).map(([alias, [subCategory, subject]]) => [
      alias,
      { category: 'Evaluation — results / view', subCategory, subject, lead: () => lead },
    ]),
  )
}

interface SubCategory {
  parameter: string
  description: string | null
  group: string | null
}
interface Category {
  category: string
  sub_categories: SubCategory[]
}
interface StoredAuth {
  token: string
  is_guest: boolean
  display_name: string
}

const categories = ref<Category[]>([])
// 'error' is not a dead end: category and sub-category fall back to free text,
// which the endpoint accepts anyway — the list is guidance, not a validator.
const listState = ref<'loading' | 'ready' | 'error'>('loading')

const category = ref('')
const subCategory = ref('')
const subject = ref('')
const message = ref('')
const email = ref('')

const account = ref<StoredAuth | null>(null)
const useAccountAddress = ref(true)

const status = ref<'idle' | 'submitting' | 'success' | 'error'>('idle')
const errorMsg = ref('')

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

const signedIn = computed(() => account.value !== null && !account.value.is_guest)
const replyByAccount = computed(() => signedIn.value && useAccountAddress.value)

const subOptions = computed(
  () => categories.value.find((c) => c.category === category.value)?.sub_categories ?? [],
)
/** A select where the taxonomy has a list, a text field where it has none —
 *  Bug report, Feature request, Other and Documentation carry no list by
 *  design, and the endpoint still requires a non-empty sub_category. */
const subIsFreeText = computed(() => listState.value === 'error' || subOptions.value.length === 0)

const canSubmit = computed(
  () =>
    status.value !== 'submitting' &&
    category.value.trim().length > 0 &&
    subCategory.value.trim().length > 0 &&
    subject.value.trim().length > 0 &&
    message.value.trim().length > 0 &&
    (replyByAccount.value || EMAIL_RE.test(email.value.trim())),
)

function readAuthCookie(): StoredAuth | null {
  const entry = document.cookie.split('; ').find((c) => c.startsWith(`${AUTH_COOKIE}=`))
  if (!entry) return null
  try {
    const parsed = JSON.parse(decodeURIComponent(entry.slice(AUTH_COOKIE.length + 1)))
    return parsed && typeof parsed.token === 'string' && parsed.token ? parsed : null
  } catch {
    // A cookie we cannot read is no worse than no cookie: ask for an address.
    return null
  }
}

/** Changing the category invalidates the sub-category chosen under the old
 *  one — silently keeping it would post a pair the taxonomy does not have. */
function onCategoryChange() {
  subCategory.value = ''
}

async function loadCategories(preselected: string) {
  try {
    const resp = await fetch(apiUrl('/api/feedback/categories'))
    if (!resp.ok) throw new Error(String(resp.status))
    const body = (await resp.json()) as { categories: Category[] }
    categories.value = body.categories ?? []
    listState.value = 'ready'
    // Default to the first category only when the link did not name one.
    if (!category.value) category.value = categories.value[0]?.category ?? ''
    // A deep link's sub-category survives only if the list still offers it;
    // otherwise the reader picks, rather than posting a stale label.
    if (
      preselected &&
      !subOptions.value.some((s) => s.parameter === preselected) &&
      subOptions.value.length > 0
    ) {
      subCategory.value = ''
    }
  } catch {
    listState.value = 'error'
  }
}

onMounted(() => {
  account.value = readAuthCookie()

  const params = new URLSearchParams(window.location.search)
  const topic = TOPICS[params.get('topic') ?? '']
  const query = (params.get('q') ?? '').trim().slice(0, QUERY_MAX)
  const context = (params.get('context') ?? '').trim().slice(0, CONTEXT_MAX)
  if (topic) {
    category.value = topic.category
    subCategory.value = topic.subCategory
    subject.value = (query ? `${topic.subject}: ${query}` : topic.subject).slice(0, SUBJECT_MAX)
  }
  // The reader's words go first — the lead asks for them — and the context
  // the link carried sits below, labelled, so it reads as attached data.
  const lead = topic?.lead(query) ?? ''
  const parts = [lead ? `${lead}\n\n` : '', context ? `\n\n— What this is about —\n${context}` : '']
  message.value = parts.join('')

  loadCategories(topic?.subCategory ?? '')
})

async function submit() {
  if (!canSubmit.value) return
  status.value = 'submitting'
  errorMsg.value = ''
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (replyByAccount.value) headers.Authorization = `Bearer ${account.value!.token}`
  try {
    const resp = await fetch(apiUrl('/api/feedback'), {
      method: 'POST',
      headers,
      body: JSON.stringify({
        // With a token the backend overwrites this anyway; without one it is
        // the only way back to the reader.
        ...(replyByAccount.value ? {} : { email: email.value.trim() }),
        subject: subject.value.trim().slice(0, SUBJECT_MAX),
        category: category.value,
        sub_category: subCategory.value.trim(),
        message: message.value.trim(),
      }),
    })
    if (!resp.ok) {
      const body = await resp.json().catch(() => null)
      throw new Error(
        resp.status === 429
          ? 'Too many submissions from here just now — please try again in a few minutes.'
          : body?.message || `The feedback could not be sent (HTTP ${resp.status}).`,
      )
    }
    status.value = 'success'
    message.value = ''
    subject.value = ''
  } catch (err) {
    status.value = 'error'
    errorMsg.value = err instanceof Error ? err.message : 'The feedback could not be sent.'
  }
}
</script>

<template>
  <div class="general-feedback">
    <div v-if="status === 'success'" class="gf-ok">
      <p>Thank you — that reached the working group.</p>
      <p v-if="replyByAccount">We reply to the address on your account.</p>
      <p v-else>We reply to the address you gave.</p>
      <button class="gf-again" @click="status = 'idle'">Send another</button>
    </div>

    <template v-else>
      <div class="gf-row">
        <label class="gf-field">
          <span>What is this about?</span>
          <select
            v-if="listState === 'ready'"
            v-model="category"
            :disabled="status === 'submitting'"
            @change="onCategoryChange"
          >
            <option v-for="c in categories" :key="c.category" :value="c.category">
              {{ c.category }}
            </option>
          </select>
          <input
            v-else
            v-model="category"
            type="text"
            placeholder="e.g. Bug report"
            :disabled="listState === 'loading' || status === 'submitting'"
          />
        </label>

        <label class="gf-field">
          <span>More precisely</span>
          <select v-if="!subIsFreeText" v-model="subCategory" :disabled="status === 'submitting'">
            <option value="" disabled>Choose…</option>
            <option v-for="s in subOptions" :key="s.parameter" :value="s.parameter">
              {{ s.parameter }}
            </option>
          </select>
          <input
            v-else
            v-model="subCategory"
            type="text"
            placeholder="In a few words"
            :disabled="status === 'submitting'"
          />
        </label>
      </div>

      <p v-if="listState === 'error'" class="gf-note">
        The category list could not be loaded, so both fields are free text. Your feedback still
        reaches us.
      </p>

      <label class="gf-field">
        <span>Subject</span>
        <input
          v-model="subject"
          type="text"
          :maxlength="SUBJECT_MAX"
          placeholder="One line"
          :disabled="status === 'submitting'"
        />
      </label>

      <label class="gf-field">
        <span>Your message</span>
        <textarea v-model="message" rows="7" :disabled="status === 'submitting'" />
      </label>

      <div v-if="signedIn" class="gf-identity">
        <label class="gf-check">
          <input v-model="useAccountAddress" type="checkbox" :disabled="status === 'submitting'" />
          <span>Reply to the address on my account ({{ account!.display_name }})</span>
        </label>
        <input
          v-if="!useAccountAddress"
          v-model="email"
          type="email"
          placeholder="Reply to this address instead"
          :disabled="status === 'submitting'"
        />
      </div>
      <label v-else class="gf-field">
        <span>Your email, so we can reply</span>
        <input v-model="email" type="email" :disabled="status === 'submitting'" />
      </label>

      <div class="gf-actions">
        <button :disabled="!canSubmit" @click="submit">
          {{ status === 'submitting' ? 'Sending…' : 'Send feedback' }}
        </button>
        <span v-if="status === 'error'" class="gf-error">{{ errorMsg }}</span>
      </div>
    </template>
  </div>
</template>

<style scoped>
/* Deliberately the same tokens and shapes as FeedbackForm.vue — the two are
   one form in two placements, and a reader who has used the small one should
   recognise this. No card border here: this one IS the page. */
.general-feedback {
  margin-top: 2rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.gf-row {
  display: grid;
  gap: 1rem;
  grid-template-columns: 1fr;
}
@media (min-width: 640px) {
  .gf-row {
    grid-template-columns: 1fr 1fr;
  }
}
.gf-field {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 0.35rem;
}
.gf-field > span {
  color: var(--vp-c-text-2);
  font-size: 0.9rem;
}
.general-feedback select,
.general-feedback input[type='text'],
.general-feedback input[type='email'],
.general-feedback textarea {
  width: 100%;
  padding: 0.6rem 0.75rem;
  border: 1px solid var(--vp-c-divider);
  border-radius: 8px;
  background: var(--vp-c-bg);
  color: var(--vp-c-text-1);
  font: inherit;
  font-size: 0.95rem;
}
.gf-identity {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.gf-check {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  color: var(--vp-c-text-2);
  font-size: 0.9rem;
}
.gf-note {
  margin: 0;
  color: var(--vp-c-text-2);
  font-size: 0.9rem;
}
.gf-actions {
  display: flex;
  align-items: center;
  gap: 1rem;
  flex-wrap: wrap;
}
/* The app's one solid-CTA recipe, shared with FeedbackForm.vue. */
.general-feedback button {
  padding: 0.5rem 1.25rem;
  border-radius: 8px;
  background: var(--vp-button-brand-bg);
  color: var(--vp-button-brand-text);
  font-weight: 600;
  cursor: pointer;
  transition: background-color 0.15s ease;
}
.general-feedback button:hover:not(:disabled) {
  background: var(--vp-button-brand-hover-bg);
}
.general-feedback button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.gf-ok {
  color: var(--vp-c-text-1);
}
.gf-ok p {
  margin: 0 0 0.5rem;
}
.gf-again {
  margin-top: 0.5rem;
}
.gf-error {
  color: var(--vp-c-danger-1);
  font-size: 0.9rem;
}
</style>
