<script setup lang="ts">
// The one spinner. Inherits currentColor so it works on both the dark surfaces
// and the light primary buttons without a variant prop.
withDefaults(defineProps<{ size?: number }>(), { size: 14 })
</script>

<template>
  <span
    class="inline-block shrink-0 animate-spin rounded-full border-2 border-current/30 border-t-current"
    :style="{ width: `${size}px`, height: `${size}px` }"
    aria-hidden="true"
  ></span>
</template>
