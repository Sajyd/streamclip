import type { MetadataRoute } from "next";

const origin = process.env.PUBLIC_APP_URL ?? "http://localhost:3000";

export default function sitemap(): MetadataRoute.Sitemap {
  return ["/", "/register", "/login", "/legal/conditions", "/legal/confidentialite"].map((path) => ({
    url: `${origin}${path}`,
  }));
}
