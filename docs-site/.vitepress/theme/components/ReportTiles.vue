<script setup lang="ts">
// A row of number tiles — the hero's headline figures, or a card's
// secondary numbers under its chart. Values arrive formatted: the page
// decides whether 2 120 194 reads as "2.1 M km".
defineProps<{
  items: { value: string; label: string }[]
}>()
</script>

<template>
  <div class="report-tiles">
    <div v-for="item in items" :key="item.label" class="report-tiles__tile">
      <p class="report-tiles__value">{{ item.value }}</p>
      <p class="report-tiles__label">{{ item.label }}</p>
    </div>
  </div>
</template>

<style>
.report-tiles {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 12px;
  margin: 8px 0;
}

.report-tiles__tile {
  padding: 16px;
  border: 1px solid var(--bot-hairline);
  border-radius: 12px;
  background: var(--bot-lift-10);
}

.vp-doc .report-tiles__value {
  margin: 0;
  color: var(--bot-primary-200);
  font-size: clamp(20px, 2.2vw, 28px);
  font-weight: 700;
  letter-spacing: -0.02em;
  line-height: 1.1;
  /* .vp-doc breaks long words; a figure is one word (its thousands are
     narrow no-break spaces), so wrapping happens only at real spaces. */
  overflow-wrap: normal;
}

.vp-doc .report-tiles__label {
  margin: 4px 0 0;
  color: var(--bot-ink-70);
  font-size: 12px;
  line-height: 1.4;
}
</style>
