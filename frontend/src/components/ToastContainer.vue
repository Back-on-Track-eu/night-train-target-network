<script setup lang="ts">
import { useToastStore } from '@/stores/toastStore'
import Toast from '@/components/Toast.vue'

const toastStore = useToastStore()
</script>

<template>
  <Teleport to="body">
    <div
      class="pointer-events-none fixed left-1/2 top-6 z-[60] w-full max-w-md -translate-x-1/2 px-4"
    >
      <TransitionGroup name="toast" tag="div" class="toast-stack flex flex-col gap-2">
        <Toast
          v-for="toast in toastStore.toasts"
          :key="toast.id"
          :toast="toast"
          class="pointer-events-auto"
          @dismiss="toastStore.dismissToast"
        />
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<style scoped>
.toast-move,
.toast-enter-active,
.toast-leave-active {
  transition: all 0.25s ease;
}
.toast-enter-from {
  opacity: 0;
  transform: translateY(-16px);
}
.toast-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}
.toast-leave-active {
  position: absolute;
  width: 100%;
}
.toast-stack {
  position: relative;
}
</style>
