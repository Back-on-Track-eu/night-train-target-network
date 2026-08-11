<script setup lang="ts">
import { onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useStore } from '@/stores/store'
import AppHeader from '@/components/AppHeader.vue'
import AuthModal from '@/components/AuthModal.vue'
import ToastContainer from '@/components/ToastContainer.vue'

const { t } = useI18n()
const store = useStore()

onMounted(() => {
  // Restore a remembered auth choice (sync, no network, no auto-guest) — a fresh
  // visitor stays 'none' until they choose. Then load the shared reference data
  // the gallery search bar and the viewport both need.
  store.restoreAuth()
  store.restoreLocale()
  store.fetchStops()
  store.fetchCompositions()
  store.fetchScenarios()
})
</script>

<template>
  <div class="flex min-h-screen flex-col bg-sapphire">
    <AppHeader />
    <div class="flex flex-1 flex-col items-center px-8 py-12">
      <h1 class="mb-10 text-center text-4xl font-light text-white">
        {{ t('proposal.heading') }}
      </h1>
      <router-view />
      <AuthModal v-if="store.authModal.open" />
    </div>
    <ToastContainer />
  </div>
</template>
