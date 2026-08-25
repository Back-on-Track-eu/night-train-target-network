// Share-menu plumbing for one proposal: which URLs to hand out, which facts to
// put in the message, and how to encode both into a channel's URL scheme.
//
// Pure by design (the src/lib-only vitest convention): these return data and
// hrefs, never wording. The component supplies the copy through t(), so the
// message follows the reader's locale — the backend's Open Graph card cannot,
// which is why its description is one fixed line.
//
// What the platforms actually allow, since it is not obvious:
//   - Copy link and e-mail (mailto:) are universal.
//   - WhatsApp takes prefilled text through https://wa.me/?text=.
//   - SIGNAL HAS NO URL SCHEME for prefilled text — signal.me links only
//     address a contact. Signal is reachable exclusively as an OS share-sheet
//     target via navigator.share(), which is why the menu offers a sheet entry
//     rather than a Signal button.
//   - The preview image is NOT passed in any of these URLs. WhatsApp and Signal
//     fetch the shared link from the sender's own device and read its Open Graph
//     tags — which is what /api/proposal/<id>/share exists to answer.

/** Both URLs a proposal has, and why there are two. */
export interface ShareUrls {
  /** The clean canonical URL. Goes on the clipboard, because this is what
   *  people paste into documents, tickets and the wiki. */
  appUrl: string
  /** The Open Graph stub. Goes to the chat channels, because only this URL
   *  answers a crawler with per-proposal tags. */
  shareUrl: string
}

function trimTrailingSlash(origin: string): string {
  return origin.replace(/\/+$/, '')
}

/**
 * appOrigin: where the SPA is served (window.location.origin).
 * apiOrigin: where /api/* is answered — API_BASE_URL, which is '' in a
 *   production build (same origin, Caddy routes the prefix) and an explicit
 *   http://localhost:5050 in bare local dev. Empty falls back to appOrigin, so
 *   the share URL is reachable in both.
 */
export function buildShareUrls(
  proposalId: number,
  appOrigin: string,
  apiOrigin: string,
): ShareUrls {
  const app = trimTrailingSlash(appOrigin)
  const api = trimTrailingSlash(apiOrigin) || app
  return {
    appUrl: `${app}/proposal/${proposalId}`,
    shareUrl: `${api}/api/proposal/${proposalId}/share`,
  }
}

/** The real, computed figures a shared message may quote. */
export interface RouteFacts {
  km: number
  stops: number
  countries: number
}

/** Only the fields routeFacts() reads, so ProposalViewport's BackendRoute
 *  satisfies it structurally without exporting that interface. */
export interface ShareRouteInput {
  trip_pairs: {
    outbound: {
      general_parameters: { trip_km: number }
      segments: unknown[]
    }
  }[]
  track_infrastructure: { country_code: string }[]
}

/**
 * Headline figures for the share message, from the calc payload the viewport
 * already holds — no extra request. Null when there is no route yet, and the
 * caller falls back to copy that quotes nothing.
 *
 * Never derive anything here from the summary block's co2_savings_t_per_year or
 * demand_* fields: demand_kpis_placeholder is TRUE, those numbers are
 * deterministic fakes, and a forwarded message is exactly where a placeholder
 * gets read as fact. Distance, stop count and countries are real.
 */
export function routeFacts(route: ShareRouteInput | null): RouteFacts | null {
  const outbound = route?.trip_pairs[0]?.outbound
  if (!outbound) return null
  return {
    km: Math.round(outbound.general_parameters.trip_km),
    // Segments are the legs between stops, so a 2-stop route has one.
    stops: outbound.segments.length + 1,
    countries: new Set(route.track_infrastructure.map((c) => c.country_code)).size,
  }
}

/**
 * mailto: with a prefilled subject and body. Plain text only — no HTML, no
 * image — and the body's newlines survive as %0A. Long bodies are truncated by
 * some clients around 2000 characters, so keep the copy short.
 */
export function mailtoHref(subject: string, body: string): string {
  return `mailto:?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`
}

/** wa.me opens the app on mobile and WhatsApp Web on desktop, with the text
 *  prefilled and a contact picker — it never names a recipient itself. */
export function whatsappHref(text: string): string {
  return `https://wa.me/?text=${encodeURIComponent(text)}`
}

/** Whether this browser can hand off to the OS share sheet — the only route to
 *  Signal, and the normal one on phones and macOS Safari. Absent on desktop
 *  Firefox, so the explicit channel buttons are never optional. */
export function canUseShareSheet(): boolean {
  return typeof navigator !== 'undefined' && typeof navigator.share === 'function'
}
