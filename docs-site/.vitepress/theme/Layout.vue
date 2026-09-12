<script setup lang="ts">
import DefaultTheme from 'vitepress/theme'
import SiteBrandBar from './components/SiteBrandBar.vue'

// The masthead goes in VitePress's `layout-top` slot rather than replacing the
// nav: that slot is the documented extension point for content above the
// chrome, and VitePress offsets its own fixed nav and sidebar by
// --vp-layout-top-height (set in custom.css) to make room. Everything else —
// sidebar, outline, mobile nav, local search — stays VitePress's, which is the
// whole point of theming by extension instead of writing a theme.
const { Layout } = DefaultTheme
</script>

<template>
  <Layout>
    <template #layout-top>
      <SiteBrandBar />
    </template>
  </Layout>
</template>
