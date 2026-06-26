import { defineStore } from 'pinia'
import { ref } from 'vue'

export type LoadStatus = 'idle' | 'loading' | 'success' | 'error'

export const useDataStore = defineStore('data', () => {
  const status = ref<LoadStatus>('idle')
  const data = ref<Record<string, unknown> | null>(null)
  const errorMessage = ref<string | null>(null)

  async function loadData(): Promise<void> {
    status.value = 'loading'
    errorMessage.value = null

    try {
      const response = await fetch('http://localhost:5000/api/health')

      const json = await response.json()

      if (!response.ok) {
        status.value = 'error'
        errorMessage.value = `HTTP ${response.status}`
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
