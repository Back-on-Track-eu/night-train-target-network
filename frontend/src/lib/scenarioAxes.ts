// The scenario picker's three switches (network / high-speed lines /
// optimised timetables) mapped onto the scenario list — both ways. The
// coordinates come from the backend (Scenario.dimensions, derived from the
// scenario key in scenario_serialize.py); nothing here parses a key.
//
// Which switch states exist is data-driven: a toggle is enabled exactly when
// flipping it lands on a scenario the API offers. Today that gives "optimised
// timetables" only together with high-speed lines, because no such scenario
// is seeded without it — the rule lives in the seed, not in this file.
//
// PREVIEW NETWORKS are the one exception, and deliberately a frontend
// decision: the 2032 routing instance and its graph cache run, and the
// backend will happily evaluate against them, but the underlying
// infrastructure data is not at the quality we want to publish figures from.
// Such a network is shown as "coming soon" — not selectable, and left out of
// the comparison surfaces and the matrix request, so we neither advertise
// numbers we do not trust nor spend half the grid computing them. Removing a
// network from PREVIEW_NETWORKS (or VITE_PREVIEW_NETWORKS) is the whole
// release switch; nothing else changes.

import type { Scenario, ScenarioDimensions } from '@/types/api'

const PREVIEW_NETWORKS: readonly string[] = ['2032']

/** Preview networks, overridable per deployment: VITE_PREVIEW_NETWORKS is a
 *  comma-separated list, and an empty string releases every network. */
export function previewNetworks(): Set<string> {
  const configured = import.meta.env.VITE_PREVIEW_NETWORKS
  if (configured === undefined) return new Set(PREVIEW_NETWORKS)
  return new Set(
    configured
      .split(',')
      .map((n: string) => n.trim())
      .filter(Boolean),
  )
}

export interface ScenarioSwitchState {
  network: string
  hsr: boolean
  optTt: boolean
}

export interface NetworkOption {
  network: string
  /** Rendered as "coming soon" and not selectable — see PREVIEW_NETWORKS. */
  preview: boolean
}

export interface ScenarioAxes {
  /** Networks in the order they should appear (numeric, ascending), preview
   *  ones included — the picker shows them, disabled. */
  networks: NetworkOption[]
  /** Scenario for a switch state, or undefined when the grid has no such cell. */
  scenarioFor(state: ScenarioSwitchState): Scenario | undefined
  /** Switch state of a scenario, or null when it has no grid coordinates. */
  stateOf(scenarioId: number): ScenarioSwitchState | null
  /** Whether flipping one switch from `state` lands on an offered scenario. */
  canToggle(state: ScenarioSwitchState, toggle: 'hsr' | 'optTt'): boolean
  /** Whether the whole network switch has an offered target for `state`. */
  canSelectNetwork(state: ScenarioSwitchState, network: string): boolean
  /** The scenarios a visitor can actually land on — grid coordinates,
   *  preview networks excluded — in network → hsr → optTt order. What the
   *  comparison bars, the grid and the matrix's scenario axis use. */
  ordered: Scenario[]
}

function key(d: ScenarioDimensions | ScenarioSwitchState): string {
  const hsr = 'hsr' in d ? d.hsr : d.hsr_allowed
  const optTt = 'optTt' in d ? d.optTt : d.optimised_timetable
  return `${d.network}|${hsr ? 1 : 0}|${optTt ? 1 : 0}`
}

export function buildScenarioAxes(
  scenarios: Scenario[],
  preview: Set<string> = previewNetworks(),
): ScenarioAxes {
  const byKey = new Map<string, Scenario>()
  const stateById = new Map<number, ScenarioSwitchState>()
  for (const scenario of scenarios) {
    const d = scenario.dimensions
    if (!d) continue
    byKey.set(key(d), scenario)
    stateById.set(scenario.scenario_id, {
      network: d.network,
      hsr: d.hsr_allowed,
      optTt: d.optimised_timetable,
    })
  }
  const networks = [...new Set([...stateById.values()].map((s) => s.network))]
    .sort((a, b) => Number(a) - Number(b) || a.localeCompare(b))
    .map((network) => ({ network, preview: preview.has(network) }))
  const scenarioFor = (state: ScenarioSwitchState) =>
    preview.has(state.network) ? undefined : byKey.get(key(state))
  const ordered = networks
    .filter((n) => !n.preview)
    .flatMap(({ network }) =>
      [
        { hsr: false, optTt: false },
        { hsr: true, optTt: false },
        { hsr: true, optTt: true },
        { hsr: false, optTt: true },
      ]
        .map((flags) => scenarioFor({ network, ...flags }))
        .filter((s): s is Scenario => s !== undefined),
    )
  return {
    networks,
    ordered,
    scenarioFor,
    // stateOf resolves for EVERY scenario with coordinates, preview included:
    // a proposal stored against one must still render its switch position
    // rather than an empty picker.
    stateOf: (scenarioId) => stateById.get(scenarioId) ?? null,
    canToggle: (state, toggle) => scenarioFor({ ...state, [toggle]: !state[toggle] }) !== undefined,
    canSelectNetwork: (state, network) => scenarioFor({ ...state, network }) !== undefined,
  }
}

/** Short label parts for chart axes: "Base", "HSR", "HSR + tt". */
export function conditionLabelKey(state: ScenarioSwitchState): 'base' | 'hsr' | 'hsrOptTt' {
  if (state.optTt) return 'hsrOptTt'
  return state.hsr ? 'hsr' : 'base'
}
