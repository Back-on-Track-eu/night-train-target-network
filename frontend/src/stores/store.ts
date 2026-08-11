import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type {
  Stop,
  Composition,
  Scenario,
  StopsResponse,
  CompositionsResponse,
  ScenariosResponse,
  GuestSessionResponse,
  VerifyResponse,
  VerifyNeedsNameResponse,
  StoredAuth,
} from '@/types/api'
import { readAuthCookie, writeAuthCookie, clearAuthCookie } from '@/lib/authCookie'
import { readLocale, writeLocale, type Locale } from '@/lib/localeStorage'
import { i18n } from '@/i18n'
import type { GallerySearchSeed } from '@/lib/proposalPrefill'

export type LoadStatus = 'idle' | 'loading' | 'success' | 'error'

// Same-origin by default in production builds (set VITE_API_BASE_URL='' and
// let the reverse proxy route /api/*); localhost fallback for bare local dev.
const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:5050'

export const useStore = defineStore('store', () => {
  const stops = ref<Stop[]>([])
  const stopsStatus = ref<LoadStatus>('idle')
  const stopsError = ref<string | null>(null)

  const compositions = ref<Composition[]>([])
  const compositionsStatus = ref<LoadStatus>('idle')
  const compositionsError = ref<string | null>(null)

  // Base + current scenarios only (historical/superseded are hidden). The
  // selected id threads into the merged proposal/calc call so routing and cost
  // always reflect one scenario.
  const scenarios = ref<Scenario[]>([])
  const scenariosStatus = ref<LoadStatus>('idle')
  const scenariosError = ref<string | null>(null)
  const selectedScenarioId = ref<number | null>(null)

  // Gallery's search-bar state at the moment "Suggest a new route" was
  // clicked, handed to ProposalWorkspace/ProposalViewport off-URL so a fresh
  // proposal's prefill doesn't leak into /proposal-builder's address bar.
  // Set right before the router.push to 'proposal-builder'; read once by
  // ProposalViewport's searchSeed prop.
  const pendingProposalSeed = ref<GallerySearchSeed | null>(null)

  // --- Auth ----------------------------------------------------------------
  // Identity is tri-state and DERIVED from the token (see authChoice): the app
  // never auto-creates a guest — a fresh visitor is 'none' until they choose.
  // The choice (logged in OR chosen-anonymous) is persisted in a cookie
  // (lib/authCookie.ts) and restored on boot via restoreAuth().
  const authToken = ref<string | null>(null)
  const isGuest = ref(false)
  const username = ref<string | null>(null)
  const userId = ref<number | null>(null)

  const authChoice = computed<'none' | 'guest' | 'user'>(() =>
    authToken.value ? (isGuest.value ? 'guest' : 'user') : 'none',
  )

  // Shared auth modal, rendered once in App.vue. ProposalViewport drives the
  // evaluation gate through openAuthModal/closeAuthModal; the user chip opens it
  // standalone.
  const authModal = ref<{
    open: boolean
    co2SavingsT: number | null
    context: 'evaluation' | 'standalone'
  }>({ open: false, co2SavingsT: null, context: 'standalone' })

  function openAuthModal(partial: Partial<Omit<typeof authModal.value, 'open'>>): void {
    authModal.value = { ...authModal.value, ...partial, open: true }
  }
  function closeAuthModal(): void {
    authModal.value = { ...authModal.value, open: false }
  }

  async function fetchStops(): Promise<void> {
    stopsStatus.value = 'loading'
    stopsError.value = null
    try {
      const response = await fetch(`${BASE_URL}/api/params/StopInfrastructures`)
      const json: StopsResponse = await response.json()
      if (!response.ok) {
        stopsStatus.value = 'error'
        stopsError.value = `HTTP ${response.status}`
      } else {
        stops.value = json.stops
        stopsStatus.value = 'success'
        console.log('[stops]', json.stops)
      }
    } catch (err) {
      stopsStatus.value = 'error'
      stopsError.value = err instanceof Error ? err.message : 'Unknown network error'
    }
  }

  async function fetchCompositions(): Promise<void> {
    compositionsStatus.value = 'loading'
    compositionsError.value = null
    try {
      const response = await fetch(`${BASE_URL}/api/params/compositions`)
      const json: CompositionsResponse = await response.json()
      if (!response.ok) {
        compositionsStatus.value = 'error'
        compositionsError.value = `HTTP ${response.status}`
      } else {
        compositions.value = json.compositions
        compositionsStatus.value = 'success'
        console.log('[compositions]', json.compositions)
      }
    } catch (err) {
      compositionsStatus.value = 'error'
      compositionsError.value = err instanceof Error ? err.message : 'Unknown network error'
    }
  }

  async function fetchScenarios(): Promise<void> {
    scenariosStatus.value = 'loading'
    scenariosError.value = null
    try {
      const response = await fetch(`${BASE_URL}/api/scenarios`)
      const json: ScenariosResponse = await response.json()
      if (!response.ok) {
        scenariosStatus.value = 'error'
        scenariosError.value = `HTTP ${response.status}`
      } else {
        // Base first, then the other current what-if scenarios.
        scenarios.value = [...json.current_base.scenarios, ...json.current_scenarios.scenarios]
        selectedScenarioId.value =
          scenarios.value.find((s) => s.is_current_base)?.scenario_id ??
          scenarios.value[0]?.scenario_id ??
          null
        scenariosStatus.value = 'success'
        console.log('[scenarios]', scenarios.value)
      }
    } catch (err) {
      scenariosStatus.value = 'error'
      scenariosError.value = err instanceof Error ? err.message : 'Unknown network error'
    }
  }

  // Apply an identity to the reactive state (no persistence — callers decide).
  function setAuth(a: StoredAuth): void {
    authToken.value = a.token
    isGuest.value = a.is_guest
    username.value = a.display_name
    userId.value = a.user_id
  }

  // Restore a remembered choice from the cookie — sync, no network, no
  // auto-guest. Called once on app boot (App.vue).
  function restoreAuth(): void {
    const stored = readAuthCookie()
    if (stored) setAuth(stored)
  }

  // Explicit anonymous choice: mint a guest identity and remember it. Throws on
  // failure so the modal can surface it.
  async function continueAsGuest(): Promise<void> {
    const response = await fetch(`${BASE_URL}/api/auth/guest`, { method: 'POST' })
    if (!response.ok) throw new Error(`guest session failed (HTTP ${response.status})`)
    const json: GuestSessionResponse = await response.json()
    const stored: StoredAuth = {
      token: json.token,
      is_guest: true,
      display_name: json.display_name,
      user_id: json.user_id,
    }
    setAuth(stored)
    writeAuthCookie(stored)
  }

  // Request an OTP (api/auth.py::request_code). The backend always answers 200
  // (no user-existence leak) EXCEPT a 400 when a new account is created without
  // a display name — surfaced as { needsUsername: true } so the modal reveals
  // the field and resends. Any other non-2xx throws.
  async function requestCode(email: string): Promise<void> {
    console.debug('[auth] request-code → POST /api/auth/request-code', { email })
    const response = await fetch(`${BASE_URL}/api/auth/request-code`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
    })
    console.debug('[auth] request-code ←', response.status)
    if (response.ok) {
      console.debug(
        '[auth] OTP accepted. If no email arrives, the backend is in AUTH_EMAIL_DEV_MODE — ' +
          'the 6-digit code is logged in the backend-api container, not emailed. ' +
          'See: docker compose -f .devcontainer/docker-compose.yml logs backend-api | grep OTP',
      )
      return
    }
    const json = await response.json().catch(() => ({}))
    console.debug('[auth] request-code error body:', json)
    throw new Error(json.message ?? `request failed (HTTP ${response.status})`)
  }

  // Verify the OTP -> JWT. Sends the CURRENT (guest) token so the backend merges
  // any prior guest work into the account (api/auth.py::verify()). Throws on a
  // bad/expired code.
  async function verifyCode(
    email: string,
    code: string,
    usernameInput?: string,
  ): Promise<{ needsUsername: boolean }> {
    console.debug('[auth] verify → POST /api/auth/verify', {
      email,
      codeLength: code.length,
      hasUsername: !!usernameInput,
    })
    const response = await fetch(`${BASE_URL}/api/auth/verify`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify(
        usernameInput ? { email, code, display_name: usernameInput } : { email, code },
      ),
    })
    console.debug('[auth] verify ←', response.status)
    const json = await response.json().catch(() => ({}))
    if (!response.ok) {
      console.debug('[auth] verify error body:', json)
      throw new Error(json.message ?? `verification failed (HTTP ${response.status})`)
    }
    // First-time registration: backend needs a display name before it issues
    // a token (code left unconsumed) — the caller shows the name step.
    if ((json as VerifyNeedsNameResponse).needs_display_name) {
      console.debug('[auth] verify: display name required (first-time registration)')
      return { needsUsername: true }
    }
    const v = json as VerifyResponse
    console.debug('[auth] verified — merged_guest:', v.merged_guest)
    const stored: StoredAuth = {
      token: v.token,
      is_guest: false,
      display_name: v.display_name,
      user_id: v.user_id,
    }
    setAuth(stored)
    writeAuthCookie(stored)
    return { needsUsername: false }
  }

  // Forget the choice: back to 'none'.
  function logout(): void {
    authToken.value = null
    isGuest.value = false
    username.value = null
    userId.value = null
    clearAuthCookie()
    closeAuthModal()
  }

  // Bearer header for authed endpoints; empty when 'none' (tokenless =
  // compute-only, nothing persists). Spread into a fetch headers object.
  function authHeaders(): Record<string, string> {
    return authToken.value ? { Authorization: `Bearer ${authToken.value}` } : {}
  }

  // --- Locale ----------------------------------------------------------------
  // Reuse vue-i18n's own reactive locale ref as the single source of truth
  // instead of duplicating it in a second ref.
  const locale = i18n.global.locale

  function setLocale(lang: Locale): void {
    locale.value = lang
    writeLocale(lang)
  }

  // Restore a remembered language — sync, no network. Called once on app boot
  // (App.vue), alongside restoreAuth().
  function restoreLocale(): void {
    const stored = readLocale()
    // Multi-language is disabled for now — the app runs in English only, even
    // if an earlier session persisted a different choice. The
    // setLocale/writeLocale machinery stays for when the LanguageSwitch is
    // re-enabled; drop this guard then.
    if (stored === 'en') locale.value = stored
  }

  return {
    stops,
    stopsStatus,
    stopsError,
    compositions,
    compositionsStatus,
    compositionsError,
    scenarios,
    scenariosStatus,
    scenariosError,
    selectedScenarioId,
    pendingProposalSeed,
    fetchStops,
    fetchCompositions,
    fetchScenarios,
    // auth
    authToken,
    isGuest,
    username,
    userId,
    authChoice,
    authModal,
    openAuthModal,
    closeAuthModal,
    restoreAuth,
    continueAsGuest,
    requestCode,
    verifyCode,
    logout,
    authHeaders,
    // locale
    locale,
    setLocale,
    restoreLocale,
  }
})
