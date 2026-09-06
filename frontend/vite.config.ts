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
  },
  // Unit tests cover pure logic in src/lib only (node environment, no DOM) —
  // components are not mounted, so no jsdom/@vue/test-utils is pulled in.
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
})
