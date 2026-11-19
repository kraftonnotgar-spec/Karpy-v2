import type { NextConfig } from "next";

// Security headers and standalone output follow the source dashboard's config. The backend
// (KARPy, FastAPI) is reached same-origin through /api, so cookies and CSRF stay first-party.
const scriptPolicy = process.env.NODE_ENV === "development" ? "script-src 'self' 'unsafe-inline' 'unsafe-eval'" : "script-src 'self' 'unsafe-inline'";
const apiOrigin = (process.env.API_ORIGIN ?? "http://127.0.0.1:9000").replace(/\/+$/, "");

// The admin console lives at src/app/admin. ADMIN_BASE_PATH serves it under another single
// segment (for example /control-room); see src/core/config/admin-path.ts for the rules.
const adminBasePath = process.env.ADMIN_BASE_PATH ?? "/admin";
if (!/^\/[A-Za-z][A-Za-z0-9_-]{2,63}$/.test(adminBasePath)) {
  throw new Error("Invalid ADMIN_BASE_PATH: use one path segment such as /admin or /control-room.");
}

const nextConfig: NextConfig = {
  poweredByHeader: false,
  typescript: { tsconfigPath: process.env.NODE_ENV === "production" ? "tsconfig.build.json" : "tsconfig.json" },
  output: "standalone",
  env: {
    // Footers start from the build year and correct themselves in the browser (core/lib/copyright).
    NEXT_PUBLIC_BUILD_YEAR: String(new Date().getUTCFullYear()),
    NEXT_PUBLIC_ADMIN_BASE_PATH: adminBasePath,
  },
  devIndicators: false,
  turbopack: { root: __dirname },
  experimental: {
    // radix-ui is one barrel of every primitive; import only the ones a page uses.
    optimizePackageImports: ["radix-ui"],
  },
  allowedDevOrigins: ["127.0.0.1"],
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${apiOrigin}/api/:path*` },
      ...(adminBasePath === "/admin"
        ? []
        : [
            { source: adminBasePath, destination: "/admin" },
            { source: `${adminBasePath}/:path*`, destination: "/admin/:path*" },
          ]),
    ];
  },
  async headers() {
    return [{ source: "/:path*", headers: [
      { key: "Content-Security-Policy", value: `default-src 'self'; ${scriptPolicy}; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; frame-src 'self' blob:; object-src 'none'; frame-ancestors 'none'; form-action 'self'; base-uri 'self'` },
      { key: "X-Content-Type-Options", value: "nosniff" }, { key: "X-Frame-Options", value: "DENY" },
      { key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" }, { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
      { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
    ] }];
  },
};

export default nextConfig;
