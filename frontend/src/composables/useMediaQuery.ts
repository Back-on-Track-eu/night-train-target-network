// A reactive answer to one CSS media query, for the few layout decisions that
// cannot live in a class: an observer's root, an inline height. Tailwind's
// breakpoints answer everything else, so the two must agree — hence the
// constants below rather than ad-hoc widths.

import { getCurrentInstance, onBeforeUnmount, readonly, ref, type Ref } from 'vue'

/** Tailwind's `lg` breakpoint — the width at which the gallery goes two-column. */
export const LG_MEDIA_QUERY = '(min-width: 64rem)'
/** Tailwind's `sm` breakpoint — below it the gallery's histogram draws at phone scale. */
export const SM_MEDIA_QUERY = '(min-width: 40rem)'

export function useMediaQuery(query: string): Readonly<Ref<boolean>> {
  const matches = ref(false)
  // SSR and the node test runner have no window; the answer is then "no",
  // which every caller treats as the narrow (stacked) layout.
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return readonly(matches)
  }

  const list = window.matchMedia(query)
  matches.value = list.matches
  const onChange = (event: MediaQueryListEvent) => {
    matches.value = event.matches
  }
  list.addEventListener('change', onChange)
  if (getCurrentInstance()) {
    onBeforeUnmount(() => list.removeEventListener('change', onChange))
  }

  return readonly(matches)
}
