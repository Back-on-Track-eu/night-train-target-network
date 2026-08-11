// The single source of PERSISTED auth. One cookie `nt_auth` carries the JWT plus
// the display fields the UI needs, so a returning user is restored on boot with
// no network round-trip. It is JS-readable by necessity — the SPA must attach the
// token as a `Bearer` header (the same trust model as the rest of the app), so
// this is a convenience store, not a secret vault.
import Cookies from 'js-cookie'
import type { StoredAuth } from '@/types/api'

const COOKIE = 'nt_auth'
// 30 days — matches the guest token's server-side TTL (backend/api/auth.py).
const MAX_AGE_DAYS = 30

export function readAuthCookie(): StoredAuth | null {
  const raw = Cookies.get(COOKIE)
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw) as StoredAuth
    // A cookie without a token is meaningless — treat it as no choice.
    return parsed && typeof parsed.token === 'string' && parsed.token ? parsed : null
  } catch {
    return null
  }
}

export function writeAuthCookie(auth: StoredAuth): void {
  Cookies.set(COOKIE, JSON.stringify(auth), {
    expires: MAX_AGE_DAYS,
    sameSite: 'lax',
    path: '/',
    // Only mark Secure over HTTPS so it still works on plain-HTTP local dev.
    secure: location.protocol === 'https:',
  })
}

export function clearAuthCookie(): void {
  Cookies.remove(COOKIE, { path: '/' })
}
