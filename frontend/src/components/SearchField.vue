<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { mdiClose, mdiMagnify } from '@mdi/js'
import AppIcon from '@/components/AppIcon.vue'

// One field of the gallery search bar: the place picked, as a removable token
// with its kind's icon, or the placeholder. Always rendered inside an
// OptionSelect, whose trigger is the surrounding element — hence the
// @click.stop on the clear button, which would otherwise open the picker it
// just cleared. "From" / "To" sit inline before a pair's two fields; a single
// field leads with the search glyph instead. Fills whatever width the search
// bar gives it, and truncates a long name rather than growing.
defineProps<{
  /** Spoken always; shown only for a pair's "From" / "To". */
  label: string
  showLabel?: boolean
  /** The chosen value's display name, or null when nothing is picked yet. */
  value: string | null
  /** The picked place's kind — station, city or country. */
  icon: string
  placeholder: string
}>()

const emit = defineEmits<{ clear: [] }>()
const { t } = useI18n()
</script>

<template>
  <div
    class="group flex h-11 w-full min-w-0 items-center gap-2.5 rounded-full px-3 transition-colors hover:bg-primary-50/[0.07]"
  >
    <span v-if="showLabel" class="shrink-0 text-[13px] text-primary-50/60">{{ label }}</span>
    <template v-else>
      <AppIcon :path="mdiMagnify" :size="20" class="shrink-0 text-primary-50/60" />
      <span class="sr-only">{{ label }}</span>
    </template>
    <span
      v-if="value"
      class="flex h-8 min-w-0 items-center gap-1.5 rounded-full bg-primary-50/[0.14] pr-0.5 pl-3 text-[15px] text-primary-50"
    >
      <AppIcon :path="icon" :size="15" class="shrink-0" />
      <span class="truncate">{{ value }}</span>
      <button
        type="button"
        class="flex h-7 w-7 shrink-0 cursor-pointer items-center justify-center rounded-full text-primary-50/70 transition hover:bg-primary-50/15 hover:text-primary-50"
        :aria-label="t('gallery.search.clear', { field: label })"
        @click.stop="emit('clear')"
      >
        <AppIcon :path="mdiClose" :size="14" />
      </button>
    </span>
    <span v-else class="min-w-0 truncate text-[15px] text-primary-50/45">{{ placeholder }}</span>
  </div>
</template>
