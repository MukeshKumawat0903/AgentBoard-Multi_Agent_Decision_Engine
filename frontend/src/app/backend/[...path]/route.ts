/**
 * Runtime reverse-proxy for the AgentBoard FastAPI backend.
 *
 * Why this exists instead of next.config.js rewrites():
 *   next.config.js rewrites() are evaluated ONCE at build time, so the
 *   BACKEND_URL env-var gets baked in.  A Route Handler is invoked on every
 *   request, reading process.env.BACKEND_URL at runtime — meaning the same
 *   Docker image works on localhost, any VM, Render, AWS ECS/EKS, etc.
 *   Just set the BACKEND_URL environment variable for the container/service.
 *
 * Supports:
 *   - All HTTP verbs (GET, POST, DELETE, PATCH, PUT)
 *   - SSE streaming (for live debate updates)
 *   - File upload (multipart/form-data)
 *   - Any query parameters / path segments
 *
 * Env vars:
 *   BACKEND_URL  – URL of the FastAPI server (default: http://localhost:8000)
 *                  Set this in your Docker run command, docker-compose.yml,
 *                  Render environment, AWS task definition, etc.
 *
 * Next.js 15 note: `params` in Route Handlers is now a Promise and must be
 *   awaited before use. See: https://nextjs.org/docs/app/api-reference/file-conventions/route
 */

import { NextRequest, NextResponse } from "next/server";

/** Resolve the upstream backend URL at request time (never at build time). */
function getBackendUrl(): string {
  return (process.env.BACKEND_URL ?? "http://localhost:8000").replace(/\/$/, "");
}

/** Headers that must not be forwarded to the upstream service. */
const HOP_BY_HOP = new Set([
  "host",
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

function buildUpstreamHeaders(req: NextRequest): Headers {
  const headers = new Headers();
  req.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase())) {
      headers.set(key, value);
    }
  });
  // Let the upstream know where the request came from
  headers.set("x-forwarded-for", req.headers.get("x-forwarded-for") ?? "unknown");
  headers.set("x-forwarded-host", req.headers.get("host") ?? "");
  return headers;
}

// Next.js 15: params is a Promise — must be awaited before use.
type RouteContext = { params: Promise<{ path: string[] }> };

async function proxyRequest(
  req: NextRequest,
  context: RouteContext,
): Promise<Response> {
  const { path } = await context.params;

  const backendUrl = getBackendUrl();
  const pathSegments = path.join("/");
  const search = req.nextUrl.search ?? "";
  const upstreamUrl = `${backendUrl}/${pathSegments}${search}`;

  const upstreamHeaders = buildUpstreamHeaders(req);

  // Pass body for methods that carry one; GET/HEAD must not have a body.
  const hasBody = req.method !== "GET" && req.method !== "HEAD";
  const body = hasBody ? req.body : undefined;

  try {
    const upstreamRes = await fetch(upstreamUrl, {
      method: req.method,
      headers: upstreamHeaders,
      body,
      // Required for streaming / SSE responses — do not buffer the body.
      // @ts-expect-error – Node 18 fetch supports duplex but TS types lag behind
      duplex: "half",
    });

    // Strip hop-by-hop headers from the upstream response before forwarding.
    const responseHeaders = new Headers();
    upstreamRes.headers.forEach((value, key) => {
      if (!HOP_BY_HOP.has(key.toLowerCase())) {
        responseHeaders.set(key, value);
      }
    });

    // Stream the body through — critical for SSE and large file downloads.
    return new Response(upstreamRes.body, {
      status: upstreamRes.status,
      statusText: upstreamRes.statusText,
      headers: responseHeaders,
    });
  } catch (err) {
    const message =
      err instanceof Error ? err.message : "Unknown proxy error";
    console.error(`[backend-proxy] Failed to reach ${upstreamUrl}: ${message}`);
    return NextResponse.json(
      { detail: `Backend unreachable: ${message}` },
      { status: 502 },
    );
  }
}

// Export a handler for every HTTP method Next.js Route Handlers support.
export const GET    = proxyRequest;
export const POST   = proxyRequest;
export const PUT    = proxyRequest;
export const PATCH  = proxyRequest;
export const DELETE = proxyRequest;
export const HEAD   = proxyRequest;
export const OPTIONS = proxyRequest;

// Ensure Next.js never statically pre-renders this route.
export const dynamic = "force-dynamic";
