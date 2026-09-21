/**
 * How long a short text should stay on screen to be read — for rotating
 * copy that the reader only half-watches, like the facts on the loading
 * overlay. Roughly 240 words a minute, plus the moment it takes to notice the
 * text changed and find its start, and never shorter than FLOOR_MS.
 */

export const READING_BASE_MS = 3_000
export const READING_PER_WORD_MS = 250
export const READING_FLOOR_MS = 10_000

export function wordCount(text: string): number {
  return text.split(/\s+/).filter(Boolean).length
}

export function readingDwellMs(text: string): number {
  return Math.max(READING_FLOOR_MS, READING_BASE_MS + READING_PER_WORD_MS * wordCount(text))
}
