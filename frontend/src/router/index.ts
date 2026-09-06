import { createRouter, createWebHistory, START_LOCATION } from 'vue-router'
import Gallery from '@/components/Gallery.vue'
import ProposalWorkspace from '@/components/ProposalWorkspace.vue'

// Route map — see the "Routing (frontend)" note in AGENTS.md for why
// proposal-builder and proposal/:id share one component instance.
export const router = createRouter({
  history: createWebHistory(),
  // Back/forward returns to where the user actually was. This matters most for
  // the gallery: it is kept alive (App.vue), so returning from a proposal
  // restores the card list intact — landing at the top of a list the user was
  // fifteen cards into would undo most of that benefit.
  scrollBehavior: (to, from, savedPosition) => {
    // A reload or a fresh load arrives with from === START_LOCATION. The
    // browser preserves a scroll offset in history.state across a reload, so
    // without this the gallery reopens halfway down at the map instead of at
    // its hero — the page's intended entry point.
    if (from === START_LOCATION) return { top: 0 }
    if (savedPosition) return savedPosition
    // A query-only change on the same route is not navigation. The gallery
    // reflects its whole search bar into the query string (Gallery.vue's
    // currentSearchQuery), so without this every filter tweak, sort change or
    // mode switch scrolled the reader back to the top of the page.
    if (to.path === from.path) return false
    return { top: 0 }
  },
  routes: [
    { path: '/', redirect: '/gallery' },
    { path: '/gallery', name: 'gallery', component: Gallery },
    { path: '/proposal-builder', name: 'proposal-builder', component: ProposalWorkspace },
    { path: '/proposal/:id', name: 'proposal', component: ProposalWorkspace },
    { path: '/:pathMatch(.*)*', redirect: '/gallery' },
  ],
})
