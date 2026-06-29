import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { Stop, Composition, StopsResponse, CompositionsResponse } from '@/types/api'

export type LoadStatus = 'idle' | 'loading' | 'success' | 'error'

const BASE_URL = 'http://localhost:5000'

export const useStore = defineStore('store', () => {
  const stops = ref<Stop[]>([])
  const stopsStatus = ref<LoadStatus>('idle')
  const stopsError = ref<string | null>(null)

  const compositions = ref<Composition[]>([])
  const compositionsStatus = ref<LoadStatus>('idle')
  const compositionsError = ref<string | null>(null)

  async function fetchStops(): Promise<void> {
    stopsStatus.value = 'loading'
    stopsError.value = null
    try {
      const response = await fetch(`${BASE_URL}/api/params/StopInfrastructures`)
      const json: StopsResponse = await response.json()
      if (!response.ok) {
        stopsStatus.value = 'error'
        stopsError.value = `HTTP ${response.status}`
      } else {
        stops.value = json.stops
        stopsStatus.value = 'success'
        console.log('[stops]', json.stops)
      }
    } catch (err) {
      stopsStatus.value = 'error'
      stopsError.value = err instanceof Error ? err.message : 'Unknown network error'
    }
  }

  async function fetchCompositions(): Promise<void> {
    compositionsStatus.value = 'loading'
    compositionsError.value = null
    try {
      const response = await fetch(`${BASE_URL}/api/params/compositions`)
      const json: CompositionsResponse = await response.json()
      if (!response.ok) {
        compositionsStatus.value = 'error'
        compositionsError.value = `HTTP ${response.status}`
      } else {
        compositions.value = json.compositions
        compositionsStatus.value = 'success'
        console.log('[compositions]', json.compositions)
      }
    } catch (err) {
      compositionsStatus.value = 'error'
      compositionsError.value = err instanceof Error ? err.message : 'Unknown network error'
    }
  }

  return {
    stops,
    stopsStatus,
    stopsError,
    compositions,
    compositionsStatus,
    compositionsError,
    fetchStops,
    fetchCompositions,
  }
})
