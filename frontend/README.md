# Night Train — Frontend

Vue 3 SPA for the Night Train Target Network economic model.

---

## Tech Stack

| Tool         | Version         | Role                                            |
| ------------ | --------------- | ----------------------------------------------- |
| Vue 3        | ^3.5            | UI framework (`<script setup>` Composition API) |
| Vite         | ^8.0            | Dev server + bundler                            |
| TypeScript   | ^5.8 (strict)   | Type safety                                     |
| Pinia        | ^2.3            | State management                                |
| PrimeVue     | ^4.3            | UI component library (Lara theme)               |
| Tailwind CSS | v4              | Utility-first CSS (`@tailwindcss/vite` plugin)  |
| vue-i18n     | ^11             | Internationalisation                            |
| ESLint       | 9 (flat config) | Linting                                         |
| Prettier     | ^3.5            | Formatting                                      |

---

## Dev Setup

### Docker (recommended)

All three services start together:

```bash
# from repo root
docker compose -f .devcontainer/docker-compose.yml up --build
```

- **Frontend**: http://localhost:5173 — Vite HMR, edits reflect instantly without rebuild
- **Backend API**: http://localhost:5000
- **OpenRailRouting**: http://localhost:8989

### Without Docker

Requires Node 22+ and the backend running separately.

```bash
cd frontend
npm install
npm run dev
```

---

## Project Structure

```
frontend/
├── index.html               # Vite entry HTML
├── package.json
├── tsconfig.json            # Reference aggregator
├── tsconfig.app.json        # src/ TypeScript config (strict)
├── tsconfig.node.json       # Config files (vite.config.ts etc.)
├── vite.config.ts
├── eslint.config.ts         # ESLint 9 flat config
├── .prettierrc
└── src/
    ├── main.ts              # App bootstrap — plugin order matters
    ├── App.vue              # Root component
    ├── style.css            # Tailwind + CSS layer declarations
    ├── env.d.ts             # Vite env type shims
    ├── types/
    │   └── api.ts           # TypeScript types for backend responses
    ├── i18n/
    │   ├── index.ts         # vue-i18n setup
    │   └── locales/
    │       └── en.json      # English strings (add de.json etc. here)
    ├── stores/
    │   └── store.ts     # Pinia store
    └── components/
        └── DataStatus.vue   # Connection test UI component
```

---

## Available Scripts

| Command                | Description                          |
| ---------------------- | ------------------------------------ |
| `npm run dev`          | Start Vite dev server with HMR       |
| `npm run build`        | Type-check then build for production |
| `npm run type-check`   | `vue-tsc --noEmit` (used in CI)      |
| `npm run lint`         | ESLint report                        |
| `npm run lint:fix`     | ESLint auto-fix                      |
| `npm run format`       | Prettier write                       |
| `npm run format:check` | Prettier check (used in CI)          |

---

## Pre-commit Hooks

Hooks run Black (backend) and Prettier (frontend) automatically on every `git commit`.

**Install once per machine:**

```bash
pip install pre-commit
pre-commit install
```

**Run manually on all files:**

```bash
pre-commit run --all-files
```

Hooks are defined in `/.pre-commit-config.yaml` at the repo root. They mirror the
`prettier-check` and `black-check` CI jobs — if CI fails on formatting, run
`npm run format` (frontend) or `black backend/` (backend) and recommit.

---

## Icons

Use the `AppIcon` component with path constants from `@mdi/js`:

```vue
<script setup lang="ts">
import AppIcon from '@/components/AppIcon.vue'
import { mdiMagnify } from '@mdi/js'
</script>

<template>
  <AppIcon :path="mdiMagnify" :size="20" color="white" />
</template>
```

Props: `path` (required), `size` (px, default `24`), `color` (default `currentColor`).

Do **not** use `<i class="mdi mdi-*">` CSS font classes — `@mdi/js` is tree-shakeable and avoids loading the full icon font.

---

## CSS Layer Architecture

PrimeVue 4 and Tailwind v4 coexist via CSS cascade layers. The layer order is declared
in two places that must stay in sync:

- `src/style.css`: `@layer tailwind-base, primevue, tailwind-utilities;`
- `src/main.ts` PrimeVue config: `cssLayer.order: 'tailwind-base, primevue, tailwind-utilities'`

This ensures Tailwind utility classes always win over PrimeVue component styles.
