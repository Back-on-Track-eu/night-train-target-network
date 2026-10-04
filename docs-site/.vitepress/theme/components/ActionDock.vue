<script setup lang="ts">
import { withBase } from 'vitepress'

// The sticky action bar of the report and update pages: what a reader
// should do after reading — draw a route, browse the gallery, send
// feedback. Fixed to the bottom of the viewport, so the pages carry no
// in-text buttons for these three; a spacer keeps the last card clear.
//
// The tool lives at the origin root while these pages sit under /docs/,
// so the first two links are root-relative, and like every link from the
// docs into the tool they open a new tab (SiteBrandBar's reasoning: the
// docs stay where the reader was, and VitePress's client router leaves an
// anchor with a target attribute alone instead of trying to load /gallery
// as a docs page). "#gallery" lands past the landing pitch, on the search
// bar and the map (frontend/src/lib/galleryEntry.ts).
const ACTIONS = [
  { label: 'Suggest a new route', href: '/proposal-builder', primary: true, external: true },
  { label: 'Visit the gallery', href: '/gallery#gallery', primary: false, external: true },
  { label: 'Provide feedback', href: withBase('/feedback'), primary: false, external: false },
]
</script>

<template>
  <div class="action-dock__spacer" aria-hidden="true" />
  <nav class="action-dock" aria-label="Actions">
    <a
      v-for="action in ACTIONS"
      :key="action.href"
      :href="action.href"
      :target="action.external ? '_blank' : undefined"
      :rel="action.external ? 'noopener noreferrer' : undefined"
      class="action-dock__button"
      :class="{ 'action-dock__button--primary': action.primary }"
    >
      {{ action.label }}
    </a>
  </nav>
</template>

<style>
.action-dock__spacer {
  height: 40px;
}

.action-dock {
  position: fixed;
  right: 0;
  bottom: 0;
  left: 0;
  /* Above the page, below VitePress's nav (var(--vp-z-index-nav), 30) so
     the mobile menu and search overlays still cover it. */
  z-index: 20;
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  justify-content: center;
  padding: 12px 16px calc(12px + env(safe-area-inset-bottom));
  border-top: 1px solid var(--bot-hairline);
  background: color-mix(in srgb, var(--bot-sapphire) 88%, transparent);
  backdrop-filter: blur(10px);
}

/* The desktop sidebar is fixed on the left; the dock starts where it ends. */
@media (min-width: 960px) {
  .action-dock {
    left: var(--vp-sidebar-width);
  }
}

@media (min-width: 1440px) {
  .action-dock {
    left: calc((100% - (var(--vp-layout-max-width) - 64px)) / 2 + var(--vp-sidebar-width) - 32px);
  }
}

.vp-doc .action-dock__button,
.action-dock__button {
  display: inline-block;
  padding: 9px 16px;
  border: 1px solid var(--bot-hairline-strong);
  border-radius: 999px;
  color: var(--bot-ink);
  font-size: 14px;
  font-weight: 700;
  line-height: 1.4;
  text-decoration: none;
  transition:
    background-color 0.15s,
    border-color 0.15s;
}

.vp-doc .action-dock__button:hover,
.action-dock__button:hover {
  background: var(--bot-lift-10);
  color: var(--bot-ink);
  text-decoration: none;
}

.vp-doc .action-dock__button--primary,
.action-dock__button--primary {
  border-color: var(--bot-primary-500);
  background: var(--bot-primary-500);
  color: #ffffff;
}

.vp-doc .action-dock__button--primary:hover,
.action-dock__button--primary:hover {
  border-color: var(--bot-primary-600);
  background: var(--bot-primary-600);
  color: #ffffff;
}

@media (max-width: 720px) {
  .action-dock__spacer {
    height: 96px;
  }

  .action-dock__button {
    flex: 1 1 auto;
    padding: 9px 10px;
    font-size: 13px;
    text-align: center;
  }
}
</style>
