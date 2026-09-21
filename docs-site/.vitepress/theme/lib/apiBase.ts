// The one home for the API origin on the documentation site — the mirror of
// frontend/src/lib/apiBase.ts, and for the same reason: two components now
// post to the API from here, and a base each is a base that drifts.
//
// Empty by default, i.e. same origin. In production the docs are served at
// /docs/ by the app's own nginx, so /api/feedback reaches the api container
// with no CORS and no configuration. In development the docs run as their own
// VitePress server behind the app's /docs proxy, and that dev server has no
// /api route — set VITE_API_BASE_URL=http://localhost:5050 (the devcontainer
// api) to submit a form while developing.
export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? ''

export function apiUrl(path: string): string {
  return `${API_BASE_URL}${path}`
}
