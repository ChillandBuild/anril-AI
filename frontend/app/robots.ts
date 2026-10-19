import type { MetadataRoute } from "next";

const SITE_URL = "https://www.anrilaitech.com";

// The app itself (dashboard, operator console, auth callbacks) is never useful in search.
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [{ userAgent: "*", allow: "/", disallow: ["/dashboard", "/operator", "/auth", "/offline"] }],
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
