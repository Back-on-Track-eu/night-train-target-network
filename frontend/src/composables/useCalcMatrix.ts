// One calc matrix per (route, HOW fields, axes). Owns the request, the cells
// it returned and the lookups the comparison views ask for:
//
//   byScenario(compositionId)   → the bar chart (one composition across
//                                 scenarios)
//   byComposition(scenarioId)   → the supply table (one scenario across
//                                 compositions)
//   okCell(scenarioId, compId)  → one grid position
//
// The viewport runs TWO of these (see ProposalViewport.startMatrix):
//   - a `summary` grid over every offered scenario × every composition, which
//     feeds the comparison bars, the grid and the supply table;
//   - a `full` matrix over every offered scenario × the SELECTED composition,
//     whose cells carry route, views and parameters — enough to display a
//     scenario without asking the backend for anything. Switching scenario is
//     therefore instant and free; every cell of both matrices is also in the
//     backend's compute cache, so the calls that do remain are hits.
//
// Lifetime: started after a successful calc, keyed so recomputing the same
// route does not refetch, and reset the moment the itinerary is edited — the
// cells would describe a route that no longer exists.

import { computed, ref, shallowRef, type ComputedRef, type Ref } from 'vue'
import { calcMatrix } from '@/lib/proposalsApi'
import { asApiFailure, type ApiFailure } from '@/lib/apiError'
import { cellKey } from '@/lib/calcMatrix'
import type {
  MatrixCell,
  MatrixCellOk,
  MatrixDocument,
  MatrixRequest,
  MatrixStats,
} from '@/types/api'

export type MatrixStatus = 'idle' | 'loading' | 'complete' | 'partial' | 'error'

export interface CalcMatrix<TRoute = unknown> {
  status: Ref<MatrixStatus>
  document: Ref<MatrixDocument<TRoute> | null>
  stats: ComputedRef<MatrixStats | null>
  failure: Ref<ApiFailure | null>
  /** Cells of the last completed request, keyed by cellKey(). */
  cells: Ref<Map<string, MatrixCell<TRoute>>>
  received: ComputedRef<number>
  okCell(scenarioId: number, compositionId: string): MatrixCellOk<TRoute> | undefined
  byScenario(compositionId: string): Map<number, MatrixCell<TRoute>>
  byComposition(scenarioId: number): Map<string, MatrixCell<TRoute>>
  /** Fetch the grid for `body`; a no-op while the same key is in flight or
   *  already loaded. `key` identifies route + HOW fields + axes. */
  start(key: string, body: MatrixRequest, headers: Record<string, string>): void
  /** Re-run the last request (retry after a failure). */
  retry(): void
  abort(): void
  reset(): void
}

export function useCalcMatrix<TRoute = unknown>(): CalcMatrix<TRoute> {
  const status = ref<MatrixStatus>('idle')
  // shallowRef: the document is replaced wholesale, and deep-proxying dozens
  // of summary objects would cost more than it buys.
  const document = shallowRef<MatrixDocument<TRoute> | null>(null)
  const failure = ref<ApiFailure | null>(null)
  const cells = shallowRef(new Map<string, MatrixCell<TRoute>>())

  const received = computed(() => cells.value.size)
  const stats = computed(() => document.value?.stats ?? null)

  let controller: AbortController | null = null
  let currentKey: string | null = null
  let lastRequest: { body: MatrixRequest; headers: Record<string, string> } | null = null

  function abort() {
    controller?.abort()
    controller = null
  }

  function reset() {
    abort()
    currentKey = null
    lastRequest = null
    status.value = 'idle'
    document.value = null
    failure.value = null
    cells.value = new Map()
  }

  function run(body: MatrixRequest, headers: Record<string, string>) {
    abort()
    const own = new AbortController()
    controller = own
    status.value = 'loading'
    failure.value = null
    calcMatrix<TRoute>(body, headers, own.signal)
      .then((doc) => {
        if (own.signal.aborted) return
        document.value = doc
        const next = new Map<string, MatrixCell<TRoute>>()
        for (const cell of doc.cells) next.set(cellKey(cell.scenario_id, cell.composition_id), cell)
        cells.value = next
        // "partial" is not an error: on a deployment without one routing
        // instance, or a route one scenario cannot serve, the grid comes back
        // with error cells and the rest is still worth showing.
        status.value = doc.status === 'complete' && doc.stats.n_error === 0 ? 'complete' : 'partial'
      })
      .catch((err: unknown) => {
        if (own.signal.aborted) return
        const f = asApiFailure(err)
        if (f?.kind === 'canceled') return
        failure.value = f ?? { kind: 'network' }
        status.value = 'error'
      })
  }

  function start(key: string, body: MatrixRequest, headers: Record<string, string>) {
    // Same grid already in flight or in hand: nothing to do. A previous
    // FAILURE is not "in hand" — a new calc is a fair reason to try again.
    if (key === currentKey && status.value !== 'error' && status.value !== 'idle') return
    reset()
    currentKey = key
    lastRequest = { body, headers }
    run(body, headers)
  }

  function retry() {
    if (lastRequest) run(lastRequest.body, lastRequest.headers)
  }

  const okCell = (scenarioId: number, compositionId: string) => {
    const cell = cells.value.get(cellKey(scenarioId, compositionId))
    return cell?.status === 'ok' ? cell : undefined
  }

  function byScenario(compositionId: string): Map<number, MatrixCell<TRoute>> {
    const out = new Map<number, MatrixCell<TRoute>>()
    for (const c of cells.value.values()) {
      if (c.composition_id === compositionId) out.set(c.scenario_id, c)
    }
    return out
  }

  function byComposition(scenarioId: number): Map<string, MatrixCell<TRoute>> {
    const out = new Map<string, MatrixCell<TRoute>>()
    for (const c of cells.value.values()) {
      if (c.scenario_id === scenarioId) out.set(c.composition_id, c)
    }
    return out
  }

  return {
    status,
    document,
    stats,
    failure,
    cells,
    received,
    okCell,
    byScenario,
    byComposition,
    start,
    retry,
    abort,
    reset,
  }
}
