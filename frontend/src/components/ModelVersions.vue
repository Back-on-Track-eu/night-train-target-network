<script setup lang="ts">
// The model versions a panel's figures were produced by, as one muted line:
// "Cost model 0.9.34 · Composition model 0.9.5". Per-result versions (route
// builder, cost, demand) come from the result on screen; the parameter and
// factor models (compositions, infrastructure, energy, emissions) from the
// registry, GET /api/models, which the store fetches once per session. An
// item without a version is left out rather than shown as a gap.
defineProps<{ items: { label: string; version: string | null | undefined }[] }>()
</script>

<template>
  <p class="text-xs text-primary-50/40">
    <template v-for="(item, i) in items.filter((it) => it.version)" :key="item.label">
      <span v-if="i > 0"> · </span>{{ item.label }} {{ item.version }}
    </template>
  </p>
</template>
