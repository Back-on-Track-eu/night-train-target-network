<script setup lang="ts">
import { useI18n } from 'vue-i18n'

// The ownership pill next to the Gallery link: whose proposal this is and what
// a change does to it — the copy-on-edit mechanism in words. An own proposal
// saves automatically, someone else's is never overwritten (ProposalViewport's
// ownsProposal), so any change becomes the visitor's own copy. Nothing to
// click; the behaviour already exists, this just stops it being a surprise.
//
// A status dot rather than an icon: the two states differ in kind, not in
// action, and a colour reads faster than two glyphs a user has to tell apart.
// Green = saved to your own; gold = the same gold every "this is not the
// default / your change lands elsewhere" surface uses (the scenario card, the
// expert-timetable pill), so the copy state is recognisable before it is read.
defineProps<{
  owned: boolean
  authorName: string | null
}>()

const { t } = useI18n()
</script>

<template>
  <p class="own-pill" :class="owned ? 'is-own' : 'is-copy'">
    <i aria-hidden="true" />
    <b>{{
      owned
        ? t('proposal.ownership.ownLabel')
        : t('proposal.ownership.copyLabel', { name: authorName ?? t('proposal.ownership.someone') })
    }}</b>
    <span>· {{ owned ? t('proposal.ownership.ownNote') : t('proposal.ownership.copyNote') }}</span>
  </p>
</template>

<style scoped>
.own-pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 14px;
  border-radius: 99px;
  border: 1px solid color-mix(in srgb, var(--color-primary-50) 15%, transparent);
  background: var(--color-sapphire-200);
  font-size: 12px;
  color: color-mix(in srgb, var(--color-primary-50) 60%, transparent);
}

.own-pill b {
  font-weight: 600;
  color: var(--color-primary-50);
}

.own-pill i {
  width: 8px;
  height: 8px;
  flex-shrink: 0;
  border-radius: 50%;
}

.is-own i {
  background: var(--color-yellow-green);
}

/* The copy state carries the gold wash, so it reads as "not your default
   workspace" at a glance — same treatment as the scenario card. */
.is-copy {
  border-color: color-mix(in srgb, #d4a54a 50%, transparent);
  background: color-mix(in srgb, #d4a54a 16%, transparent);
}

.is-copy i {
  background: #d4a54a;
}
</style>
