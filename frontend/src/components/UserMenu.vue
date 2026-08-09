<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useStore } from '@/stores/store'
import { useToastStore } from '@/stores/toastStore'
import AppIcon from '@/components/AppIcon.vue'
import { mdiAccountCircle } from '@mdi/js'

const { t } = useI18n()
const store = useStore()
const toastStore = useToastStore()

const open = ref(false)

function close() {
  open.value = false
}
function onLogout() {
  store.logout()
  toastStore.addToast('success', t('toast.logoutSuccess'))
  close()
}
function onLogin() {
  // Reuse the shared modal in standalone (non-evaluation) mode.
  store.openAuthModal({ context: 'standalone' })
  close()
}
</script>

<template>
  <!-- `relative` establishes the positioning context for the dropdown's
       `absolute right-0` below — this chip now sits inline in AppHeader's
       flex row rather than being `fixed`-positioned by its consumer. -->
  <div class="relative">
    <button
      type="button"
      class="flex cursor-pointer items-center gap-2 rounded-full bg-primary-50/5 px-3 py-1.5 text-primary-50 transition hover:bg-primary-50/10"
      @click="open = !open"
    >
      <span class="text-sm font-semibold leading-none">
        {{ store.authChoice === 'user' ? store.username : t('user.guest') }}
      </span>
      <AppIcon :path="mdiAccountCircle" :size="22" />
    </button>

    <!-- Click-away catcher: below the chip (z-40) and menu (z-50), above content. -->
    <Teleport to="body">
      <div v-if="open" class="fixed inset-0 z-30" @click="close" />
    </Teleport>

    <div
      v-if="open"
      class="user-menu absolute right-0 z-50 mt-2 flex min-w-40 flex-col overflow-hidden rounded-xl shadow-xl"
    >
      <!-- Not-yet-decided and guest visitors have nothing to log out of — only
           offer login/register. A registered user only gets log out. -->
      <button
        v-if="store.authChoice !== 'user'"
        type="button"
        class="cursor-pointer px-4 py-2.5 text-left text-sm text-primary-50 transition hover:bg-primary-50/10"
        @click="onLogin"
      >
        {{ t('user.login') }}
      </button>
      <button
        v-else
        type="button"
        class="cursor-pointer px-4 py-2.5 text-left text-sm text-primary-50 transition hover:bg-primary-50/10"
        @click="onLogout"
      >
        {{ t('user.logout') }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.user-menu {
  background: #23263d;
  border: 1px solid color-mix(in srgb, var(--p-primary-50) 20%, transparent);
}
</style>
