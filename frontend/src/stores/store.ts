import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type {
  Stop,
  Composition,
  CompositionCatalog,
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
import { apiRequest } from '@/lib/apiClient'
import { asApiFailure, type ApiFailure } from '@/lib/apiError'

export type LoadStatus = 'idle' | 'loading' | 'success' | 'error'

export const useStore = defineStore('store', () => {
  // Reference data carries the classified ApiFailure rather than a string, so
  // each consumer can choose its own copy (and offer Retry) instead of being
  // handed a bare "HTTP 503" — or, worse, a JSON-parser message, which is what
  // these used to produce for an empty-bodied 502 from the proxy.
  const stops = ref<Stop[]>([])
  const stopsStatus = ref<LoadStatus>('idle')
  const stopsFailure = ref<ApiFailure | null>(null)

  const compositions = ref<Composition[]>([])
  // Everything the same response carries alongside them — coach types,
  // classes, operators, field documentation and sources. Kept because the
  // composition detail overlay resolves a formation against it.
  const compositionCatalog = ref<CompositionCatalog>({
    operators: [],
    classes: {},
    coach_types: {},
    descriptions: { compositions: {}, operators: {} },
    sources: {},
  })
  const compositionsStatus = ref<LoadStatus>('idle')
  const compositionsFailure = ref<ApiFailure | null>(null)

  // Base + current scenarios only (historical/superseded are hidden). The
  // selected id threads into the merged proposal/calc call so routing and cost
  // always reflect one scenario.
  const scenarios = ref<Scenario[]>([])
  const scenariosStatus = ref<LoadStatus>('idle')
  const scenariosFailure = ref<ApiFailure | null>(null)
  const selectedScenarioId = ref<number | null>(null)

  // Gallery's search-bar state at the moment "Suggest a new route" was
  // clicked, handed to ProposalWorkspace/ProposalViewport off-URL so a fresh
  // proposal's prefill doesn't leak into /proposal-builder's address bar.
  // Set right before the router.push to 'proposal-builder'; read once by
  // ProposalViewport's searchSeed prop.
  const pendingProposalSeed = ref<GallerySearchSeed | null>(null)

  // The gallery is kept alive across navigation (App.vue), so its loaded list
  // survives a trip into a proposal and back — which also means a proposal
  // published in between would be missing from it. Publishing sets this; the
  // gallery refetches once on re-activation and clears it. Plain
  // back-navigation leaves it false and issues no requests at all.
  const galleryStale = ref(false)

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
    stopsFailure.value = null
    try {
      const json = await apiRequest<StopsResponse>('/api/params/StopInfrastructures', {
        budget: 'reference',
      })
      stops.value = json.stops
      stopsStatus.value = 'success'
    } catch (err) {
      stopsStatus.value = 'error'
      stopsFailure.value = asApiFailure(err)
    }
  }

  async function fetchCompositions(): Promise<void> {
    compositionsStatus.value = 'loading'
    compositionsFailure.value = null
    try {
      const json = await apiRequest<CompositionsResponse>('/api/params/compositions', {
        budget: 'reference',
      })
      compositions.value = json.compositions
      compositionCatalog.value = {
        operators: json.operators,
        classes: json.classes,
        coach_types: json.coach_types,
        descriptions: json.descriptions,
        sources: json.sources,
      }
      compositionsStatus.value = 'success'
    } catch (err) {
      compositionsStatus.value = 'error'
      compositionsFailure.value = asApiFailure(err)
    }
  }

  async function fetchScenarios(): Promise<void> {
    scenariosStatus.value = 'loading'
    scenariosFailure.value = null
    try {
      const json = await apiRequest<ScenariosResponse>('/api/scenarios', { budget: 'reference' })
      // Base first, then the other current what-if scenarios.
      scenarios.value = [...json.current_base.scenarios, ...json.current_scenarios.scenarios]
      selectedScenarioId.value =
        scenarios.value.find((s) => s.is_current_base)?.scenario_id ??
        scenarios.value[0]?.scenario_id ??
        null
      scenariosStatus.value = 'success'
    } catch (err) {
      scenariosStatus.value = 'error'
      // Consumers MUST surface this: with no scenario loaded, selectedScenarioId
      // stays null and the calc silently runs against the live base instead of
      // the scenario the user thinks is selected. ComputeInputsPanel says so.
      scenariosFailure.value = asApiFailure(err)
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

  // The three auth calls pass countsTowardOutage: false — a mistyped code or a
  // rate-limited OTP request is the user's own flow, not evidence the backend is
  // unwell, and must not arm the degraded banner.
  const AUTH_OPTS = { method: 'POST', countsTowardOutage: false } as const

  // Explicit anonymous choice: mint a guest identity and remember it. Throws an
  // ApiError on failure so the modal can classify it.
  async function continueAsGuest(): Promise<void> {
    const json = await apiRequest<GuestSessionResponse>('/api/auth/guest', AUTH_OPTS)
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
    await apiRequest('/api/auth/request-code', { ...AUTH_OPTS, body: { email } })
    console.debug(
      '[auth] OTP accepted. If no email arrives, the backend is in AUTH_EMAIL_DEV_MODE — ' +
        'the 6-digit code is logged in the backend-api container, not emailed. ' +
        'See: docker compose -f .devcontainer/docker-compose.yml logs backend-api | grep OTP',
    )
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
    const json = await apiRequest<VerifyResponse | VerifyNeedsNameResponse>('/api/auth/verify', {
      ...AUTH_OPTS,
      headers: authHeaders(),
      body: usernameInput ? { email, code, display_name: usernameInput } : { email, code },
    })
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
    stopsFailure,
    compositions,
    compositionCatalog,
    compositionsStatus,
    compositionsFailure,
    scenarios,
    scenariosStatus,
    scenariosFailure,
    selectedScenarioId,
    pendingProposalSeed,
    galleryStale,
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
