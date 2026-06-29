<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import ProposalViewport from '@/components/ProposalViewport.vue'

const { t } = useI18n()
</script>

<template>
  <div class="flex min-h-screen flex-col items-center bg-sapphire px-8 py-12">
    <h1 class="mb-10 text-center text-4xl font-light text-white">
      {{ t('proposal.heading') }}
    </h1>
    <ProposalViewport mode="edit" class="w-full max-w-6xl" />
  </div>
</template>
