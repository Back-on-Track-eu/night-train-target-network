<script setup lang="ts">
import logo from '../assets/logo.png'
import headerBg from '../assets/header.jpg'

// The Back-on-Track masthead, carrying the same logo and the same header
// image as frontend/src/components/AppHeader.vue — compressed into one fixed
// bar rather than the app's two scrolling bands.
//
// WHY NOT A REPLICA. VitePress's `layout-top` slot renders in normal document
// flow, but its nav and sidebar are `position: fixed; top:
// var(--vp-layout-top-height)` (VPNav.vue, VPSidebar.vue). The slot is built
// for chrome that STAYS. Reproducing the app's 243px scroll-away masthead
// would pin the nav 243px down the viewport forever: scroll once and page
// content runs up behind a nav bar stranded in mid-screen. So the masthead is
// fixed, and to be fixed it has to be short.
//
// The header image survives as this bar's background — `cover` at the app's
// own 50% 48% focal point, so it is a slice of the same band rather than a
// flat colour. A sapphire veil sits over it: the image's brightness is not
// under our control, and white-on-unveiled-photo is not a contrast guarantee.
//
// Dropped from the app's version: the language switcher (these pages are
// English only) and the account menu (the docs have no auth). "Open the tool"
// takes the slot the switcher occupies there.
//
// The bar's height is mirrored by --vp-layout-top-height in custom.css, which
// is how VitePress offsets its nav, sidebar and content. Change one, change
// the other.
//
// The tool lives at the origin root while these pages sit under /docs/, so a
// root-relative href is correct. target="_blank" is load-bearing twice over:
// VitePress's client router intercepts same-origin anchors and would try to
// resolve "/" as a docs page, and leaving the app in place would discard a
// proposal being drafted (the same reasoning as AppHeader's own comment).
</script>

<template>
  <div class="bot-brand" :style="{ backgroundImage: `url(${headerBg})` }">
    <div class="bot-veil">
      <div class="bot-inner">
        <a href="https://back-on-track.eu/" target="_blank" rel="noopener noreferrer">
          <img :src="logo" alt="Night Train Target Network" class="bot-logo" />
        </a>
        <a href="/" target="_blank" rel="noopener noreferrer" class="bot-tool-link">
          Open the tool
          <svg
            class="bot-tool-icon"
            viewBox="0 0 24 24"
            width="14"
            height="14"
            aria-hidden="true"
            focusable="false"
          >
            <path
              fill="currentColor"
              d="M14 3v2h3.59l-9.83 9.83 1.41 1.41L19 6.41V10h2V3m-2 16H5V5h7V3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7h-2Z"
            />
          </svg>
        </a>
      </div>
    </div>
  </div>
</template>

<style scoped>
.bot-brand {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  /* VitePress reserves a level for exactly this slot: above the nav (30),
     below the backdrop (50) and the mobile sidebar drawer (60), so opening
     the drawer covers the masthead rather than fighting it. */
  z-index: var(--vp-z-index-layout-top);
  background-color: var(--bot-sapphire);
  background-size: cover;
  background-position: 50% 48%;
}

/* 70% sapphire over the photo. Worst case — a pure white pixel underneath —
   still leaves white text at ~6:1, so the link is legible wherever the image
   crop happens to land. */
.bot-veil {
  background-color: color-mix(in srgb, var(--bot-sapphire) 70%, transparent);
}

/* max-w-[1140px] with a 1rem gutter that disappears at xl, matching
   AppHeader's "px-4 xl:px-0". */
.bot-inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin: 0 auto;
  width: 100%;
  max-width: 1140px;
  height: 52px;
  padding: 0 1rem;
}

@media (min-width: 768px) {
  .bot-inner {
    height: 64px;
  }
}

@media (min-width: 1280px) {
  .bot-inner {
    padding: 0;
  }
}

.bot-logo {
  display: block;
  width: 120px;
  object-fit: contain;
}

@media (min-width: 768px) {
  .bot-logo {
    width: 160px;
  }
}

.bot-tool-link {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  flex-shrink: 0;
  color: #ffffff;
  font-size: 13.5px;
  line-height: 1;
  text-decoration: none;
  transition: color 0.15s ease;
}

/* Brand sulphur yellow (--color-sulphur-yellow, frontend/src/style.css:44 —
   declared there but never used). The app's language switcher hovers to
   --color-pure-green #008f39, which is 3.9:1 on sapphire and 1.4:1 over a
   worst-case veiled photo. Of the brand accents this is the only one that
   clears AA against a background we do not control: 4.9:1 worst case. */
.bot-tool-link:hover {
  color: #eaf044;
}

.bot-tool-icon {
  flex-shrink: 0;
  opacity: 0.75;
}
</style>
