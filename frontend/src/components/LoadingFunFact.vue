<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'

// Rotating Back-on-Track tidbits shown while a route is being evaluated — the
// calc is the one genuinely long wait in the app, so the time is spent saying
// what the project is actually for.
//
// Every tidbit pairs a fact with the DEMAND Back-on-Track attaches to it:
// back-on-track.eu is a lobbying effort for more night trains, not a trivia
// site, and a fact with the ask stripped off misrepresents the source. Copy and
// figures live in en.json under proposal.funFacts.
//
// Keys, not an array, so the strings stay addressable by name for translators
// and this list can be reordered without renumbering anything. Facts are keyed
// here rather than read with tm() so every lookup is a plain t() call.
const FACT_KEYS = [
  'targetNetwork',
  'europeanSleeper',
  'sevenInTen',
  'carpatia',
  'euEmissions',
  'flyLess',
  'climate',
  'parisBerlin',
  'aviation',
  'rollingStock',
  'reuse',
  'network',
] as const

const ROTATE_MS = 9000
const BOT_URL = 'https://back-on-track.eu/'

const { t } = useI18n()

// Random start so a user who evaluates several routes doesn't reread the same
// opener each time; from there it advances in order, so one wait never repeats
// a tidbit.
const index = ref(Math.floor(Math.random() * FACT_KEYS.length))
let timer: ReturnType<typeof setInterval> | undefined

onMounted(() => {
  timer = setInterval(() => {
    index.value = (index.value + 1) % FACT_KEYS.length
  }, ROTATE_MS)
})
onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})

const current = computed(() => {
  const key = FACT_KEYS[index.value]
  return {
    key,
    fact: t(`proposal.funFacts.${key}.fact`),
    demand: t(`proposal.funFacts.${key}.demand`),
  }
})
</script>

<template>
  <div class="flex max-w-xs flex-col gap-1.5 border-t border-primary-50/15 pt-3 text-left">
    <span class="text-[0.65rem] font-bold uppercase tracking-wider text-primary-50/50">
      {{ t('proposal.funFacts.label') }}
    </span>
    <!-- key on the tidbit so each rotation is a fresh element and the fade runs -->
    <Transition name="fact" mode="out-in">
      <div :key="current.key" class="flex flex-col gap-1.5">
        <p class="text-xs leading-relaxed text-primary-50/90">{{ current.fact }}</p>
        <p class="text-xs leading-relaxed text-primary-50/60">
          <span class="font-semibold text-primary-50/80"
            >{{ t('proposal.funFacts.demandLabel') }}
          </span>
          {{ current.demand }}
        </p>
      </div>
    </Transition>
    <a
      :href="BOT_URL"
      target="_blank"
      rel="noopener noreferrer"
      class="text-[0.7rem] text-primary-50/60 underline underline-offset-2 transition hover:text-primary-50"
    >
      {{ t('proposal.funFacts.linkLabel') }}
    </a>
  </div>
</template>

<style scoped>
/* Opacity only — a transform would jitter the panel it sits in. */
.fact-enter-active,
.fact-leave-active {
  transition: opacity 0.4s ease;
}
.fact-enter-from,
.fact-leave-to {
  opacity: 0;
}
</style>
