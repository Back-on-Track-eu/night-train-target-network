import { defineStore } from 'pinia'
import { ref } from 'vue'
import type {
  Stop,
  Composition,
  Scenario,
  StopsResponse,
  CompositionsResponse,
  ScenariosResponse,
} from '@/types/api'

export type LoadStatus = 'idle' | 'loading' | 'success' | 'error'

// Same-origin by default in production builds (set VITE_API_BASE_URL='' and
// let the reverse proxy route /api/*); localhost fallback for bare local dev.
const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:5050'

export const useStore = defineStore('store', () => {
  const stops = ref<Stop[]>([])
  const stopsStatus = ref<LoadStatus>('idle')
  const stopsError = ref<string | null>(null)

  const compositions = ref<Composition[]>([])
  const compositionsStatus = ref<LoadStatus>('idle')
  const compositionsError = ref<string | null>(null)

  // Base + current scenarios only (historical/superseded are hidden). The
  // selected id threads into the merged proposal/calc call so routing and cost
  // always reflect one scenario.
  const scenarios = ref<Scenario[]>([])
  const scenariosStatus = ref<LoadStatus>('idle')
  const scenariosError = ref<string | null>(null)
  const selectedScenarioId = ref<number | null>(null)

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

  async function fetchScenarios(): Promise<void> {
    scenariosStatus.value = 'loading'
    scenariosError.value = null
    try {
      const response = await fetch(`${BASE_URL}/api/scenarios`)
      const json: ScenariosResponse = await response.json()
      if (!response.ok) {
        scenariosStatus.value = 'error'
        scenariosError.value = `HTTP ${response.status}`
      } else {
        // Base first, then the other current what-if scenarios.
        scenarios.value = [...json.current_base.scenarios, ...json.current_scenarios.scenarios]
        selectedScenarioId.value =
          scenarios.value.find((s) => s.is_current_base)?.scenario_id ??
          scenarios.value[0]?.scenario_id ??
          null
        scenariosStatus.value = 'success'
        console.log('[scenarios]', scenarios.value)
      }
    } catch (err) {
      scenariosStatus.value = 'error'
      scenariosError.value = err instanceof Error ? err.message : 'Unknown network error'
    }
  }

  return {
    stops,
    stopsStatus,
    stopsError,
    compositions,
    compositionsStatus,
    compositionsError,
    scenarios,
    scenariosStatus,
    scenariosError,
    selectedScenarioId,
    fetchStops,
    fetchCompositions,
    fetchScenarios,
  }
})
