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
      // Overridden by the compose docs service (DOCS_CONTAINER_PORT); the
      // fallback mirrors backend/docker/.env.example and must stay equal to it.
      port: Number(process.env.DOCS_CONTAINER_PORT ?? 5174),
      strictPort: true,
      host: true,
      // The app's dev server proxies /docs here with changeOrigin, so the
      // Host arriving is whatever it used to reach us: the `docs` compose
      // service name from the frontend container, or host.docker.internal
      // when the docs server runs on the host instead. Vite's host check
      // rejects either with a 403 unless listed. Dev-only; the built site is
      // static and served by nginx.
      allowedHosts: ['localhost', 'docs', 'host.docker.internal'],
      // Polling is required for HMR to see edits through the Docker bind mount.
      watch: { usePolling: true },
    },
  },

  lang: 'en-GB',
  title: 'Night Train Target Network',
  description:
    'Back-on-Track’s proposal for a European night train network, and the model ' +
    'behind it: what a route costs, where the data comes from, and what it assumes.',
  cleanUrls: true,

  // The app has exactly one look: a fixed dark page, no light mode and no
  // toggle (frontend/src/style.css:3-5). Offering a light theme here would
  // mean inventing a second palette the brand does not have, so the switch
  // is removed rather than left to produce something unbranded.
  appearance: 'force-dark',

  // Tab icon and link preview, mirroring frontend/index.html. The app inlines
  // these as data URIs; here they are files under public/, so BASE has to be
  // applied by hand — head entries are emitted verbatim.
  head: [
    ['link', { rel: 'icon', type: 'image/jpeg', sizes: '32x32', href: `${BASE}favicon-32.jpg` }],
    ['link', { rel: 'icon', type: 'image/jpeg', sizes: '192x192', href: `${BASE}favicon-192.jpg` }],
    ['link', { rel: 'apple-touch-icon', href: `${BASE}favicon-192.jpg` }],
    ['meta', { name: 'theme-color', content: '#1d1e33' }],
    ['meta', { property: 'og:type', content: 'website' }],
    ['meta', { property: 'og:site_name', content: 'Back-on-Track Target Network' }],
    ['meta', { property: 'og:title', content: 'Night Train Target Network' }],
    [
      'meta',
      {
        property: 'og:description',
        content:
          'Every number the night train tool produces, and where it comes from: ' +
          'the data, the formulas, and the assumptions still standing in for ' +
          'measurements.',
      },
    ],
  ],

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
      { text: 'About', link: '/' },
      { text: 'Data sources', link: '/sources/' },
      { text: 'Costs', link: '/cost/total-cost' },
      // "Open the tool" used to sit here. It is in the masthead now
      // (.vitepress/theme/components/SiteBrandBar.vue), which is where the
      // app puts its own outbound links.
    ],

    // One flat sidebar for every page, including the landing one: the site
    // has no home layout, so the tree is visible wherever a reader lands.
    //
    // The reference pages (formulas, parameters, versions, changelog,
    // standard values, emission factors) are deliberately absent here. They
    // are still built and still published: every input row of every cost
    // page's legend links into them, 122 links in all. They are reached from
    // a formula rather than browsed.
    sidebar: [
      // About is the landing page, so it sits above the groups rather than
      // heading a group of one.
      { text: 'About', link: '/' },
      {
        text: 'The model',
        items: [
          { text: 'Data sources', link: '/sources/' },
          { text: 'Route planning', link: '/routing' },
          { text: 'Stop catalogue', link: '/stops' },
          { text: 'Demand and revenue', link: '/demand' },
          { text: 'Emissions', link: '/emissions' },
          { text: 'Known gaps', link: '/not-modelled' },
        ],
      },
      // Generated from CALC_TREE — see render_site.py::render_sidebar.
      { text: 'Costs', items: costSidebar },
      {
        text: 'Calibration',
        items: [
          { text: 'Track access', link: '/methodology/track-access' },
          { text: 'Energy', link: '/methodology/energy' },
          { text: 'Traction electricity', link: '/methodology/energy-pricing' },
          { text: 'Shunting and stabling', link: '/methodology/facility' },
          { text: 'Rolling stock', link: '/methodology/compositions' },
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
