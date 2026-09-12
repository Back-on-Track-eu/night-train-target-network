# Development image for the documentation site — the VitePress dev server,
# mirroring frontend/Dockerfile. The PRODUCTION docs are not built here:
# frontend/Dockerfile.demo builds them from the `docssrc` named context and
# copies the static bundle into its nginx image, so the deployed site stays
# one container.
#
# This exists so `docker compose up --build` brings the docs up with
# everything else. frontend/vite.config.ts proxies /docs to this container
# (DOCS_DEV_URL); without it every /docs/... URL matches vue-router's
# catch-all and silently redirects to the gallery.

FROM node:22-alpine

WORKDIR /app

COPY package.json package-lock.json ./

RUN npm install

COPY . .

EXPOSE 5174

# Host and port come from .vitepress/config.ts (host: true, strictPort), so
# a busy port fails loudly instead of moving and breaking the proxy.
CMD ["npm", "run", "dev"]
