/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  compress: true,
  poweredByHeader: false,
  eslint: {
    ignoreDuringBuilds: true,
  },
  experimental: {
    optimizePackageImports: ["lucide-react"],
  },
  images: {
    formats: ["image/avif", "image/webp"],
  },
  // The marketing site built under /new is the homepage: "/" serves it in place (the address bar stays "/"),
  // and the old /new address redirects to "/". The previous homepage file (app/page.tsx) is no longer reached.
  async redirects() {
    return [{ source: "/new", destination: "/", permanent: true }];
  },
  async rewrites() {
    return { beforeFiles: [{ source: "/", destination: "/new" }], afterFiles: [], fallback: [] };
  },
};

export default nextConfig;
