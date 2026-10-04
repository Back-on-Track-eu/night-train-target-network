// Is the build running in this tab still the one the server serves?
//
// Vite names the entry bundle by content hash, and index.html is the one
// place that names it — so "the live index.html names a different
// index-*.js than the one that booted this page" is a complete test for
// "a deploy happened since this tab loaded (or the browser served a stale
// index.html)". Pure helpers here; the watch that acts on them is
// composables/useFreshBuild.ts.

const ENTRY_BUNDLE = /\/assets\/index-[\w-]+\.js/

/** The entry bundle an index.html names, or null when it names none. */
export function entryBundleOf(html: string): string | null {
  return html.match(ENTRY_BUNDLE)?.[0] ?? null
}

/** The entry bundle that booted this document — null on the dev server,
 *  which serves /src/main.ts instead, so the check is simply off there. */
export function runningEntryBundle(doc: Document): string | null {
  for (const script of doc.querySelectorAll<HTMLScriptElement>('script[type="module"][src]')) {
    const found = entryBundleOf(script.getAttribute('src') ?? '')
    if (found) return found
  }
  return null
}

/** The entry bundle the server names right now. `no-store` so neither the
 *  browser cache nor a proxy can answer for it — this request exists to
 *  bypass exactly those. */
export async function liveEntryBundle(): Promise<string | null> {
  const res = await fetch('/index.html', { cache: 'no-store', credentials: 'same-origin' })
  if (!res.ok) return null
  return entryBundleOf(await res.text())
}
