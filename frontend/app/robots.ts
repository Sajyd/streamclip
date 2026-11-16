import type { MetadataRoute } from "next";

const origin = process.env.PUBLIC_APP_URL ?? "http://localhost:3000";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        disallow: ["/dashboard", "/billing", "/settings", "/admin", "/auth/", "/api/"],
      },
    ],
    sitemap: `${origin}/sitemap.xml`,
  };
}
