import DefaultTheme from 'vitepress/theme'
import type { Theme } from 'vitepress'
import Layout from './Layout.vue'
import FeedbackForm from './components/FeedbackForm.vue'
import 'katex/dist/katex.min.css'
import './custom.css'

// Registered globally so any page can end with <FeedbackForm /> without an
// import — the emitted cost pages include it, and hand-written pages use
// the same tag. Renaming it breaks all 30 generated pages, which carry the
// tag verbatim (see backend/scripts/model_docs/render_site.py).
//
// Layout extends the default one with the Back-on-Track masthead; custom.css
// carries the brand tokens. Neither touches page content.
//
// katex.min.css is not optional. markdown-it-katex emits BOTH a visual
// .katex-html layer and a .katex-mathml copy for screen readers; the
// stylesheet is what clips the MathML out of sight (clip-path: inset(50%)),
// and what supplies the math fonts. Without it every formula renders twice —
// once typeset, once as a run-on line of plain text. It goes before
// custom.css so the brand rules there win.
export default {
  extends: DefaultTheme,
  Layout,
  enhanceApp({ app }) {
    app.component('FeedbackForm', FeedbackForm)
  },
} satisfies Theme
