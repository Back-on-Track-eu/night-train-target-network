// The "typical night train" yardstick of the general position paper, as the
// gallery applies it: one way, 500–2 000 km, 7–21 hours, at least 50 km/h on
// average. The launch report counted with 7–16 h and 60 km/h; both were
// loosened after looking at the existing catalogue (2026-10-03/04: the median
// real night train runs right around 60 km/h, and a fair share of them —
// Adria, Bosphor Express, Prietenia — take an evening, a night and a day),
// so the gallery's default view is the set the paper means in practice.
//
// In the gallery the yardstick is a PRESET of the four range filters the
// distribution panel exposes (lib/galleryRanges.ts): the panel starts on it,
// a dragged handle or a typed bound leaves it, and the pill brings it back.
// Every range goes to the backend with scope "proposal"
// (adapters/proposal/filter_builder.py), so the bounds are asked of
// PROPOSALS ONLY and every existing (ONTD) train stays listed — the real
// trains are the comparison, whether or not they meet the paper's envelope
// (126 of production's 205 did not, 2026-10-03).

export const TYPICAL_NIGHT_TRAIN = {
  distanceKm: { min: 500, max: 2000 },
  timeH: { min: 7, max: 21 },
  avgSpeedKmh: { min: 50 },
} as const
