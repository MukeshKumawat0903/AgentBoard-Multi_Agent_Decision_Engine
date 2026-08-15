# ============================================================
# Stage 1 — deps: install node_modules
# ============================================================
FROM node:20-alpine AS deps

WORKDIR /app

# Copy package manifests only (cache-friendly layer)
COPY package.json package-lock.json ./

# Install production + dev deps (dev deps needed for next build)
RUN npm ci --legacy-peer-deps


# ============================================================
# Stage 2 — builder: compile the Next.js app
# ============================================================
FROM node:20-alpine AS builder

WORKDIR /app

# Bring in dependencies from previous stage
COPY --from=deps /app/node_modules ./node_modules

# Copy full source
COPY . .

# Disable telemetry during build
ENV NEXT_TELEMETRY_DISABLED=1

# Build the standalone Next.js bundle
# next.config.js already has output: "standalone"
RUN npm run build


# ============================================================
# Stage 3 — runner: lean production image
# ============================================================
FROM node:20-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

# Backend URL used by Next.js rewrites proxy (overrideable at runtime)
ENV BACKEND_URL=http://backend:8000

# Security: non-root user
RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs

# Copy only the standalone output (no node_modules bulk)
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static     ./.next/static


USER nextjs

EXPOSE 3000

# Health check — Next.js returns 200 on "/"
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD wget -qO- http://localhost:3000/ > /dev/null || exit 1

# Next.js standalone outputs a self-contained server.js
CMD ["node", "server.js"]
