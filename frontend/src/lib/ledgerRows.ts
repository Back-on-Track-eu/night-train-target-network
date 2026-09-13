// Row shape shared by the cost and revenue ledgers. Here rather than in the
// component because `<script setup>` cannot export a type, and both panels
// build these arrays.

export interface LedgerRow {
  key: string
  label: string
  value: number
  depth: number
  hasChildren: boolean
  isExpanded: boolean
  share: number | null
  /** A swatch before the label — revenue's accommodation classes carry the
   *  colour they have in the formation drawing; cost rows have none. */
  color?: string | null
  /** Signed leaves (the catering contribution) print an explicit + when
   *  positive. They are NOT colourised — see LedgerTree. */
  signed?: boolean
}
