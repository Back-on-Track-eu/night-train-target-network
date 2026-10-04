<script setup lang="ts">
// One story card of a report page: kicker, one big number, a one-line
// title, prose (default slot) and a chart beside it (#viz slot). Cards
// stack on a phone; `wide` stacks them at every width, for a map or a
// quote grid that needs the whole row.
defineProps<{
  kicker: string
  title: string
  big?: string
  wide?: boolean
}>()
</script>

<template>
  <section class="report-card" :class="{ 'report-card--wide': wide }">
    <div class="report-card__text">
      <p class="report-kicker">{{ kicker }}</p>
      <p v-if="big" class="report-card__big">{{ big }}</p>
      <h2 class="report-card__title">{{ title }}</h2>
      <div class="report-card__body">
        <slot />
      </div>
    </div>
    <div v-if="$slots.viz" class="report-card__viz">
      <slot name="viz" />
    </div>
  </section>
</template>

<style>
/* Unscoped on purpose: the body is markdown rendered by VitePress, whose
   .vp-doc rules (heading borders, paragraph margins) would otherwise win
   over a scoped selector. Everything is namespaced under .report-card. */
.report-card {
  display: grid;
  grid-template-columns: 1fr 1.15fr;
  gap: 32px;
  align-items: center;
  margin: 20px 0;
  padding: 36px;
  border: 1px solid var(--bot-hairline);
  border-radius: 16px;
  background: var(--bot-lift-5);
}

.report-card--wide {
  grid-template-columns: 1fr;
}

.report-kicker {
  margin: 0 0 6px;
  color: var(--bot-primary-300);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.vp-doc .report-card .report-kicker {
  margin: 0 0 6px;
  line-height: 1.4;
}

.report-card__big {
  margin: 0;
  color: var(--bot-primary-200);
  font-size: clamp(44px, 7vw, 84px);
  font-weight: 700;
  letter-spacing: -0.03em;
}

.vp-doc .report-card .report-card__big {
  margin: 0;
  line-height: 1;
}

.vp-doc .report-card h2.report-card__title {
  margin: 6px 0 14px;
  padding: 0;
  border: 0;
  font-size: 22px;
  font-weight: 700;
  line-height: 1.25;
  letter-spacing: 0;
}

.vp-doc .report-card__body p {
  margin: 0 0 12px;
  color: var(--bot-ink-70);
  font-size: 16px;
  line-height: 1.55;
}

.vp-doc .report-card__body p:last-child {
  margin-bottom: 0;
}

.vp-doc .report-card__body strong {
  color: var(--bot-ink);
}

.report-card__viz {
  min-width: 0;
}

/* Sub-headings and captions inside the chart column, set by the chart
   components and by hand-written markdown alike. */
.vp-doc .report-card .report-subhead {
  margin: 18px 0 6px;
  color: var(--bot-ink-50);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.1em;
  line-height: 1.4;
  text-transform: uppercase;
}

.vp-doc .report-card .report-caption {
  margin: 8px 0 0;
  color: var(--bot-ink-50);
  font-size: 12px;
  line-height: 1.5;
}

.vp-doc .report-card .report-caption strong {
  color: var(--bot-ink-70);
}

.report-two {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 28px;
}

@media (max-width: 720px) {
  .report-card {
    grid-template-columns: 1fr;
    padding: 24px 20px;
  }

  .report-two {
    grid-template-columns: 1fr;
  }
}
</style>
