import { createRouter, createWebHistory } from 'vue-router'
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
  scrollBehavior: (_to, _from, savedPosition) => savedPosition ?? { top: 0 },
  routes: [
    { path: '/', redirect: '/gallery' },
    { path: '/gallery', name: 'gallery', component: Gallery },
    { path: '/proposal-builder', name: 'proposal-builder', component: ProposalWorkspace },
    { path: '/proposal/:id', name: 'proposal', component: ProposalWorkspace },
    { path: '/:pathMatch(.*)*', redirect: '/gallery' },
  ],
})
