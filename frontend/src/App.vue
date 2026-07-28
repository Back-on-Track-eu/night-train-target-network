<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useStore } from '@/stores/store'
import Gallery from '@/components/Gallery.vue'
import ProposalViewport from '@/components/ProposalViewport.vue'

const { t } = useI18n()
const store = useStore()

const view = ref<'gallery' | 'viewport'>('gallery')

onMounted(async () => {
  // Guest stopgap: acquire an identity first so persist-on-calc saves what the
  // viewport plans/evaluates. Then load the shared reference data the gallery
  // search bar and the viewport both need — this used to live in
  // ProposalViewport.onMounted, which no longer runs at app startup.
  await store.initGuestSession()
  await store.fetchStops()
  store.fetchCompositions()
  store.fetchScenarios()
})
</script>

<template>
  <div class="flex min-h-screen flex-col items-center bg-sapphire px-8 py-12">
    <h1 class="mb-10 text-center text-4xl font-light text-white">
      {{ t('proposal.heading') }}
    </h1>
    <Gallery v-if="view === 'gallery'" class="w-full max-w-6xl" @create="view = 'viewport'" />
    <ProposalViewport v-else mode="edit" class="w-full max-w-6xl" @back="view = 'gallery'" />
  </div>
</template>
