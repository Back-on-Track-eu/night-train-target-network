<script setup lang="ts">
// One timetable time plus its overnight day marker ("07:36 +1").
//
// Extracted because it appears four times — arrival/departure × the edit and
// display tables in ProposalViewport — and because the marker's legibility is
// exactly the kind of thing that gets tuned more than once. It was originally a
// <sup>, which inside 12px text renders near 10px and was too small to read.
// Now it is the same size as the time, bold, on its own chip so "0736+1" can't
// read as a single number.
defineProps<{
  time: string | null
  /** Calendar days after the trip's first departure; only > 0 shows a marker. */
  day?: number
}>()
</script>

<template>
  <span v-if="time" class="flex items-center gap-1">
    <span class="text-xs tabular-nums leading-none text-primary-50">{{ time }}</span>
    <span
      v-if="(day ?? 0) > 0"
      class="rounded bg-primary-50/25 px-1 py-0.5 text-xs font-bold leading-none text-primary-50"
      >+{{ day }}</span
    >
  </span>
</template>
