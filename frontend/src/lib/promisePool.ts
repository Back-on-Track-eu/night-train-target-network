// Bounded-concurrency map. The gallery needs this because it fans out one
// GET /api/proposal/:id per card to draw route geometry — on a 20-card page
// that was 20 simultaneous requests at a backend running 4 gunicorn workers,
// i.e. the frontend could manufacture the overload it then complains about.

/** Per-item result, settled. A rejecting item does not reject the pool: the
 *  caller decides what a partial failure means (the gallery draws what it can
 *  and raises one toast, rather than one per missing route). */
export type Settled<T> = { ok: true; value: T } | { ok: false; error: unknown }

/**
 * Run `fn` over `items` with at most `limit` in flight. Results are returned in
 * input order regardless of completion order.
 */
export async function mapLimit<I, O>(
  items: readonly I[],
  limit: number,
  fn: (item: I, index: number) => Promise<O>,
): Promise<Settled<O>[]> {
  const results: Settled<O>[] = new Array(items.length)
  if (items.length === 0) return results

  const width = Math.max(1, Math.min(limit, items.length))
  let next = 0

  async function worker(): Promise<void> {
    for (;;) {
      const index = next++
      if (index >= items.length) return
      try {
        results[index] = { ok: true, value: await fn(items[index], index) }
      } catch (error) {
        results[index] = { ok: false, error }
      }
    }
  }

  await Promise.all(Array.from({ length: width }, worker))
  return results
}
