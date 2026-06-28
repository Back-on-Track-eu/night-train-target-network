<template>
  <svg
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 24 24"
    :width="size"
    :height="size"
    role="img"
    aria-hidden="true"
  >
    <path :d="path" :fill="color" />
  </svg>
</template>

<script setup lang="ts">
withDefaults(
  defineProps<{
    path: string
    size?: number | string
    color?: string
  }>(),
  {
    size: 24,
    color: 'currentColor',
  },
)
</script>
