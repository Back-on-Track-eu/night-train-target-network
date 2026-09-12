<script setup lang="ts">
import { ref, computed } from 'vue'
import { useData, useRoute } from 'vitepress'

// "Found a mistake?" — posts to the same POST /api/feedback the app uses.
// Same origin: the docs are served at /docs/ by the app's own nginx, so a
// relative /api/feedback needs no CORS and no configuration.
//
// category/sub_category are protocol values sent verbatim, not display
// text. sub_category is the page path, which is why the backend's
// Documentation category ships an empty sub_categories list: the page
// names live here, and the backend does not read docs-site/.
const FEEDBACK_CATEGORY = 'Documentation'
const SUBJECT_MAX = 200

const route = useRoute()
const { page } = useData()

const message = ref('')
const email = ref('')
const status = ref<'idle' | 'submitting' | 'success' | 'error'>('idle')
const errorMsg = ref('')

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
const emailValid = computed(() => EMAIL_RE.test(email.value.trim()))
const canSubmit = computed(
  () => emailValid.value && message.value.trim().length > 0 && status.value !== 'submitting',
)

// The page this was sent from, so a correction can be routed without the
// reporter having to describe where they were.
const pagePath = computed(() => route.path || '/')
const pageTitle = computed(() => page.value.title || pagePath.value)

async function submit() {
  if (!canSubmit.value) return
  status.value = 'submitting'
  errorMsg.value = ''
  try {
    const resp = await fetch('/api/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: email.value.trim(),
        subject: `Docs: ${pageTitle.value}`.slice(0, SUBJECT_MAX),
        category: FEEDBACK_CATEGORY,
        sub_category: pagePath.value,
        message: message.value.trim(),
      }),
    })
    if (!resp.ok) {
      // 429 is the endpoint's rate limit; everything else is a validation
      // or storage failure whose body may carry a usable message.
      const body = await resp.json().catch(() => null)
      throw new Error(
        resp.status === 429
          ? 'Too many submissions from here just now — please try again in a few minutes.'
          : body?.message || `The report could not be sent (HTTP ${resp.status}).`,
      )
    }
    status.value = 'success'
    message.value = ''
    email.value = ''
  } catch (err) {
    status.value = 'error'
    errorMsg.value = err instanceof Error ? err.message : 'The report could not be sent.'
  }
}
</script>

<template>
  <div class="feedback-form">
    <h2>Found a mistake?</h2>
    <p>
      This documentation describes a model that is still being built, and some of it will be wrong.
      If a number looks off, a source is missing, or an explanation does not hold up, tell us — it
      reaches the working group with the page you were reading.
    </p>

    <div v-if="status === 'success'" class="feedback-ok">
      Thank you — that reached the working group. We reply to the address you gave.
    </div>

    <template v-else>
      <textarea
        v-model="message"
        rows="4"
        placeholder="What is wrong, or what would make this clearer?"
        :disabled="status === 'submitting'"
      />
      <input
        v-model="email"
        type="email"
        placeholder="Your email, so we can reply"
        :disabled="status === 'submitting'"
      />
      <div class="feedback-actions">
        <button :disabled="!canSubmit" @click="submit">
          {{ status === 'submitting' ? 'Sending…' : 'Send' }}
        </button>
        <span v-if="status === 'error'" class="feedback-error">{{ errorMsg }}</span>
      </div>
    </template>
  </div>
</template>

<style scoped>
.feedback-form {
  margin-top: 3rem;
  padding: 1.5rem;
  border: 1px solid var(--vp-c-divider);
  border-radius: 12px;
  background: var(--vp-c-bg-soft);
}
.feedback-form h2 {
  margin: 0 0 0.5rem;
  border: none;
  padding: 0;
  font-size: 1.15rem;
}
.feedback-form p {
  margin: 0 0 1rem;
  color: var(--vp-c-text-2);
  font-size: 0.95rem;
}
.feedback-form textarea,
.feedback-form input {
  width: 100%;
  margin-bottom: 0.75rem;
  padding: 0.6rem 0.75rem;
  border: 1px solid var(--vp-c-divider);
  border-radius: 8px;
  background: var(--vp-c-bg);
  color: var(--vp-c-text-1);
  font: inherit;
  font-size: 0.95rem;
}
.feedback-actions {
  display: flex;
  align-items: center;
  gap: 1rem;
  flex-wrap: wrap;
}
/* The app's one solid-CTA recipe: primary-500 under white, darkening on
   hover — frontend/src/components/CommentSection.vue:180. brand-1 is link
   text here, not a fill, so it is deliberately not used. */
.feedback-form button {
  padding: 0.5rem 1.25rem;
  border-radius: 8px;
  background: var(--vp-button-brand-bg);
  color: var(--vp-button-brand-text);
  font-weight: 600;
  cursor: pointer;
  transition: background-color 0.15s ease;
}
.feedback-form button:hover:not(:disabled) {
  background: var(--vp-button-brand-hover-bg);
}
.feedback-form button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.feedback-ok {
  color: var(--vp-c-brand-1);
  font-weight: 500;
}
.feedback-error {
  color: var(--vp-c-danger-1);
  font-size: 0.9rem;
}
</style>
