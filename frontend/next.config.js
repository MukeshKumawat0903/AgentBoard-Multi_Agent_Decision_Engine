/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  async rewrites() {
    // Proxy all /backend/* requests to the FastAPI server.
    // This means the browser only ever calls the Next.js server (same host/port),
    // so it works from any IP with no CORS issues and no hardcoded backend URL.
    const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";
    return [
      {
        source: "/backend/:path*",
        destination: `${backendUrl}/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
