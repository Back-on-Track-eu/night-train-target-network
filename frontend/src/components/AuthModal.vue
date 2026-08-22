<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import { useStore } from '@/stores/store'
import { useToastStore } from '@/stores/toastStore'
import AppIcon from '@/components/AppIcon.vue'
import AppSpinner from '@/components/AppSpinner.vue'
import { useLocaleFormat } from '@/composables/useLocaleFormat'
import { useApiFailure } from '@/composables/useApiFailure'
import { mdiCheckCircle, mdiArrowRight, mdiClose } from '@mdi/js'

const { t } = useI18n()
const store = useStore()
const toastStore = useToastStore()
const { formatInt } = useLocaleFormat()
const { describe } = useApiFailure()

const modal = computed(() => store.authModal)
const isEvaluation = computed(() => modal.value.context === 'evaluation')
// The evaluation gate is a hard gate — it can only be left by choosing (guest
// or a completed login). Only the standalone (user-menu) opening is dismissable,
// so a guest who opened "Log in / register" isn't trapped.
const canDismiss = computed(() => modal.value.context === 'standalone')

// Step machine: email → (display name, only for brand-new accounts) → code.
type Step = 'email' | 'name' | 'code'
const step = ref<Step>('email')
const email = ref('')
const username = ref('')
const digits = ref<string[]>(['', '', '', '', '', ''])
const codeBoxes = ref<HTMLElement | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)

const code = computed(() => digits.value.join(''))
const canVerify = computed(() => /^\d{6}$/.test(code.value))

const headerText = computed(() => {
  if (step.value === 'code') return t('auth.verifyTitle')
  if (step.value === 'name') return t('auth.nameTitle')
  return isEvaluation.value ? t('auth.completed') : t('auth.loginTitle')
})
const showCheck = computed(() => isEvaluation.value && step.value === 'email')
// CO₂ + register blurb only on the first (email) step of an evaluation gate.
const co2Text = computed(() => {
  if (!isEvaluation.value || step.value !== 'email') return null
  const v = modal.value.co2SavingsT
  if (v == null) return null
  return t('auth.co2Savings', { value: formatInt(v) })
})
const showRegisterBlurb = computed(() => isEvaluation.value && step.value === 'email')
// "Continue as guest" only makes sense before any choice is made, and only on
// the evaluation gate (first proposal prompt) — opening "Log in / Register"
// from the user menu is an explicit choice to log in, not a guest fork.
const showGuestOption = computed(() => isEvaluation.value && store.authChoice === 'none')

function dismiss() {
  store.closeAuthModal()
}

// Failures stay INLINE here (rendered below the form) and are deliberately not
// also toasted: the user is looking straight at this modal, so a toast is a
// second copy of the same sentence — and keeping both was why three error
// strings existed twice in en.json. Successes still toast, because the modal
// closes and takes its own feedback with it.
//
// Every handler resets `loading` in a finally. The old code only cleared it on
// the failure paths and relied on App.vue unmounting the modal on success,
// which works today and breaks the moment the modal is kept mounted.

async function onGuest() {
  loading.value = true
  error.value = null
  try {
    await store.continueAsGuest()
    dismiss()
    toastStore.addToast('success', t('toast.guestSuccess'))
  } catch (e) {
    error.value = describe(e, 'errors.authGuestFailed')
  } finally {
    loading.value = false
  }
}

async function onEmailContinue() {
  if (!email.value.trim()) return
  loading.value = true
  error.value = null
  try {
    await store.requestCode(email.value.trim())
    step.value = 'code'
  } catch (e) {
    error.value = describe(e, 'errors.slug.email_failed')
  } finally {
    loading.value = false
  }
}

async function onVerify() {
  if (!canVerify.value) return
  loading.value = true
  error.value = null
  try {
    // First-time registration: the backend asks for a display name (code left
    // unconsumed) — advance to the name step, keeping the same code.
    const { needsUsername } = await store.verifyCode(email.value.trim(), code.value)
    if (needsUsername) {
      step.value = 'name'
      return
    }
    dismiss()
    toastStore.addToast('success', t('toast.loginSuccess'))
  } catch (e) {
    error.value = describe(e, 'errors.slug.invalid_code')
  } finally {
    loading.value = false
  }
}

async function onNameContinue() {
  if (!username.value.trim()) return
  loading.value = true
  error.value = null
  try {
    // Re-submit the same code together with the chosen name to complete
    // registration. A taken/invalid name throws with the backend message.
    const { needsUsername } = await store.verifyCode(
      email.value.trim(),
      code.value,
      username.value.trim(),
    )
    if (needsUsername) {
      error.value = t('auth.usernameRequired')
      return
    }
    dismiss()
    toastStore.addToast('success', t('toast.registerSuccess'))
  } catch (e) {
    error.value = describe(e, 'errors.slug.invalid_code')
  } finally {
    loading.value = false
  }
}

function backToEmail() {
  step.value = 'email'
  error.value = null
}

// --- Six-box code input --------------------------------------------------
function focusBox(i: number) {
  codeBoxes.value?.querySelectorAll('input')[i]?.focus()
}
function onDigitInput(i: number, e: Event) {
  const el = e.target as HTMLInputElement
  const v = el.value.replace(/\D/g, '')
  digits.value[i] = v ? v[v.length - 1] : ''
  el.value = digits.value[i]
  if (digits.value[i] && i < 5) focusBox(i + 1)
  if (canVerify.value) onVerify()
}
function onDigitKeydown(i: number, e: KeyboardEvent) {
  if (e.key === 'Backspace' && !digits.value[i] && i > 0) focusBox(i - 1)
}
function onDigitPaste(e: ClipboardEvent) {
  e.preventDefault()
  const text = (e.clipboardData?.getData('text') ?? '').replace(/\D/g, '').slice(0, 6)
  if (!text) return
  for (let i = 0; i < 6; i++) digits.value[i] = text[i] ?? ''
  focusBox(Math.min(text.length, 5))
  if (canVerify.value) onVerify()
}

// Reset + focus the first box whenever we land on the code step.
watch(
  () => step.value,
  async (s) => {
    if (s === 'code') {
      digits.value = ['', '', '', '', '', '']
      await nextTick()
      focusBox(0)
    }
  },
)
</script>

<template>
  <Teleport to="body">
    <div
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm"
      @click.self="canDismiss && dismiss()"
    >
      <div
        class="auth-card relative flex w-full max-w-xl flex-col overflow-hidden rounded-2xl shadow-2xl"
      >
        <button
          v-if="canDismiss"
          type="button"
          class="absolute right-4 top-4 cursor-pointer text-primary-50/50 transition hover:text-primary-50"
          :aria-label="t('auth.close')"
          @click="dismiss"
        >
          <AppIcon :path="mdiClose" :size="20" />
        </button>

        <div class="flex items-center gap-3 px-8 pb-2 pt-7">
          <AppIcon v-if="showCheck" :path="mdiCheckCircle" :size="28" color="var(--p-primary-50)" />
          <h2 class="text-2xl font-bold leading-tight text-primary-50">{{ headerText }}</h2>
        </div>

        <div class="flex flex-col gap-5 px-8 pb-8 pt-2">
          <p v-if="co2Text || showRegisterBlurb" class="text-sm leading-relaxed text-primary-50/80">
            <template v-if="co2Text">{{ co2Text }}</template
            >{{ t('auth.register') }}
          </p>

          <!-- Step: email + guest (two columns) -->
          <template v-if="step === 'email'">
            <div class="flex flex-col gap-5 sm:flex-row sm:items-stretch sm:gap-6">
              <!-- Left: e-mail + continue -->
              <div class="flex flex-1 flex-col gap-4">
                <div class="flex flex-col gap-1.5">
                  <label class="text-sm font-semibold text-primary-50">{{ t('auth.email') }}</label>
                  <input
                    v-model="email"
                    type="email"
                    autocomplete="email"
                    class="auth-input rounded-xl px-4 py-2.5 outline-none"
                    @keyup.enter="onEmailContinue"
                  />
                </div>
                <button
                  type="button"
                  :disabled="loading || !email.trim()"
                  class="auth-primary flex items-center justify-center gap-2 rounded-full px-6 py-2.5 text-sm"
                  @click="onEmailContinue"
                >
                  {{ t('auth.continue') }}
                  <AppSpinner v-if="loading" :size="16" />
                  <AppIcon v-else :path="mdiArrowRight" :size="16" />
                </button>
              </div>

              <!-- Right: OR + continue as guest, beside the whole left block.
                   Only shown on the evaluation gate — the user-menu login is an
                   explicit choice, not a guest fork. -->
              <div
                v-if="showGuestOption"
                class="flex flex-col items-center justify-center gap-3 sm:border-l sm:border-primary-50/15 sm:pl-6"
              >
                <span class="text-sm font-semibold text-primary-50/50">{{ t('auth.or') }}</span>
                <button
                  type="button"
                  :disabled="loading"
                  class="flex items-center gap-2 rounded-full border border-primary-50/30 px-6 py-2.5 text-sm text-primary-50 transition hover:bg-primary-50/10 disabled:opacity-50"
                  @click="onGuest"
                >
                  {{ t('auth.continueGuest') }}
                  <AppSpinner v-if="loading" :size="16" />
                  <AppIcon v-else :path="mdiArrowRight" :size="16" />
                </button>
              </div>
            </div>
          </template>

          <!-- Step: display name (new accounts only) -->
          <template v-else-if="step === 'name'">
            <div class="flex flex-col gap-1.5">
              <label class="text-sm font-semibold text-primary-50">{{ t('auth.username') }}</label>
              <input
                v-model="username"
                type="text"
                class="auth-input rounded-xl px-4 py-2.5 outline-none"
                @keyup.enter="onNameContinue"
              />
            </div>
            <div class="flex items-center justify-between">
              <button
                type="button"
                :disabled="loading"
                class="cursor-pointer text-sm text-primary-50/60 underline-offset-2 hover:underline"
                @click="backToEmail"
              >
                {{ t('auth.emailIncorrect') }}
              </button>
              <button
                type="button"
                :disabled="loading || !username.trim()"
                class="auth-primary flex items-center gap-2 rounded-full px-6 py-2.5 text-sm"
                @click="onNameContinue"
              >
                {{ t('auth.continue') }}
                <AppSpinner v-if="loading" :size="16" />
                <AppIcon v-else :path="mdiArrowRight" :size="16" />
              </button>
            </div>
          </template>

          <!-- Step: OTP code (six boxes) -->
          <template v-else>
            <p class="text-sm text-primary-50/70">{{ t('auth.codeSent', { email }) }}</p>
            <div ref="codeBoxes" class="flex justify-center gap-4" @paste="onDigitPaste">
              <input
                v-for="(d, i) in digits"
                :key="i"
                :value="d"
                inputmode="numeric"
                maxlength="1"
                autocomplete="one-time-code"
                class="auth-input h-14 w-full max-w-14 rounded-xl text-center text-2xl font-semibold outline-none"
                @input="onDigitInput(i, $event)"
                @keydown="onDigitKeydown(i, $event)"
              />
            </div>
            <div class="flex items-center justify-between">
              <button
                type="button"
                :disabled="loading"
                class="cursor-pointer text-sm text-primary-50/60 underline-offset-2 hover:underline"
                @click="backToEmail"
              >
                {{ t('auth.emailIncorrect') }}
              </button>
              <button
                type="button"
                :disabled="loading || !canVerify"
                class="auth-primary flex items-center gap-2 rounded-full px-6 py-2.5 text-sm"
                @click="onVerify"
              >
                {{ t('auth.verify') }}
                <AppSpinner v-if="loading" :size="16" />
                <AppIcon v-else :path="mdiArrowRight" :size="16" />
              </button>
            </div>
          </template>

          <p v-if="error" class="text-sm text-red-400" role="alert">{{ error }}</p>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.auth-card {
  background: #23263d;
  border: 1px solid var(--p-primary-50);
}
.auth-input {
  color: var(--p-primary-50);
  background: color-mix(in srgb, var(--p-primary-50) 6%, transparent);
  border: 1px solid color-mix(in srgb, var(--p-primary-50) 25%, transparent);
  transition: border-color 0.15s ease;
}
.auth-input:focus {
  border-color: var(--p-primary-50);
}
.auth-primary {
  cursor: pointer;
  font-weight: 600;
  color: #23263d;
  background: var(--p-primary-50);
  transition: opacity 0.15s ease;
}
.auth-primary:hover {
  opacity: 0.9;
}
.auth-primary:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}
</style>
