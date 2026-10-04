<script setup lang="ts">
// One entry of a product update page: a tag (what kind of change), a
// title and, in the default slot, a paragraph written in markdown. "Next"
// entries take a running number instead of the tag so the roadmap reads
// as the order it will be tackled in.
defineProps<{
  tag: 'Launched' | 'Shipped' | 'Fixed' | 'Improved' | 'Next'
  title: string
  index?: number
}>()
</script>

<template>
  <li class="changelog-entry" :class="{ 'changelog-entry--numbered': tag === 'Next' && index }">
    <span v-if="tag === 'Next' && index" class="changelog-entry__index">{{ index }}</span>
    <span v-else class="changelog-entry__tag" :class="`changelog-entry__tag--${tag.toLowerCase()}`">
      {{ tag }}
    </span>
    <div class="changelog-entry__text">
      <h3 class="changelog-entry__title">{{ title }}</h3>
      <div class="changelog-entry__body">
        <slot />
      </div>
    </div>
  </li>
</template>

<style>
/* The list the entries sit in: a plain <ul class="changelog"> in the page. */
.vp-doc ul.changelog {
  display: grid;
  gap: 14px;
  margin: 16px 0;
  padding: 0;
  list-style: none;
}

.vp-doc .changelog-entry {
  display: grid;
  grid-template-columns: 92px 1fr;
  gap: 16px;
  align-items: start;
  margin: 0;
  padding: 16px 18px;
  border: 1px solid var(--bot-hairline);
  border-radius: 12px;
  background: var(--bot-lift-5);
}

.vp-doc .changelog-entry + .changelog-entry {
  margin-top: 0;
}

.vp-doc .changelog-entry--numbered {
  grid-template-columns: 34px 1fr;
  gap: 12px;
}

.vp-doc h3.changelog-entry__title {
  margin: 0 0 4px;
  padding: 0;
  font-size: 16px;
  font-weight: 600;
  line-height: 1.4;
  letter-spacing: 0;
}

.vp-doc .changelog-entry__body p {
  margin: 0;
  color: var(--bot-ink-70);
  font-size: 15px;
  line-height: 1.6;
}

.vp-doc .changelog-entry__body p + p {
  margin-top: 8px;
}

.changelog-entry__tag {
  display: inline-block;
  margin-top: 2px;
  padding: 4px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  line-height: 1.3;
  text-align: center;
  text-transform: uppercase;
}

.changelog-entry__tag--launched,
.changelog-entry__tag--shipped {
  background: var(--bot-primary-500);
  color: #ffffff;
}

.changelog-entry__tag--fixed {
  border: 1px solid var(--bot-hairline);
  background: var(--bot-lift-10);
  color: var(--bot-ink);
}

.changelog-entry__tag--improved {
  background: color-mix(in srgb, var(--bot-primary-400) 25%, transparent);
  color: var(--bot-primary-200);
}

.changelog-entry__tag--next {
  border: 1px dashed var(--bot-primary-300);
  color: var(--bot-primary-300);
}

.changelog-entry__index {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  margin-top: 1px;
  border-radius: 50%;
  background: var(--bot-primary-500);
  color: #ffffff;
  font-size: 13px;
  font-weight: 700;
}

@media (max-width: 600px) {
  .vp-doc .changelog-entry {
    grid-template-columns: 1fr;
    gap: 8px;
  }

  .changelog-entry__tag {
    justify-self: start;
  }
}
</style>
