import type { LocationQuery } from 'vue-router'

// Where /gallery opens. The landing pitch sits above the gallery proper, and
// it is the right first screen for someone arriving at the site itself — the
// origin root redirects to /gallery. Everyone else came for the gallery: a
// link that carries a filter (a station, a country, a range, a scenario), the
// "back" pill of a proposal, the "visit the gallery" buttons of the docs
// site. Those land scrolled to the search bar and the map (Gallery.vue's
// scrollToGallery) — decided 2026-10-04.
//
// The two signals: the hash below on an in-app or docs link that names no
// filter, and any filter key in the query. Gallery.vue writes its whole
// search bar into the query after mount, so the keys that are ALWAYS there
// (tab, kind, sort, dir) say nothing about how the reader arrived: a reload
// of a plain /gallery still opens on the pitch.
export const GALLERY_HASH = '#gallery'

const ALWAYS_PRESENT = new Set(['tab', 'kind', 'sort', 'dir'])

export function queryNamesAFilter(query: LocationQuery): boolean {
  return Object.keys(query).some((key) => !ALWAYS_PRESENT.has(key))
}

export function entersAtGallery(hash: string, query: LocationQuery): boolean {
  return hash === GALLERY_HASH || queryNamesAFilter(query)
}
