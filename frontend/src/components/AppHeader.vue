<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useStore } from '@/stores/store'
import LanguageSwitch from '@/components/LanguageSwitch.vue'
import UserMenu from '@/components/UserMenu.vue'
import logo from '@/assets/B-o-T_Logo_4c_inverted.png'
import headerBg from '@/assets/header-background.jpg'

const { t } = useI18n()
const store = useStore()
</script>

<template>
  <header>
    <!-- Utility bar — mirrors back-on-track.eu: 42px tall, #1d1e33, content
         right-aligned inside a centred ~1140px container. -->
    <div class="bg-sapphire">
      <div
        class="relative mx-auto flex h-[42px] w-full max-w-[1140px] items-center justify-end px-4 xl:px-0"
      >
        <!-- Languages sit flush to the container's right edge — the exact
             back-on-track.eu position (right edge of "Polski" at the gutter).
             The account badge is pushed just past that edge, into the outer
             gutter to its right, so it never shifts the languages inward. -->
        <LanguageSwitch />
        <!-- Always visible: reads "Guest" until the user logs in. `z-50` lifts
             this wrapper's stacking context above UserMenu's click-away catcher
             (teleported to body at z-30) — without it the transform here
             (-translate-y-1/2) traps the z-50 dropdown below the catcher, so
             clicks on the menu hit the catcher and it just closes. -->
        <div class="absolute left-full top-1/2 z-50 ml-4 -translate-y-1/2">
          <UserMenu />
        </div>
      </div>
    </div>

    <!-- Brand bar — background image with the logo, mirrors BoT's ~200px band
         (logo 350px wide, flush to the container's left edge). -->
    <div
      class="bg-cover"
      :style="{ backgroundImage: `url(${headerBg})`, backgroundPosition: '50% 48%' }"
    >
      <div
        class="mx-auto flex h-[140px] w-full max-w-[1140px] items-center px-4 md:h-[201px] xl:px-0"
      >
        <img :src="logo" :alt="t('header.logoAlt')" class="w-[240px] object-contain md:w-[350px]" />
      </div>
    </div>
  </header>
</template>
