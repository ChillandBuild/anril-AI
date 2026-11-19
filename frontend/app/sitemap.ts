import type { MetadataRoute } from "next";
import { POSTS, postPath } from "@/components/site/blog-posts";
import { INDUSTRY_PAGES } from "@/components/site/industry-pages";
import { ALL_LANDINGS } from "@/components/site/landing-content";

const SITE_URL = "https://www.anrilaitech.com";

// Public pages only.
const PATHS = ["/", "/product", "/pricing", "/website-development", "/industries", "/about", "/contact", ...ALL_LANDINGS.map((l) => l.path), ...INDUSTRY_PAGES.map((p) => p.path), "/blog", ...POSTS.map((p) => postPath(p.slug)), "/privacy-policy", "/terms-and-conditions", "/data-deletion"];

export default function sitemap(): MetadataRoute.Sitemap {
  const updated = new Map(POSTS.map((p) => [postPath(p.slug), new Date(`${p.updated}T00:00:00Z`)]));
  return PATHS.map((path) => ({ url: `${SITE_URL}${path}`, lastModified: updated.get(path) }));
}
