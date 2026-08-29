<script setup lang="ts">
import { ref, computed, onUnmounted } from 'vue'

const props = defineProps<{
  stops: { stop_id: string; name: string }[]
  // [originIndex, destIndex] into stops — the committed selection. Kept a full
  // leg apart (origin < dest) so there is always at least one section.
  modelValue: number[]
}>()
const emit = defineEmits<{ 'update:modelValue': [value: number[]] }>()

const trackRef = ref<HTMLElement | null>(null)
const lastIndex = computed(() => Math.max(props.stops.length - 1, 1))

// Live drag state: which handle (0 = origin, 1 = dest) and its continuous
// fraction (0..1). Null when idle. The handle follows the pointer smoothly;
// the committed value snaps to the nearest stop and updates live as the
// highlighted stop changes during the drag.
const drag = ref<{ handle: 0 | 1; frac: number } | null>(null)

function other(handle: 0 | 1): number {
  return props.modelValue[handle === 0 ? 1 : 0]
}

function pct(index: number): number {
  return (index / lastIndex.value) * 100
}

// Continuous fraction for a handle: the live drag position, or its committed
// stop otherwise. Clamped so a handle never crosses its neighbour.
function handleFrac(handle: 0 | 1): number {
  if (drag.value && drag.value.handle === handle) return drag.value.frac
  return props.modelValue[handle] / lastIndex.value
}

const originPct = computed(() => handleFrac(0) * 100)
const destPct = computed(() => handleFrac(1) * 100)
const fillLeft = computed(() => Math.min(originPct.value, destPct.value))
const fillWidth = computed(() => Math.abs(destPct.value - originPct.value))

// Highlight follows the committed selection, which updates live during a drag.
function isActive(i: number): boolean {
  return i === props.modelValue[0] || i === props.modelValue[1]
}

function clampFrac(handle: 0 | 1, frac: number): number {
  const otherFrac = other(handle) / lastIndex.value
  return handle === 0 ? Math.min(frac, otherFrac) : Math.max(frac, otherFrac)
}

// Nearest stop for a fraction, kept at least one leg away from the neighbour.
function snapIndex(handle: 0 | 1, frac: number): number {
  let n = Math.round(frac * lastIndex.value)
  n = handle === 0 ? Math.min(n, other(handle) - 1) : Math.max(n, other(handle) + 1)
  return Math.min(Math.max(n, 0), lastIndex.value)
}

function fracFromEvent(e: PointerEvent): number {
  const el = trackRef.value
  if (!el) return 0
  const rect = el.getBoundingClientRect()
  return Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width))
}

function onPointerMove(e: PointerEvent) {
  if (!drag.value) return
  const handle = drag.value.handle
  const frac = clampFrac(handle, fracFromEvent(e))
  drag.value = { handle, frac }
  const n = snapIndex(handle, frac)
  if (n !== props.modelValue[handle]) {
    const next = [...props.modelValue]
    next[handle] = n
    emit('update:modelValue', next)
  }
}

function stopListening() {
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerup', onPointerUp)
}

function onPointerUp() {
  drag.value = null // handle snaps to its committed stop
  stopListening()
}

function startDrag(handle: 0 | 1, e: PointerEvent) {
  drag.value = { handle, frac: clampFrac(handle, fracFromEvent(e)) }
  window.addEventListener('pointermove', onPointerMove)
  window.addEventListener('pointerup', onPointerUp)
}

onUnmounted(stopListening)
</script>

<template>
  <div class="px-4 pb-2 select-none">
    <!-- Track with fill, per-stop ticks, and two handles -->
    <div ref="trackRef" class="relative h-1.5 rounded-full bg-primary-50/20">
      <div
        class="absolute h-full rounded-full bg-primary-50"
        :style="{ left: `${fillLeft}%`, width: `${fillWidth}%` }"
      />
      <span
        v-for="(s, i) in stops"
        :key="`tick-${s.stop_id}`"
        class="absolute top-1/2 h-2 w-0.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-primary-50/40"
        :style="{ left: `${pct(i)}%` }"
      />
      <button
        class="absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 cursor-grab touch-none rounded-full border-2 border-sapphire-100 bg-primary-50 shadow active:cursor-grabbing"
        :style="{ left: `${originPct}%` }"
        @pointerdown.prevent="startDrag(0, $event)"
      />
      <button
        class="absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 cursor-grab touch-none rounded-full border-2 border-sapphire-100 bg-primary-50 shadow active:cursor-grabbing"
        :style="{ left: `${destPct}%` }"
        @pointerdown.prevent="startDrag(1, $event)"
      />
    </div>

    <!-- One station label per stop — angled bottom-left→top-right, its end
         anchored at the stop, itinerary-board style. Active ones highlighted. -->
    <div class="relative mt-3 h-28">
      <span
        v-for="(s, i) in stops"
        :key="`label-${s.stop_id}`"
        class="absolute top-0 origin-top-right whitespace-nowrap text-sm leading-none transition-colors"
        :class="isActive(i) ? 'font-semibold text-primary-50' : 'text-primary-50/50'"
        :style="{ left: `${pct(i)}%`, transform: 'translateX(-100%) rotate(-45deg)' }"
      >
        {{ s.name }}
      </span>
    </div>
  </div>
</template>
