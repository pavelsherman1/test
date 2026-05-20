# Ethan's Mission Control - Birthday Task Tracker
# Multi-stage build for minimal final image

FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --omit=dev --no-audit --no-fund

FROM node:20-alpine
WORKDIR /app

# Copy installed deps
COPY --from=deps /app/node_modules ./node_modules

# Copy app code
COPY package.json ./
COPY server.js ./
COPY public ./public

# Bundled seed (read-only, copied into image as data-seed/)
# Container will copy this to the volume on first boot
COPY data ./data-seed

# Create empty data dir for volume mount
RUN mkdir -p /app/data

# Non-root user
RUN addgroup -g 1001 -S nodejs && \
    adduser -S -u 1001 -G nodejs ethan && \
    chown -R ethan:nodejs /app
USER ethan

ENV NODE_ENV=production
ENV PORT=3000
ENV DATA_DIR=/app/data

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:3000/api/health || exit 1

CMD ["node", "server.js"]
