/// <reference types="vitest/config" />
import { defineConfig, type ViteDevServer } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))

// Where the docs dev server lives. The devcontainer overrides it with the
// `docs` compose service name; the fallback is for a host-run `npm run dev`
// reaching the docs container's published port (or a host-run docs server).
const DOCS_DEV_URL = process.env.DOCS_DEV_URL ?? 'http://localhost:5174'

// nginx redirects a bare /docs to /docs/ in the built image (its automatic
// directory redirect, since /docs is a real directory there). The dev server
// has no such behaviour: /docs would be proxied verbatim and VitePress, which
// is mounted at the /docs/ base, answers with its "did you mean to visit
// /docs/ instead?" notice. Send the redirect ourselves so both environments
// behave the same.
//
// configureServer without a returned post-hook runs before Vite's internal
// middlewares, so this fires ahead of the proxy below.
const docsTrailingSlash = {
  name: 'docs-trailing-slash',
  configureServer(server: ViteDevServer) {
    server.middlewares.use((req, res, next) => {
      const [path, query] = (req.url ?? '').split('?')
      if (path !== '/docs') return next()
      res.writeHead(301, { Location: '/docs/' + (query ? `?${query}` : '') })
      res.end()
    })
  },
}

export default defineConfig({
  plugins: [vue(), tailwindcss(), docsTrailingSlash],
  resolve: {
    alias: [
      {
        find: /^@\//,
        replacement: resolve(__dirname, './src') + '/',
      },
    ],
  },
  server: {
    host: '0.0.0.0',
    // Ports come from backend/docker/.env via the devcontainer compose
    // overlay (FRONTEND_CONTAINER_PORT / FRONTEND_HOST_PORT); the
    // fallbacks mirror .env.example and must stay equal to it.
    port: Number(process.env.FRONTEND_CONTAINER_PORT ?? 5173),
    hmr: {
      clientPort: Number(process.env.FRONTEND_HOST_PORT ?? 5173),
    },
    // Polling is required for HMR to see edits through the Docker bind mount.
    watch: {
      usePolling: true,
    },
    // The documentation site lives at /docs/ in production, served by
    // frontend/nginx.conf ahead of the SPA fallback (see Dockerfile.demo).
    // The dev server has no such route, so without this proxy /docs/... hits
    // the SPA, matches vue-router's catch-all and silently redirects to the
    // gallery — which is exactly where every cost-factor popover's "Read the
    // full explanation" link would land a developer.
    //
    // The `docs` service in .devcontainer/docker-compose.yml runs it, so
    // bringing the stack up brings the docs up with it. It binds 5174 and
    // already serves under the /docs/ base, so paths match production
    // exactly. With it not running the proxy fails loudly rather than
    // redirecting, which is the point.
    //
    // DOCS_DEV_URL exists because this dev server usually runs INSIDE the
    // frontend container, where localhost is the container, not the host:
    //   DOCS_DEV_URL=http://docs:5174
    proxy: {
      '/docs': {
        target: DOCS_DEV_URL,
        changeOrigin: true,
        // Without this the failure is an ECONNREFUSED AggregateError stack
        // trace in the terminal and a dead tab — which does not tell you the
        // one thing you need to know. Answer with the command instead.
        configure: (proxy) => {
          proxy.on('error', (_err, _req, res) => {
            if (!('writeHead' in res) || res.headersSent) return
            res.writeHead(503, { 'Content-Type': 'text/html; charset=utf-8' })
            res.end(
              `<!doctype html><meta charset="utf-8">
               <title>Docs dev server not running</title>
               <style>body{font:16px/1.6 system-ui;margin:4rem auto;max-width:38rem;padding:0 1rem}
               code{background:#eee;padding:.15em .4em;border-radius:4px}</style>
               <h1>The documentation dev server isn't running</h1>
               <p>In the built image nginx serves <code>/docs/</code>. In development
               it is proxied to a separate VitePress server, which is not answering
               at <code>${DOCS_DEV_URL}</code>.</p>
               <p>It normally comes up with the stack, as the <code>docs</code>
               service. Start just that one:</p>
               <pre><code>docker compose -f backend/docker/docker-compose.yml -f .devcontainer/docker-compose.yml up -d docs</code></pre>
               <p>Or run it outside Docker:</p>
               <pre><code>cd docs-site &amp;&amp; npm run dev</code></pre>
               <p>Then reload. See the "Documentation site" section in CLAUDE.md.</p>`,
            )
          })
        },
      },
    },
  },
  // Unit tests cover pure logic in src/lib only (node environment, no DOM) —
  // components are not mounted, so no jsdom/@vue/test-utils is pulled in.
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
})
