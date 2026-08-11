<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useStore } from '@/stores/store'
import ProposalViewport from '@/components/ProposalViewport.vue'

// Registered for BOTH /proposal-builder and /proposal/:id (router/index.ts) —
// deliberately the same component instance for both routes, so a post-publish
// router.replace between them patches in place instead of remounting
// ProposalViewport and losing its just-computed state. See the "Routing
// (frontend)" note in AGENTS.md.
const route = useRoute()
const router = useRouter()
const store = useStore()

const proposalId = computed(() => (route.params.id ? Number(route.params.id) : null))
const mode = computed(() => (proposalId.value !== null ? 'display' : 'edit'))
// Off-URL prefill seed set by Gallery's createProposal() just before the push
// here — see store.pendingProposalSeed. Falls back to null (defaultPair's two
// random major stops) for a directly-opened /proposal-builder.
const searchSeed = computed(() => (mode.value === 'edit' ? store.pendingProposalSeed : null))

function onPublished(id: number) {
  if (route.name !== 'proposal') router.replace({ name: 'proposal', params: { id } })
}
</script>

<template>
  <ProposalViewport
    :mode="mode"
    :proposal-id="proposalId"
    :search-seed="searchSeed"
    class="w-full max-w-6xl"
    @back="router.push({ name: 'gallery' })"
    @published="onPublished"
  />
</template>
