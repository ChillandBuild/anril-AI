import type { MetadataRoute } from "next";

const SITE_URL = "https://www.anrilaitech.com";

// Public pages only.
const PATHS = ["/", "/new/product", "/new/pricing", "/new/industries", "/new/about", "/contact", "/privacy-policy", "/terms-and-conditions", "/data-deletion"];

export default function sitemap(): MetadataRoute.Sitemap {
  return PATHS.map((path) => ({ url: `${SITE_URL}${path}` }));
}
