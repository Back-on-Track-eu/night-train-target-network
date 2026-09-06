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

  // 5173 is the app's dev server; the two must not collide. frontend's Vite
  // proxies /docs here (DOCS_DEV_URL) so the popover's docs links resolve in
  // development exactly as they do behind nginx in production. strictPort so
  // a busy 5174 fails loudly instead of silently moving and breaking that.
  //
  // host: true — the app's dev server usually runs in a container and reaches
  // this one across the boundary, which a loopback-only bind would refuse.
  vite: {
    server: {
      port: 5174,
      strictPort: true,
      host: true,
      // The app's dev server proxies /docs here with changeOrigin, so the
      // Host arriving is whatever it used to reach us — host.docker.internal
      // from inside the frontend container. Vite's host check rejects that
      // with a 403 unless it is listed. Dev-only; the built site is static
      // and served by nginx.
      allowedHosts: ['localhost', 'host.docker.internal'],
    },
  },

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
      // '/../' would be rendered as href="/docs/../". A browser normalises
      // that to "/", but VitePress's client-side router intercepts
      // same-origin links first and tries to resolve it as a page — which is
      // a 404. target: '_blank' makes the router skip it and hands the URL to
      // the browser, which resolves it correctly. The app lives at the root
      // of this same origin; its absolute URL differs per environment, so it
      // cannot simply be hardcoded here.
      { text: 'Open the tool', link: '/../', target: '_blank' },
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
