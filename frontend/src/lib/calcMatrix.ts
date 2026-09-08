// POST /api/proposal/calc/matrix on the client side: reading the NDJSON
// stream record by record, folding records into the document shape, and
// re-inlining the "full" detail's shared references. Pure functions over the
// types in types/api.ts — the request itself lives in lib/proposalsApi.ts
// (calcMatrix) and the state in composables/useCalcMatrix.ts.
//
// Stream framing: one JSON record per line, `\n`-terminated, never gzipped
// (the backend keeps application/x-ndjson out of Flask-Compress), so the
// reader is a byte stream → TextDecoder → split on `\n` → JSON.parse per
// complete line. A trailing partial line is carried over between chunks.

import type {
  MatrixCell,
  MatrixCellOk,
  MatrixDocument,
  MatrixHeader,
  MatrixRecord,
  MatrixStats,
  ProposalCalcResponse,
  SharedKind,
} from '@/types/api'

/** Split a chunked byte stream of NDJSON into parsed records, in order. */
export async function* readNdjson<T = unknown>(
  stream: ReadableStream<Uint8Array>,
): AsyncGenerator<T> {
  const reader = stream.getReader()
  const decoder = new TextDecoder()
  let carry = ''
  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      carry += decoder.decode(value, { stream: true })
      let newline = carry.indexOf('\n')
      while (newline >= 0) {
        const line = carry.slice(0, newline).trim()
        carry = carry.slice(newline + 1)
        if (line.length > 0) yield JSON.parse(line) as T
        newline = carry.indexOf('\n')
      }
    }
    const tail = (carry + decoder.decode()).trim()
    if (tail.length > 0) yield JSON.parse(tail) as T
  } finally {
    reader.releaseLock()
  }
}

/** Split a complete NDJSON text (tests, non-streaming fallbacks). */
export function parseNdjson<T = unknown>(text: string): T[] {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
    .map((line) => JSON.parse(line) as T)
}

/**
 * The same fold the backend applies for the JSON document mode
 * (matrix_serialize.fold_matrix_records): header fields at the top level,
 * shared blocks by kind then id, cells sorted by index. Returns null while
 * no header has arrived — a document cannot exist without its axes.
 */
export function foldMatrixRecords<TRoute = unknown>(
  records: Iterable<MatrixRecord<TRoute>>,
): MatrixDocument<TRoute> | null {
  let header: MatrixHeader | null = null
  const shared: Partial<Record<SharedKind, Record<string, unknown>>> = {}
  const cells: MatrixCell<TRoute>[] = []
  let status: MatrixDocument['status'] = 'aborted'
  let stats: MatrixStats | null = null
  for (const record of records) {
    if (record.type === 'header') header = record
    else if (record.type === 'shared') (shared[record.kind] ??= {})[record.id] = record.data
    else if (record.type === 'cell') {
      const { type: _type, ...cell } = record
      void _type
      cells.push(cell as MatrixCell<TRoute>)
    } else if (record.type === 'done') {
      status = record.status
      stats = record.stats
    }
  }
  if (header === null) return null
  const { type: _type, ...headerFields } = header
  void _type
  return {
    ...headerFields,
    status,
    stats: stats ?? { n_cells: header.n_cells, n_ok: 0, n_error: 0, n_cache_hit: 0, elapsed_s: 0 },
    ...(Object.keys(shared).length > 0 ? { shared } : {}),
    cells: [...cells].sort((a, b) => a.index - b.index),
  }
}

interface RouteWithGeometryRefs {
  trip_pairs: {
    outbound: { segments: { geometry_id: string }[] }
    return_trip: { segments: { geometry_id: string }[] }
  }[]
  [key: string]: unknown
}

/**
 * Turn a "full" cell back into the /calc response shape: geometry references
 * become a route.geometries list, parameter references become
 * evaluation.input.parameters. Unknown references are left as they are — the
 * backend guarantees every shared record precedes its first reference, so a
 * miss here means the stream was cut short.
 */
export function inlineSharedRefs<TRoute extends RouteWithGeometryRefs>(
  cell: MatrixCellOk<TRoute>,
  shared: MatrixDocument['shared'] | undefined,
): {
  route: TRoute & { geometries: { id: string; coords: unknown }[] }
  parameters: Record<string, unknown>
} | null {
  if (!cell.route || !cell.evaluation || !shared) return null
  const geometry = shared.geometry ?? {}
  const geometries: { id: string; coords: unknown }[] = []
  const seen = new Set<string>()
  for (const pair of cell.route.trip_pairs) {
    for (const trip of [pair.outbound, pair.return_trip]) {
      for (const seg of trip.segments) {
        if (seen.has(seg.geometry_id) || !(seg.geometry_id in geometry)) continue
        seen.add(seg.geometry_id)
        geometries.push({ id: seg.geometry_id, coords: geometry[seg.geometry_id] })
      }
    }
  }
  const parameters: Record<string, unknown> = {}
  for (const [kind, ref] of Object.entries(cell.evaluation.parameters_refs)) {
    const block = shared[kind as SharedKind]?.[ref]
    if (block !== undefined) parameters[kind] = block
  }
  return { route: { ...cell.route, geometries }, parameters }
}

/**
 * A full-detail cell as the /calc response it is equivalent to — how a
 * scenario switch is served without asking the backend for anything. The
 * versions and the models block come from the header (identical for every
 * cell); the request is the header's echo re-pointed at this cell's
 * coordinates, so publishing from it sends exactly what /calc would have.
 *
 * Returns null for a summary-level cell — the caller must fall back to a
 * real /calc then.
 */
export function cellAsCalcResponse<TRoute extends RouteWithGeometryRefs>(
  document: MatrixDocument<TRoute>,
  cell: MatrixCellOk<TRoute>,
): ProposalCalcResponse<TRoute> | null {
  const inlined = inlineSharedRefs(cell, document.shared)
  if (!inlined || !cell.evaluation || !document.models) return null
  const {
    composition_ids: _c,
    scenario_ids: _s,
    detail: _d,
    ...how
  } = document.request as Record<string, unknown> & {
    composition_ids?: unknown
    scenario_ids?: unknown
    detail?: unknown
  }
  void _c
  void _s
  void _d
  return {
    route_builder_version: document.route_builder_version,
    calc_version: document.calc_version,
    route_fingerprint: cell.route_fingerprint,
    request: { ...how, composition_id: cell.composition_id, scenario_id: cell.scenario_id },
    ...(cell.suggested_stops ? { suggested_stops: cell.suggested_stops } : {}),
    summary: cell.summary,
    route: inlined.route,
    evaluation: {
      models: document.models,
      input: { parameters: inlined.parameters },
      views: cell.evaluation.views,
    },
  } as unknown as ProposalCalcResponse<TRoute>
}

/** Cell lookup keyed the way the UI asks: by (scenario, composition). */
export function cellKey(scenarioId: number, compositionId: string): string {
  return `${scenarioId}:${compositionId}`
}
