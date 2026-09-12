<script setup lang="ts">
import { computed, ref } from 'vue'
import Avatar from 'primevue/avatar'
import AvatarGroup from 'primevue/avatargroup'
import { useLocaleFormat } from '@/composables/useLocaleFormat'

// The overlapping circle of country flags — gallery cards and the route stats
// panel share it, so the two never drift apart in size, stacking order or
// fallback behaviour.
//
// Circular flag SVGs are vendored under public/flags/ (47 of them). A country
// without one falls back to its code as a label, which is why the image error
// is tracked rather than assumed away.
const props = withDefaults(
  defineProps<{
    countries: string[]
    /** Disc diameter. The gallery card and the route stats both use the default. */
    size?: string
    /** Ring around each disc — set it to the surface the flags sit on so the
     *  overlap reads as cleanly "cut out" rather than outlined in a mismatched
     *  colour. Defaults to the card/panel surface (primary-50/5 on sapphire). */
    borderColor?: string
  }>(),
  {
    size: '1.55rem',
    borderColor: 'color-mix(in srgb, var(--p-primary-50) 5%, var(--color-sapphire))',
  },
)

const { countryName } = useLocaleFormat()

const failedFlags = ref(new Set<string>())
function markFailed(code: string) {
  failedFlags.value = new Set(failedFlags.value).add(code)
}

const flagUrl = (code: string) => `/flags/${code.toLowerCase()}.svg`

// Earlier (leftmost) flags stack above later ones — reversed z-index, since
// AvatarGroup's negative-margin overlap would otherwise put the rightmost
// flag on top.
const avatarPt = computed(() => (code: string, index: number) => ({
  root: {
    class: 'overflow-hidden rounded-full',
    style:
      `width:${props.size};height:${props.size};border:2px solid ${props.borderColor};` +
      `font-size:0.65rem;background:#2b2e4a;color:var(--p-primary-50);` +
      `position:relative;z-index:${props.countries.length - index};`,
  },
  image: { onError: () => markFailed(code) },
}))
</script>

<template>
  <AvatarGroup class="flag-group">
    <Avatar
      v-for="(c, index) in countries"
      :key="c"
      :image="failedFlags.has(c) ? undefined : flagUrl(c)"
      :label="failedFlags.has(c) ? c : undefined"
      :aria-label="countryName(c)"
      shape="circle"
      :pt="avatarPt(c, index)"
    />
  </AvatarGroup>
</template>

<style scoped>
/* Circular flag images fill their avatar disc. PrimeVue's Lara preset (unlike
   some other presets) doesn't give AvatarGroup any built-in overlap, so it's
   applied explicitly here; z-index (avatarPt, above) puts earlier flags on top. */
.flag-group :deep(.p-avatar img) {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.flag-group :deep(.p-avatar + .p-avatar) {
  margin-left: -0.6rem;
}
</style>
