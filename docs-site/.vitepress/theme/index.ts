import DefaultTheme from 'vitepress/theme'
import type { Theme } from 'vitepress'
import Layout from './Layout.vue'
import FeedbackForm from './components/FeedbackForm.vue'
import GeneralFeedbackForm from './components/GeneralFeedbackForm.vue'
import ReportCard from './components/ReportCard.vue'
import ReportTiles from './components/ReportTiles.vue'
import ReportBars from './components/ReportBars.vue'
import ReportMap from './components/ReportMap.vue'
import ReportQuotes from './components/ReportQuotes.vue'
import ReportChips from './components/ReportChips.vue'
import ChangelogEntry from './components/ChangelogEntry.vue'
import ActionDock from './components/ActionDock.vue'
import 'katex/dist/katex.min.css'
import './custom.css'

// Registered globally so any page can end with <FeedbackForm /> without an
// import — the emitted cost pages include it, and hand-written pages use
// the same tag. Renaming it breaks all 30 generated pages, which carry the
// tag verbatim (see backend/scripts/model_docs/render_site.py).
//
// GeneralFeedbackForm is used on one page (feedback.md) and is registered the
// same way rather than imported there: a markdown file importing from
// ./.vitepress/theme/components/ is a path that breaks the moment the page
// moves into a folder.
//
// The Report* components, ChangelogEntry and ActionDock are the building
// blocks of the report and product-update pages (reports/, updates/ —
// see reports/README.md). Global for the same reason: those pages live in
// folders and are written as markdown around the tags.
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
    app.component('GeneralFeedbackForm', GeneralFeedbackForm)
    app.component('ReportCard', ReportCard)
    app.component('ReportTiles', ReportTiles)
    app.component('ReportBars', ReportBars)
    app.component('ReportMap', ReportMap)
    app.component('ReportQuotes', ReportQuotes)
    app.component('ReportChips', ReportChips)
    app.component('ChangelogEntry', ChangelogEntry)
    app.component('ActionDock', ActionDock)
  },
} satisfies Theme
