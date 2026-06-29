<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import DataStatus from '@/components/DataStatus.vue'

const { t } = useI18n()
</script>

<template>
  <div class="min-h-screen bg-surface-50 p-8">
    <header class="mb-8 text-center">
      <h1 class="text-3xl font-bold text-primary-700">{{ t('app.title') }}</h1>
    </header>
    <main>
      <DataStatus />
    </main>
  </div>
</template>
