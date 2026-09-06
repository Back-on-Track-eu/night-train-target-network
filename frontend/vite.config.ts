/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))

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
        target: process.env.DOCS_DEV_URL ?? 'http://localhost:5174',
        changeOrigin: true,
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
