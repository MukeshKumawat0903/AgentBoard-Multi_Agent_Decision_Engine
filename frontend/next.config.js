const path = require("path");

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",

  // Pin the tracing root to this folder so Next.js does not walk up to the
  // monorepo root and get confused by the root-level package-lock.json.
  // Without this, Next.js 15+ emits a spurious "multiple lockfiles" warning.
  outputFileTracingRoot: path.join(__dirname),

  // NOTE: We do NOT use rewrites() here because rewrites() are evaluated at
  // BUILD TIME — BACKEND_URL would get baked into the image.
  //
  // Instead, all /backend/* requests are handled at RUNTIME by the Route Handler
  // at src/app/backend/[...path]/route.ts, which reads process.env.BACKEND_URL
  // on every request. This makes the same Docker image work on:
  //   - Local Docker:  BACKEND_URL=http://agentboard-backend:8000
  //   - Render:        BACKEND_URL=https://my-backend.onrender.com
  //   - AWS ECS:       BACKEND_URL=http://backend-service:8000
  //   - Any VM:        BACKEND_URL=http://<private-ip>:8000
};

module.exports = nextConfig;
