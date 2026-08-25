<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { mdiClose } from '@mdi/js'
import AppIcon from '@/components/AppIcon.vue'

// One field of the gallery search bar (From / To / Station / Country / the two
// relation ends). Always rendered inside a StopSelect or CountrySelect, whose
// trigger is the surrounding element — hence the @click.stop on the clear
// button, which would otherwise open the picker it just cleared.
//
// Fixed width, so picking a long station name no longer resizes the field and
// with it the whole pill; `group` so the hover target is the field's full box
// rather than just the glyphs of the name sitting in it.
defineProps<{
  label: string
  /** The chosen value's display name, or null when nothing is picked yet. */
  value: string | null
  placeholder: string
}>()

const emit = defineEmits<{ clear: [] }>()
const { t } = useI18n()
</script>

<template>
  <div
    class="group flex w-48 flex-col rounded-full px-4 py-1.5 transition-colors hover:bg-primary-50/10"
  >
    <span class="text-xs font-semibold text-primary-50">{{ label }}</span>
    <span class="flex items-center gap-1">
      <span
        class="min-w-0 flex-1 truncate text-sm transition-colors group-hover:text-primary-50/80"
        :class="value ? 'text-primary-50' : 'text-primary-50/40'"
      >
        {{ value ?? placeholder }}
      </span>
      <button
        v-if="value"
        type="button"
        class="shrink-0 cursor-pointer rounded-full p-0.5 text-primary-50/50 transition hover:bg-primary-50/15 hover:text-primary-50"
        :aria-label="t('gallery.search.clear', { field: label })"
        @click.stop="emit('clear')"
      >
        <AppIcon :path="mdiClose" :size="14" />
      </button>
    </span>
  </div>
</template>
