/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))

// Where the docs dev server lives. Overridden in the devcontainer, whose
// frontend container reaches the host-run docs server across the boundary.
const DOCS_DEV_URL = process.env.DOCS_DEV_URL ?? 'http://localhost:5174'

export default defineConfig({
  plugins: [vue(), tailwindcss()],
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
    // Run the docs alongside the app:  cd docs-site && npm run dev
    // It binds 5174 and already serves under the /docs/ base, so paths match
    // production exactly. With it not running the proxy fails loudly rather
    // than redirecting, which is the point.
    //
    // DOCS_DEV_URL exists because this dev server usually runs INSIDE the
    // frontend container, where localhost is the container. docs-site/ is not
    // mounted there, so the docs server runs on the host and the container
    // reaches it as host.docker.internal:
    //   DOCS_DEV_URL=http://host.docker.internal:5174
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
               <p>Start it:</p>
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
