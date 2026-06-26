export interface Stop {
  stop_id: string
  name: string
  country_code: string
  lat: number
  lon: number
  stop_charge_eur: { value: number; is_default: boolean }
}

export interface Composition {
  comp_id: string
  description: string
  operator_id: string
  routing: { max_speed_kmh: number; total_weight_t: number; hsr_allowed: boolean }
  capacity: Record<string, { places: number; density: number }>
}

export interface StopsResponse {
  stops: Stop[]
}

export interface CompositionsResponse {
  compositions: Composition[]
}
