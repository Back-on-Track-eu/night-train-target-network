import { defineConfig } from 'vitepress'
import katexModule from '@vscode/markdown-it-katex'
import costSidebar from './generated-sidebar.json'

// Served from a /docs/ subpath of the same origin as the app (see
// frontend/nginx.conf). The SPA hardcodes base '/' and claims the whole
// origin's history space, so this base is load-bearing: without it both
// sites emit absolute /assets/* URLs and collide.
const BASE = '/docs/'

export default defineConfig({
  base: BASE,
  lang: 'en-GB',
  title: 'How the model works',
  description:
    'How the European night train network tool computes what a route would cost, ' +
    'where its data comes from, and what it assumes.',
  cleanUrls: true,

  // Fail the build on a link to a page that does not exist. The emitter
  // generates most links from the model registries, so a dead one means a
  // formula moved without its page moving with it.
  ignoreDeadLinks: false,

  // Locale scaffolding: English only for now, but the routing is in place
  // so a second language can be added without changing a single URL.
  locales: {
    root: { label: 'English', lang: 'en-GB' },
  },

  themeConfig: {
    search: { provider: 'local' },

    nav: [
      { text: 'Start here', link: '/' },
      { text: 'Data sources', link: '/sources/' },
      { text: 'What it costs', link: '/cost/total-cost' },
      { text: 'Reference', link: '/reference/versions' },
      { text: 'Open the tool', link: '/../' },
    ],

    sidebar: [
      {
        text: 'Start here',
        items: [
          { text: 'What this tool computes', link: '/' },
          { text: 'How to read our numbers', link: '/reading-the-numbers' },
          { text: "What we don't yet model", link: '/not-modelled' },
        ],
      },
      {
        text: 'Where the numbers come from',
        items: [
          { text: 'Data sources', link: '/sources/' },
          { text: 'How a route is planned', link: '/routing' },
          { text: 'The stop catalogue', link: '/stops' },
          { text: 'Revenue and demand', link: '/demand' },
          { text: 'Emissions', link: '/emissions' },
          { text: 'Scenarios', link: '/scenarios' },
        ],
      },
      // Generated from CALC_TREE — see render_site.py::render_sidebar.
      { text: 'What it costs', items: costSidebar },
      {
        text: 'How it was calibrated',
        items: [
          { text: 'Track access', link: '/methodology/track-access' },
          { text: 'Energy consumption', link: '/methodology/energy' },
          { text: 'Traction electricity', link: '/methodology/energy-pricing' },
          { text: 'Shunting and stabling', link: '/methodology/facility' },
          { text: 'Terrain and buffers', link: '/methodology/route-context' },
          { text: 'Rolling stock', link: '/methodology/compositions' },
        ],
      },
      {
        text: 'Reference',
        items: [
          { text: 'Model versions', link: '/reference/versions' },
          { text: 'What changed', link: '/reference/changelog' },
          { text: 'All formulas', link: '/reference/formulas' },
          { text: 'Parameter reference', link: '/reference/parameters' },
          { text: 'Standard values', link: '/reference/standard-values' },
          { text: 'Emission factors', link: '/reference/emission-factors' },
        ],
      },
    ],

    outline: { level: [2, 3] },

    socialLinks: [
      { icon: 'github', link: 'https://github.com/Back-on-Track-eu/night-train-target-network' },
    ],

    footer: {
      message:
        'Published by Back-on-Track. Every number on this site is generated from the ' +
        'model that produces the tool’s results.',
    },

    editLink: {
      pattern:
        'https://github.com/Back-on-Track-eu/night-train-target-network/edit/staging/docs-site/:path',
      text: 'Suggest a correction',
    },
  },

  markdown: {
    // KaTeX, not VitePress's default MathJax: the backend's LaTeX was written
    // against KaTeX (it is what the app's cost popover rendered), and one
    // renderer across the project means one dialect to stay compatible with.
    config: (md) => {
      // The package double-wraps its CJS export under ESM, so the plugin
      // function is one .default deeper than the import suggests.
      const katex = (katexModule as unknown as { default: unknown }).default ?? katexModule
      md.use(katex as Parameters<typeof md.use>[0])
    },
    lineNumbers: false,
  },
})
