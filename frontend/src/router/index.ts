import { createRouter, createWebHistory } from 'vue-router'
import Gallery from '@/components/Gallery.vue'
import ProposalWorkspace from '@/components/ProposalWorkspace.vue'

// Route map — see the "Routing (frontend)" note in AGENTS.md for why
// proposal-builder and proposal/:id share one component instance.
export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/gallery' },
    { path: '/gallery', name: 'gallery', component: Gallery },
    { path: '/proposal-builder', name: 'proposal-builder', component: ProposalWorkspace },
    { path: '/proposal/:id', name: 'proposal', component: ProposalWorkspace },
    { path: '/:pathMatch(.*)*', redirect: '/gallery' },
  ],
})
