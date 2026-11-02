import type { MetadataRoute } from "next";
import { POSTS, postPath } from "@/components/site/blog-posts";
import { ALL_LANDINGS } from "@/components/site/landing-content";

const SITE_URL = "https://www.anrilaitech.com";

// Public pages only.
const PATHS = ["/", "/product", "/pricing", "/industries", "/about", "/contact", ...ALL_LANDINGS.map((l) => l.path), "/blog", ...POSTS.map((p) => postPath(p.slug)), "/privacy-policy", "/terms-and-conditions", "/data-deletion"];

export default function sitemap(): MetadataRoute.Sitemap {
  return PATHS.map((path) => ({ url: `${SITE_URL}${path}` }));
}
