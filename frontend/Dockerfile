# Stage 1: Build
FROM node:22-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# Stage 2: Serve (non-root nginx)
FROM nginxinc/nginx-unprivileged:alpine

LABEL org.opencontainers.image.title="geolens-frontend"
LABEL org.opencontainers.image.description="PostGIS-native GIS data catalog frontend"
LABEL org.opencontainers.image.licenses="Apache-2.0"

COPY --from=builder --chown=nginx:nginx /app/dist /usr/share/nginx/html
COPY --from=builder --chown=nginx:nginx /app/public/env-config.template.js /usr/share/nginx/html/env-config.template.js
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --chmod=755 docker-entrypoint.sh /docker-entrypoint.sh

ENTRYPOINT ["/docker-entrypoint.sh"]

HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:8080/ || exit 1

EXPOSE 8080
