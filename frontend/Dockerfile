FROM node:22-alpine

WORKDIR /app

# Install dependencies in a separate layer for caching.
# node_modules stays inside the container (anonymous volume in docker-compose).
COPY package*.json ./
RUN npm ci

EXPOSE 5173

# host flag also set in vite.config.ts; duplicated here as a safety net
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
