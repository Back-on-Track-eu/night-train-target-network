import DefaultTheme from 'vitepress/theme'
import type { Theme } from 'vitepress'
import FeedbackForm from './components/FeedbackForm.vue'

// Registered globally so any page can end with <FeedbackForm /> without an
// import — the emitted cost pages include it, and hand-written pages use
// the same tag.
export default {
  extends: DefaultTheme,
  enhanceApp({ app }) {
    app.component('FeedbackForm', FeedbackForm)
  },
} satisfies Theme
