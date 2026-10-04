<script setup lang="ts">
// Comment quotes in a grid, each attributed to the route it was written
// on and never to a person: the report shows no display names.
defineProps<{
  items: { text: string; route: string }[]
}>()
</script>

<template>
  <div class="report-quotes">
    <blockquote v-for="q in items" :key="q.text" class="report-quotes__quote">
      <p>“{{ q.text }}”</p>
      <cite>on {{ q.route }}</cite>
    </blockquote>
  </div>
</template>

<style>
.report-quotes {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 14px;
}

.vp-doc .report-quotes__quote {
  margin: 0;
  padding: 18px 20px;
  border: 1px solid var(--bot-hairline);
  border-radius: 12px;
  background: var(--bot-lift-10);
  color: var(--bot-ink);
}

.vp-doc .report-quotes__quote p {
  margin: 0 0 10px;
  font-size: 15px;
  line-height: 1.5;
}

.report-quotes__quote cite {
  color: var(--bot-primary-300);
  font-size: 12px;
  font-style: normal;
}
</style>
