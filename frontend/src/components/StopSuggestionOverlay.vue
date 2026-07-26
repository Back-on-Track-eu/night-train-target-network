<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { SuggestedStop } from '@/types/api'
import AppIcon from '@/components/AppIcon.vue'
import { mdiClose, mdiCheck } from '@mdi/js'

defineProps<{ suggestions: SuggestedStop[] }>()
const emit = defineEmits<{ confirm: [selectedIds: string[]]; cancel: [] }>()

const { t } = useI18n()

// Default: nothing selected — the user opts stops in explicitly (the whole
// point of this overlay is that intermediate stops are no longer added
// automatically).
const selected = ref<Set<string>>(new Set())

function toggle(stopId: string) {
  const next = new Set(selected.value)
  if (next.has(stopId)) next.delete(stopId)
  else next.add(stopId)
  selected.value = next
}

const selectedCount = computed(() => selected.value.size)

function confirm() {
  emit('confirm', [...selected.value])
}
</script>

<template>
  <Teleport to="body">
    <div
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm"
      @click.self="emit('cancel')"
    >
      <div
        class="suggestion-card flex max-h-[85vh] w-full max-w-md flex-col overflow-hidden rounded-2xl shadow-2xl"
      >
        <!-- Header -->
        <div class="flex items-start justify-between gap-3 px-6 pb-4 pt-6">
          <div class="flex flex-col gap-1">
            <h2 class="text-xl font-bold leading-tight text-primary-50">
              {{ t('proposal.suggestions.title') }}
            </h2>
            <p class="text-sm text-primary-50/60">
              {{ t('proposal.suggestions.subtitle') }}
            </p>
          </div>
          <button
            class="mt-0.5 shrink-0 cursor-pointer text-primary-50/60 transition-colors hover:text-primary-50"
            :aria-label="t('proposal.suggestions.skip')"
            @click="emit('cancel')"
          >
            <AppIcon :path="mdiClose" :size="22" />
          </button>
        </div>

        <!-- Suggestion list -->
        <div
          class="flex-1 overflow-y-auto px-3 py-1"
          style="
            scrollbar-width: thin;
            scrollbar-color: color-mix(in srgb, var(--p-primary-50) 50%, transparent) transparent;
          "
        >
          <button
            v-for="stop in suggestions"
            :key="stop.stop_id"
            class="flex w-full items-center gap-3 rounded-xl px-3 py-3 text-left transition-colors hover:bg-primary-50/5"
            @click="toggle(stop.stop_id)"
          >
            <!-- Checkbox indicator -->
            <span
              class="flex h-5 w-5 shrink-0 items-center justify-center rounded-md border transition-colors"
              :class="
                selected.has(stop.stop_id)
                  ? 'border-primary-50 bg-primary-50'
                  : 'border-primary-50/40 bg-transparent'
              "
            >
              <AppIcon
                v-if="selected.has(stop.stop_id)"
                :path="mdiCheck"
                :size="14"
                color="#23263d"
              />
            </span>

            <span class="flex flex-1 flex-col">
              <span class="text-base font-semibold leading-tight text-primary-50">
                {{ stop.stop_name }}
              </span>
              <span class="text-xs text-primary-50/50">{{ stop.country_code }}</span>
            </span>

            <span class="shrink-0 text-sm tabular-nums text-primary-50/70">
              {{
                t('proposal.suggestions.addedTime', { minutes: Math.round(stop.added_time_min) })
              }}
            </span>
          </button>
        </div>

        <!-- Footer -->
        <div
          class="flex items-center justify-between gap-3 px-6 pb-6 pt-4"
          style="border-top: 1px solid color-mix(in srgb, var(--p-primary-50) 15%, transparent)"
        >
          <span class="text-sm text-primary-50/60">
            {{
              selectedCount === 0
                ? t('proposal.suggestions.none')
                : t('proposal.suggestions.selectedCount', selectedCount)
            }}
          </span>
          <button
            class="cursor-pointer rounded-full bg-primary-50/10 px-6 py-2 text-sm text-primary-50 transition-colors hover:bg-primary-50/20"
            @click="confirm"
          >
            {{
              selectedCount === 0
                ? t('proposal.suggestions.confirmNone')
                : t('proposal.suggestions.confirm', selectedCount)
            }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.suggestion-card {
  background: #23263d;
  border: 1px solid var(--p-primary-50);
}
.suggestion-card *::-webkit-scrollbar {
  width: 5px;
}
.suggestion-card *::-webkit-scrollbar-track {
  background: transparent;
}
.suggestion-card *::-webkit-scrollbar-thumb {
  background: color-mix(in srgb, var(--p-primary-50) 50%, transparent);
  border-radius: 99px;
}
</style>
