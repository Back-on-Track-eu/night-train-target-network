import { describe, expect, it } from 'vitest'
import { buildScenarioAxes, conditionLabelKey } from './scenarioAxes'
import type { Scenario } from '@/types/api'

function scenario(
  id: number,
  key: string,
  network: string,
  hsr: boolean,
  optTt: boolean,
): Scenario {
  return {
    scenario_id: id,
    scenario_key: key,
    scenario_name: key,
    description: null,
    change_log: null,
    editor: null,
    created_at: '',
    is_current_base: id === 1,
    is_current_scenario: true,
    track_infrastructures_version: id,
    track_infrastructure_defaults_version: id,
    stop_infrastructures_version: id,
    stop_infrastructure_defaults_version: id,
    passage_charges_version: id,
    routing_graph_key: `infra_${network}`,
    dimensions: { network, hsr_allowed: hsr, optimised_timetable: optTt },
  }
}

const seeded = [
  scenario(1, 'infra-2026', '2026', false, false),
  scenario(2, 'infra-2026-hsr', '2026', true, false),
  scenario(3, 'infra-2026-hsr-opt-tt', '2026', true, true),
  scenario(5, 'infra-2032', '2032', false, false),
  scenario(6, 'infra-2032-hsr', '2032', true, false),
  scenario(7, 'infra-2032-hsr-opt-tt', '2032', true, true),
]

// No preview network unless a test asks for one — the module default holds
// 2032 back, which the preview block below covers explicitly.
const NONE = new Set<string>()

describe('buildScenarioAxes', () => {
  const axes = buildScenarioAxes(seeded, NONE)

  it('maps switch states to scenarios and back', () => {
    expect(axes.scenarioFor({ network: '2032', hsr: true, optTt: false })?.scenario_id).toBe(6)
    expect(axes.stateOf(3)).toEqual({ network: '2026', hsr: true, optTt: true })
    expect(axes.stateOf(99)).toBeNull()
  })

  it('offers networks in ascending order and orders scenarios by the grid', () => {
    expect(axes.networks).toEqual([
      { network: '2026', preview: false },
      { network: '2032', preview: false },
    ])
    expect(axes.ordered.map((s) => s.scenario_id)).toEqual([1, 2, 3, 5, 6, 7])
  })

  it('enables optimised timetables only where a scenario exists for it', () => {
    expect(axes.canToggle({ network: '2026', hsr: false, optTt: false }, 'optTt')).toBe(false)
    expect(axes.canToggle({ network: '2026', hsr: true, optTt: false }, 'optTt')).toBe(true)
    expect(axes.canToggle({ network: '2026', hsr: true, optTt: true }, 'hsr')).toBe(false)
    expect(axes.canSelectNetwork({ network: '2026', hsr: true, optTt: true }, '2032')).toBe(true)
  })

  it('ignores scenarios without dimensions', () => {
    const withUnknown = [
      ...seeded,
      { ...scenario(9, 'other', 'x', false, false), dimensions: null },
    ]
    expect(buildScenarioAxes(withUnknown, NONE).ordered).toHaveLength(6)
  })
})

describe('preview networks', () => {
  const axes = buildScenarioAxes(seeded, new Set(['2032']))

  it('shows the network but does not let anything land on it', () => {
    expect(axes.networks).toEqual([
      { network: '2026', preview: false },
      { network: '2032', preview: true },
    ])
    expect(axes.canSelectNetwork({ network: '2026', hsr: false, optTt: false }, '2032')).toBe(false)
    expect(axes.scenarioFor({ network: '2032', hsr: true, optTt: false })).toBeUndefined()
  })

  it('keeps its scenarios out of the comparison and the matrix axis', () => {
    expect(axes.ordered.map((s) => s.scenario_id)).toEqual([1, 2, 3])
  })

  it('still resolves the switch position of a proposal stored against it', () => {
    expect(axes.stateOf(6)).toEqual({ network: '2032', hsr: true, optTt: false })
  })
})

describe('conditionLabelKey', () => {
  it('names the three operating conditions', () => {
    expect(conditionLabelKey({ network: '2026', hsr: false, optTt: false })).toBe('base')
    expect(conditionLabelKey({ network: '2026', hsr: true, optTt: false })).toBe('hsr')
    expect(conditionLabelKey({ network: '2026', hsr: true, optTt: true })).toBe('hsrOptTt')
  })
})
