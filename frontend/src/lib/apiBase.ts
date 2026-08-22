// The one home for the API origin. Same-origin by default in production builds
// (deploy bakes VITE_API_BASE_URL='' and Caddy routes /api/* to the api
// container); the localhost fallback is for bare local dev against the
// devcontainer stack, where the frontend and api are different origins.
export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:5050'
