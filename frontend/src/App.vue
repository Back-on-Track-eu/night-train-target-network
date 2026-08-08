<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useStore } from '@/stores/store'
import Gallery from '@/components/Gallery.vue'
import ProposalViewport from '@/components/ProposalViewport.vue'
import UserMenu from '@/components/UserMenu.vue'
import AuthModal from '@/components/AuthModal.vue'

const { t } = useI18n()
const store = useStore()

const view = ref<'gallery' | 'viewport'>('gallery')

onMounted(() => {
  // Restore a remembered auth choice (sync, no network, no auto-guest) — a fresh
  // visitor stays 'none' until they choose. Then load the shared reference data
  // the gallery search bar and the viewport both need.
  store.restoreAuth()
  store.fetchStops()
  store.fetchCompositions()
  store.fetchScenarios()
})
</script>

<template>
  <div class="flex min-h-screen flex-col items-center bg-sapphire px-8 py-12">
    <UserMenu v-if="store.authChoice !== 'none'" class="fixed right-8 top-6 z-40" />
    <h1 class="mb-10 text-center text-4xl font-light text-white">
      {{ t('proposal.heading') }}
    </h1>
    <Gallery v-if="view === 'gallery'" class="w-full max-w-6xl" @create="view = 'viewport'" />
    <ProposalViewport v-else mode="edit" class="w-full max-w-6xl" @back="view = 'gallery'" />
    <AuthModal v-if="store.authModal.open" />
  </div>
</template>
