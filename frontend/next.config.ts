import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV === "development";

// Pages are prerendered (static shell + streamed content), which rules out
// per-request nonces: scripts are restricted to this origin instead. Payment
// pages are hosted by Stripe, reached by top-level navigation only.
const contentSecurityPolicy = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' blob: data: https://*.amazonaws.com",
  "media-src 'self' blob: https://*.amazonaws.com",
  "font-src 'self'",
  `connect-src 'self' https://*.amazonaws.com${isDev ? " ws:" : ""}`,
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self' https://checkout.stripe.com https://billing.stripe.com",
  "frame-ancestors 'none'",
  ...(isDev ? [] : ["upgrade-insecure-requests"]),
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: contentSecurityPolicy },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=()" },
  { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" },
];

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  poweredByHeader: false,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async headers() {
    return [
      { source: "/(.*)", headers: securityHeaders },
      // These pages carry a single-use token in their URL: never sent as a referrer.
      {
        source: "/(reset-password|verify-email)",
        headers: [{ key: "Referrer-Policy", value: "no-referrer" }],
      },
    ];
  },
  async rewrites() {
    // Local: memorable /rtmp resolve is served by the API process.
    const api = process.env.API_INTERNAL_URL;
    if (!api) {
      return [];
    }
    return [{ source: "/rtmp", destination: `${api.replace(/\/$/, "")}/rtmp` }];
  },
};

export default nextConfig;
