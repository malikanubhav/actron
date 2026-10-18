# Frontend image: Next.js standalone build served by `node server.js`.
# Build from the repository root: docker build -f infra/docker/frontend.Dockerfile -t actron-frontend:dev .
#
# next.config.ts reads API_INTERNAL_URL when it builds, and Next.js bakes the /api, /slack and /webhooks
# rewrites into the build. So the backend address is a build argument; the default matches compose.
FROM node:22.23.3-bookworm-slim AS deps
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM node:22.23.3-bookworm-slim AS build
WORKDIR /app/frontend
ARG API_INTERNAL_URL=http://backend:8080
ARG NEXT_PUBLIC_ACTRON_DEV_FIXTURES=0
ENV API_INTERNAL_URL=${API_INTERNAL_URL} \
    NEXT_PUBLIC_ACTRON_DEV_FIXTURES=${NEXT_PUBLIC_ACTRON_DEV_FIXTURES} \
    NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/frontend/node_modules ./node_modules
COPY frontend/ ./
# The build snapshots the ontology (see the prebuild script in package.json), so the files must be next door.
COPY ontology/ /app/ontology/
RUN npm run build

FROM node:22.23.3-bookworm-slim AS run
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
WORKDIR /app
RUN groupadd --gid 10001 nextjs && useradd --uid 10001 --gid nextjs --shell /usr/sbin/nologin nextjs
# With `output: "standalone"` the server and the files it traces are in .next/standalone.
COPY --from=build --chown=nextjs:nextjs /app/frontend/.next/standalone ./
COPY --from=build --chown=nextjs:nextjs /app/frontend/.next/static ./.next/static
COPY --from=build --chown=nextjs:nextjs /app/frontend/public ./public
USER nextjs
EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD node -e "fetch('http://127.0.0.1:3000/').then(r=>process.exit(r.status<500?0:1)).catch(()=>process.exit(1))"
CMD ["node", "server.js"]
