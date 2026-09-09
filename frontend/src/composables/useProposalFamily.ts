// The proposal family on the client: one document per stop list + HOW,
// every scenario variant × composition in it, and one member's views fetched
// on demand. Replaces the two useCalcMatrix instances the viewport used to
// run (a summary grid and a full-detail scenario grid) — the document is both.
//
// Ownership: the viewport starts a family after every evaluation and resets
// it when the itinerary is edited (its members would describe a route that no
// longer exists). The results components read members through the same
// query surface the matrix cells had — okMember/byScenario/byComposition —
// keyed by SCENARIO id, because that is what the switches and the grid
// already work in; the document's scenario_variant_id is mapped through its
// own axes.
//
// Views are separate on purpose: the document carries every member's summary
// and route but no evaluation views (they are ~700 KB each, and a visitor
// opens one or two). views() fetches a member's on first use and caches it
// per family key; the viewport clears calcResult.views while one is in
// flight so zone E shows its skeleton rather than the previous member's
// figures.

import { computed, ref, shallowRef, type ComputedRef, type Ref } from 'vue'
import { fetchFamilyViews, postFamily } from '@/lib/proposalsApi'
import { asApiFailure, type ApiFailure } from '@/lib/apiError'
import { memberKey } from '@/lib/proposalFamily'
import type {
  EvaluationViews,
  FamilyDocument,
  FamilyMember,
  FamilyMemberOk,
  FamilyRequest,
  ScenarioVariant,
} from '@/types/api'

export type FamilyStatus = 'idle' | 'loading' | 'complete' | 'partial' | 'error'

export interface ProposalFamily {
  status: Ref<FamilyStatus>
  document: Ref<FamilyDocument | null>
  failure: Ref<ApiFailure | null>
  /** Members of the loaded document, keyed by memberKey(). */
  members: Ref<Map<string, FamilyMember>>
  /** The same members keyed `${scenario_id}:${composition_id}` — the key the
   *  combination grid works in. */
  cells: ComputedRef<Map<string, FamilyMember>>
  /** Members received so far — the document's, once it is here. */
  received: ComputedRef<number>
  /** scenario_id → its variant on the document's axis (one per scenario
   *  while one measure set is seeded). */
  variantOf: ComputedRef<Map<number, ScenarioVariant>>
  okMember(scenarioId: number, compositionId: string): FamilyMemberOk | undefined
  member(scenarioId: number, compositionId: string): FamilyMember | undefined
  byScenario(compositionId: string): Map<number, FamilyMember>
  byComposition(scenarioId: number): Map<string, FamilyMember>
  /** Build (or fetch from the document cache) the family for `body`. A no-op
   *  while the same key is in flight or loaded; `key` names stops + HOW +
   *  axes. Resolves to the document, or null on failure / cancellation. */
  start(
    key: string,
    body: FamilyRequest,
    headers: Record<string, string>,
    onSlow?: (phase: 'slow' | 'verySlow') => void,
  ): Promise<FamilyDocument | null>
  /** One member's six views, fetched once per family and cached. */
  views(scenarioId: number, compositionId: string): Promise<EvaluationViews | null>
  retry(): void
  abort(): void
  reset(): void
}

export function useProposalFamily(): ProposalFamily {
  const status = ref<FamilyStatus>('idle')
  const document = shallowRef<FamilyDocument | null>(null)
  const failure = ref<ApiFailure | null>(null)
  const members = shallowRef(new Map<string, FamilyMember>())
  const viewsCache = new Map<string, EvaluationViews>()

  let controller: AbortController | null = null
  let currentKey: string | null = null
  let lastRequest: {
    body: FamilyRequest
    headers: Record<string, string>
    onSlow?: (phase: 'slow' | 'verySlow') => void
  } | null = null

  const variantOf = computed(() => {
    const out = new Map<number, ScenarioVariant>()
    for (const v of document.value?.axes.scenario_variants ?? []) {
      // First variant per scenario wins — the base measure set, as the
      // backend orders the axis.
      if (!out.has(v.scenario_id)) out.set(v.scenario_id, v)
    }
    return out
  })

  const cells = computed(() => {
    const out = new Map<string, FamilyMember>()
    for (const m of members.value.values()) {
      const scenarioId = scenarioIdOf(m.scenario_variant_id)
      if (scenarioId !== undefined) out.set(`${scenarioId}:${m.composition_id}`, m)
    }
    return out
  })
  const received = computed(() => members.value.size)

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
    members.value = new Map()
    viewsCache.clear()
  }

  function run(
    body: FamilyRequest,
    headers: Record<string, string>,
    onSlow?: (phase: 'slow' | 'verySlow') => void,
  ): Promise<FamilyDocument | null> {
    abort()
    const own = new AbortController()
    controller = own
    status.value = 'loading'
    failure.value = null
    return postFamily(body, headers, own.signal, onSlow)
      .then((doc) => {
        if (own.signal.aborted) return null
        document.value = doc
        const next = new Map<string, FamilyMember>()
        for (const m of doc.members) next.set(memberKey(m.scenario_variant_id, m.composition_id), m)
        members.value = next
        status.value = doc.stats.n_error === 0 ? 'complete' : 'partial'
        return doc
      })
      .catch((err: unknown) => {
        if (own.signal.aborted) return null
        const f = asApiFailure(err)
        if (f?.kind === 'canceled') return null
        failure.value = f ?? { kind: 'network' }
        status.value = 'error'
        return null
      })
  }

  function start(
    key: string,
    body: FamilyRequest,
    headers: Record<string, string>,
    onSlow?: (phase: 'slow' | 'verySlow') => void,
  ): Promise<FamilyDocument | null> {
    if (key === currentKey && status.value !== 'error' && status.value !== 'idle') {
      return Promise.resolve(document.value)
    }
    reset()
    currentKey = key
    lastRequest = { body, headers, onSlow }
    return run(body, headers, onSlow)
  }

  function retry() {
    if (lastRequest) run(lastRequest.body, lastRequest.headers, lastRequest.onSlow)
  }

  function member(scenarioId: number, compositionId: string): FamilyMember | undefined {
    const variant = variantOf.value.get(scenarioId)
    if (!variant) return undefined
    return members.value.get(memberKey(variant.scenario_variant_id, compositionId))
  }

  function okMember(scenarioId: number, compositionId: string): FamilyMemberOk | undefined {
    const m = member(scenarioId, compositionId)
    return m?.status === 'ok' ? m : undefined
  }

  function scenarioIdOf(scenarioVariantId: number): number | undefined {
    for (const v of document.value?.axes.scenario_variants ?? []) {
      if (v.scenario_variant_id === scenarioVariantId) return v.scenario_id
    }
    return undefined
  }

  function byScenario(compositionId: string): Map<number, FamilyMember> {
    const out = new Map<number, FamilyMember>()
    for (const m of members.value.values()) {
      if (m.composition_id !== compositionId) continue
      const scenarioId = scenarioIdOf(m.scenario_variant_id)
      // One entry per scenario: the first variant is the base measure set.
      if (scenarioId !== undefined && !out.has(scenarioId)) out.set(scenarioId, m)
    }
    return out
  }

  function byComposition(scenarioId: number): Map<string, FamilyMember> {
    const variant = variantOf.value.get(scenarioId)
    const out = new Map<string, FamilyMember>()
    if (!variant) return out
    for (const m of members.value.values()) {
      if (m.scenario_variant_id === variant.scenario_variant_id) out.set(m.composition_id, m)
    }
    return out
  }

  async function views(scenarioId: number, compositionId: string): Promise<EvaluationViews | null> {
    const doc = document.value
    const variant = variantOf.value.get(scenarioId)
    if (!doc || !variant) return null
    const key = memberKey(variant.scenario_variant_id, compositionId)
    const cached = viewsCache.get(key)
    if (cached) return cached
    try {
      const resp = await fetchFamilyViews(
        doc.family_key,
        variant.scenario_variant_id,
        compositionId,
      )
      // The family may have been reset while the fetch was out; a stale
      // answer must not land in a newer family's cache.
      if (document.value !== doc) return null
      viewsCache.set(key, resp.views)
      return resp.views
    } catch (err) {
      if (asApiFailure(err)?.kind === 'canceled') return null
      throw err
    }
  }

  return {
    status,
    document,
    failure,
    members,
    cells,
    received,
    variantOf,
    okMember,
    member,
    byScenario,
    byComposition,
    start,
    views,
    retry,
    abort,
    reset,
  }
}
