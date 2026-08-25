// Reactive mirror of lib/apiHealth's plain observable state, so the banner can
// read it without apiHealth (or apiClient) having to import vue.

import { onScopeDispose, shallowRef, type ShallowRef } from 'vue'
import { apiHealth, type ApiHealthState } from '@/lib/apiHealth'

export function useApiHealth(): {
  state: ShallowRef<ApiHealthState>
  dismiss: () => void
} {
  const state = shallowRef<ApiHealthState>(apiHealth.snapshot())
  const unsubscribe = apiHealth.subscribe((next) => {
    state.value = next
  })
  onScopeDispose(unsubscribe)
  return { state, dismiss: () => apiHealth.dismiss() }
}
