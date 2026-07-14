import maplibregl from 'maplibre-gl'

export type LngLat = [number, number]

// Mercator coordinates span 0..1 across the whole world, so European legs are
// on the order of 0.01..0.1 apart. This threshold is far below any real leg
// yet safely above float round-trip noise, used only to drop bend vertices
// that would create degenerate zero-length segments.
const EPS = 1e-9

/**
 * Build a schematic "train itinerary" connector through the given stops.
 *
 * Every leg between two consecutive stops A -> B travels only horizontally,
 * vertically, or at exactly 45 degrees (octilinear routing). Each leg has a
 * single bend: a 45-degree diagonal leaving A that covers the *shorter* of the
 * two axes, followed by an axis-aligned segment into B for the remainder. When
 * a leg is already axis-aligned or perfectly diagonal the bend coincides with
 * an endpoint and is omitted, so no zero-length segments are produced.
 *
 * "45 degrees" is measured on screen, not in raw lon/lat: raw degrees are
 * distorted by the Web Mercator projection (more so at European latitudes), so
 * the octilinear math is done in Mercator space. Screen pixels are a uniform
 * scale + translate of Mercator coordinates, so an angle that is 45 degrees in
 * Mercator space stays 45 degrees on screen at every pan and zoom — no
 * recompute on map move is needed.
 */
export function octilinearPath(coords: LngLat[]): LngLat[] {
  if (coords.length < 2) return coords.map((c) => [c[0], c[1]] as LngLat)

  const merc = coords.map((c) => maplibregl.MercatorCoordinate.fromLngLat(c))
  const out: LngLat[] = [[coords[0][0], coords[0][1]]]

  for (let i = 0; i < merc.length - 1; i++) {
    const a = merc[i]
    const b = merc[i + 1]
    const dx = b.x - a.x
    const dy = b.y - a.y
    const m = Math.min(Math.abs(dx), Math.abs(dy))

    // Diagonal leg leaving A covers the shorter axis; the remainder into B is
    // then axis-aligned. Emit the bend only when it is distinct from both
    // endpoints (i.e. the leg is neither already axis-aligned nor perfectly
    // diagonal), avoiding degenerate zero-length segments.
    const bendX = a.x + Math.sign(dx) * m
    const bendY = a.y + Math.sign(dy) * m
    const distToA = Math.hypot(bendX - a.x, bendY - a.y)
    const distToB = Math.hypot(bendX - b.x, bendY - b.y)
    if (distToA > EPS && distToB > EPS) {
      const bend = new maplibregl.MercatorCoordinate(bendX, bendY, 0).toLngLat()
      out.push([bend.lng, bend.lat])
    }
    out.push([coords[i + 1][0], coords[i + 1][1]])
  }

  return out
}
