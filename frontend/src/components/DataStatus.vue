<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useDataStore } from '@/stores/dataStore'
import Button from 'primevue/button'
import Card from 'primevue/card'
import Message from 'primevue/message'

const { t } = useI18n()
const store = useDataStore()

const severityMap = {
  idle: 'secondary',
  loading: 'info',
  success: 'success',
  already_loaded: 'success',
  error: 'error',
} as const
</script>

<template>
  <Card class="mx-auto mt-8 w-full max-w-2xl">
    <template #title>{{ t('dataStatus.title') }}</template>
    <template #content>
      <div class="flex flex-col gap-4">
        <Message :severity="severityMap[store.status]">
          {{ t(`dataStatus.status.${store.status}`) }}
        </Message>

        <Button
          :label="t('dataStatus.loadButton')"
          :loading="store.status === 'loading'"
          :disabled="store.status === 'loading'"
          @click="store.loadData()"
        />

        <div v-if="store.data" class="mt-4">
          <p class="mb-2 text-sm font-semibold">{{ t('dataStatus.response') }}</p>
          <pre class="overflow-auto rounded bg-surface-100 p-3 text-xs">{{
            JSON.stringify(store.data, null, 2)
          }}</pre>
        </div>

        <p v-if="store.data?.loaded_at" class="text-sm text-surface-500">
          {{ t('dataStatus.loadedAt', { time: store.data.loaded_at }) }}
        </p>
      </div>
    </template>
  </Card>
</template>
