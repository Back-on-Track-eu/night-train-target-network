import { describe, expect, it } from 'vitest'
import {
  cellAsCalcResponse,
  cellKey,
  foldMatrixRecords,
  inlineSharedRefs,
  parseNdjson,
  readNdjson,
} from './calcMatrix'
import type { MatrixCellOk, MatrixRecord } from '@/types/api'

type Route = {
  trip_pairs: {
    outbound: { segments: { geometry_id: string }[] }
    return_trip: { segments: { geometry_id: string }[] }
  }[]
}

const header: MatrixRecord<Route> = {
  type: 'header',
  route_builder_version: '0.9.33',
  calc_version: '0.9.25',
  request: {},
  axes: { scenarios: [], compositions: [] },
  n_cells: 2,
  baseline_index: 0,
}
const shared: MatrixRecord<Route> = {
  type: 'shared',
  kind: 'geometry',
  id: 'g:aaaa',
  data: [
    [1, 2],
    [3, 4],
  ],
}
const paramShared: MatrixRecord<Route> = {
  type: 'shared',
  kind: 'compositions',
  id: 'p:bbbb',
  data: { c: 1 },
}
function cell(index: number, cacheHit: boolean): MatrixRecord<Route> {
  return {
    type: 'cell',
    index,
    scenario_id: 1,
    composition_id: index === 0 ? 'A' : 'B',
    status: 'ok',
    cache_hit: cacheHit,
    route_fingerprint: 'sha256:x',
    summary: { co2_savings_t_per_year: 1 },
    route: {
      trip_pairs: [
        {
          outbound: { segments: [{ geometry_id: 'g:aaaa' }] },
          return_trip: { segments: [{ geometry_id: 'g:aaaa' }] },
        },
      ],
    },
    evaluation: {
      parameters_refs: {
        geometry: '',
        track_infrastructures: 'p:none',
        stop_infrastructures: 'p:none',
        compositions: 'p:bbbb',
      },
      views: {} as never,
    },
  }
}
const done: MatrixRecord<Route> = {
  type: 'done',
  status: 'complete',
  stats: { n_cells: 2, n_ok: 2, n_error: 0, n_cache_hit: 1, elapsed_s: 1.5 },
}

function stream(text: string, chunkSize: number): ReadableStream<Uint8Array> {
  const bytes = new TextEncoder().encode(text)
  let offset = 0
  return new ReadableStream({
    pull(controller) {
      if (offset >= bytes.length) return controller.close()
      controller.enqueue(bytes.slice(offset, offset + chunkSize))
      offset += chunkSize
    },
  })
}

describe('readNdjson', () => {
  it('yields one record per line regardless of chunk boundaries', async () => {
    const text = [header, shared, cell(1, true), cell(0, false), done]
      .map((r) => JSON.stringify(r))
      .join('\n')
    for (const chunkSize of [1, 7, 64, 100_000]) {
      const records: MatrixRecord<Route>[] = []
      for await (const record of readNdjson<MatrixRecord<Route>>(stream(text, chunkSize))) {
        records.push(record)
      }
      expect(records.map((r) => r.type)).toEqual(['header', 'shared', 'cell', 'cell', 'done'])
    }
  })

  it('handles a trailing newline and blank lines', async () => {
    const text = `${JSON.stringify(header)}\n\n${JSON.stringify(done)}\n`
    const records = parseNdjson<MatrixRecord<Route>>(text)
    expect(records).toHaveLength(2)
    const streamed: MatrixRecord<Route>[] = []
    for await (const r of readNdjson<MatrixRecord<Route>>(stream(text, 5))) streamed.push(r)
    expect(streamed).toHaveLength(2)
  })
})

describe('foldMatrixRecords', () => {
  it('mirrors the backend fold: cells sorted, shared by kind, stats from done', () => {
    const doc = foldMatrixRecords([
      header,
      shared,
      paramShared,
      cell(1, true),
      cell(0, false),
      done,
    ])
    expect(doc).not.toBeNull()
    expect(doc!.cells.map((c) => c.index)).toEqual([0, 1])
    expect(doc!.shared?.geometry?.['g:aaaa']).toEqual([
      [1, 2],
      [3, 4],
    ])
    expect(doc!.status).toBe('complete')
    expect(doc!.stats.n_cache_hit).toBe(1)
    expect('type' in doc!).toBe(false)
  })

  it('is null without a header and aborted without a done record', () => {
    expect(foldMatrixRecords([cell(0, false)])).toBeNull()
    expect(foldMatrixRecords([header, cell(0, false)])!.status).toBe('aborted')
  })
})

describe('inlineSharedRefs', () => {
  it('rebuilds route.geometries and the parameters block from the shared map', () => {
    const doc = foldMatrixRecords([header, shared, paramShared, cell(0, false), done])!
    const ok = doc.cells[0] as MatrixCellOk<Route>
    const inlined = inlineSharedRefs(ok, doc.shared)!
    expect(inlined.route.geometries).toEqual([
      {
        id: 'g:aaaa',
        coords: [
          [1, 2],
          [3, 4],
        ],
      },
    ])
    expect(inlined.parameters).toEqual({ compositions: { c: 1 } })
  })

  it('is null for a summary-level cell', () => {
    const summaryCell = { ...cell(0, false), route: undefined, evaluation: undefined }
    const { type: _t, ...bare } = summaryCell as MatrixCellOk<Route> & { type: 'cell' }
    void _t
    expect(inlineSharedRefs(bare, {})).toBeNull()
  })
})

describe('cellKey', () => {
  it('is stable per (scenario, composition)', () => {
    expect(cellKey(3, 'NEW-BAL-7')).toBe('3:NEW-BAL-7')
  })
})

describe('cellAsCalcResponse', () => {
  it('rebuilds a full cell into the /calc response it is equivalent to', () => {
    const doc = foldMatrixRecords([
      {
        ...header,
        request: {
          stops: ['a', 'b'],
          composition_ids: ['A'],
          scenario_ids: [1],
          detail: 'full',
          schedule_mode: 'alwaysDaily',
        },
        models: { evaluation: {} } as never,
      },
      shared,
      paramShared,
      cell(0, false),
      done,
    ])!
    const response = cellAsCalcResponse(doc, doc.cells[0] as MatrixCellOk<Route>)!
    expect(response.calc_version).toBe('0.9.25')
    expect(response.route_fingerprint).toBe('sha256:x')
    // Axes replaced by this cell's coordinates; the HOW fields survive.
    expect(response.request).toEqual({
      stops: ['a', 'b'],
      schedule_mode: 'alwaysDaily',
      composition_id: 'A',
      scenario_id: 1,
    })
    expect(response.evaluation.input.parameters).toEqual({ compositions: { c: 1 } })
    expect(response.evaluation.models).toEqual({ evaluation: {} })
    expect(response.summary).toEqual({ co2_savings_t_per_year: 1 })
  })

  it('is null for a summary-level cell — the caller must fall back to /calc', () => {
    const summaryDoc = foldMatrixRecords([header, done])!
    const bare = { ...cell(0, false), route: undefined, evaluation: undefined } as never
    expect(cellAsCalcResponse(summaryDoc, bare)).toBeNull()
  })
})
