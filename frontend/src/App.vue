<script setup lang="ts">
import { onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useStore } from '@/stores/store'
import AppHeader from '@/components/AppHeader.vue'
import AuthModal from '@/components/AuthModal.vue'
import ToastContainer from '@/components/ToastContainer.vue'
import ApiStatusBanner from '@/components/ApiStatusBanner.vue'

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
    <ApiStatusBanner />
    <div class="flex flex-1 flex-col items-center px-8 py-12">
      <h1 class="mb-10 text-center text-4xl font-light text-white">
        {{ t('proposal.heading') }}
      </h1>
      <!-- Gallery only. Opening a proposal used to UNMOUNT the gallery, throwing
           away the loaded pages, the pagination offset and every per-card route
           geometry — so coming straight back re-ran the whole query plus one
           GET /api/proposal/<id> per card. Keeping it alive makes that
           round trip free instead of merely faster.
           ProposalWorkspace is deliberately NOT cached: the publish flow does
           router.replace() and depends on Vue Router patching that live
           instance (see the "Routing (frontend)" note in AGENTS.md).
           `include` matches the component name Vue infers from Gallery.vue's
           filename — renaming that file silently disables the cache. -->
      <router-view v-slot="{ Component }">
        <keep-alive :include="['Gallery']">
          <component :is="Component" />
        </keep-alive>
      </router-view>
    </div>
    <!-- Shared app-level overlays live OUTSIDE the routed subtree: a modal owned
         by the store has no business sitting among the route's own children,
         where route churn and keep-alive activation can reach it. The `v-if`
         stays — AuthModal has no internal visibility guard, so without it the
         overlay would render permanently. -->
    <AuthModal v-if="store.authModal.open" />
    <ToastContainer />
  </div>
</template>
