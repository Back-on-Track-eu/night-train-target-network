<script setup lang="ts">
// A cloud of short labels — the stations readers asked for and did not
// find. Hand-tidied in the page, not derived from the feedback texts.
defineProps<{
  items: string[]
  heading?: string
}>()
</script>

<template>
  <div class="report-chips">
    <p v-if="heading" class="report-subhead">{{ heading }}</p>
    <p class="report-chips__row">
      <span v-for="item in items" :key="item" class="report-chips__chip">{{ item }}</span>
    </p>
  </div>
</template>

<style>
.vp-doc .report-chips__row {
  margin: 0;
  line-height: 1.4;
}

.report-chips__chip {
  display: inline-block;
  margin: 0 6px 6px 0;
  padding: 3px 10px;
  border: 1px solid var(--bot-hairline);
  border-radius: 999px;
  background: var(--bot-lift-10);
  color: var(--bot-ink-70);
  font-size: 12px;
}
</style>
