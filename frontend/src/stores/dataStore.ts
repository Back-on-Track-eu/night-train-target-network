import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { DataLoadResponse } from '@/types/api'

export type LoadStatus = 'idle' | 'loading' | 'success' | 'already_loaded' | 'error'

export const useDataStore = defineStore('data', () => {
  const status = ref<LoadStatus>('idle')
  const data = ref<DataLoadResponse | null>(null)
  const errorMessage = ref<string | null>(null)

  async function loadData(): Promise<void> {
    status.value = 'loading'
    errorMessage.value = null

    try {
      const response = await fetch('http://localhost:5000/api/data/load', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      })

      const json: DataLoadResponse = await response.json()

      if (response.status === 409) {
        status.value = 'already_loaded'
        data.value = json
      } else if (!response.ok) {
        status.value = 'error'
        errorMessage.value = json.message ?? `HTTP ${response.status}`
      } else {
        status.value = 'success'
        data.value = json
      }
    } catch (err) {
      status.value = 'error'
      errorMessage.value = err instanceof Error ? err.message : 'Unknown network error'
    }
  }

  return { status, data, errorMessage, loadData }
})
