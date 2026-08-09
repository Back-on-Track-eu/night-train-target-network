// Shared pass-through styling for unstyled PrimeVue Selects rendered as a
// pill (rounded-full, hairline border) — used across the evaluation panel's
// cube/scenario dropdowns and the trip selector in ProposalViewport.vue.
export const selectPillPt = {
  root: {
    class:
      'flex cursor-pointer items-center rounded-full border border-primary-50/20 bg-transparent transition hover:bg-primary-50/10',
  },
  label: { class: 'px-3 py-1.5 text-sm text-primary-50 leading-none' },
  dropdown: { class: 'flex items-center pr-3 text-primary-50/60' },
  overlay: {
    class:
      'z-50 mt-1 overflow-hidden rounded-xl border border-primary-50/20 bg-sapphire-100 shadow-xl',
  },
  listContainer: { class: 'overflow-auto' },
  option: {
    class: 'cursor-pointer px-4 py-2 text-sm text-primary-50 transition hover:bg-primary-50/10',
  },
}
