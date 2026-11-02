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
  // The marketing site lives in app/new but is served at clean addresses: "/", "/product", "/pricing",
  // "/industries" and "/about" rewrite to it in place (the address bar stays clean). Any old /new address
  // redirects to the clean one; the #hash is kept by the browser. app/page.tsx is no longer reached.
  async redirects() {
    return [
      { source: "/new", destination: "/", permanent: true },
      { source: "/new/:path*", destination: "/:path*", permanent: true },
    ];
  },
  async rewrites() {
    return {
      beforeFiles: [
        { source: "/", destination: "/new" },
        { source: "/product", destination: "/new/product" },
        { source: "/pricing", destination: "/new/pricing" },
        { source: "/industries", destination: "/new/industries" },
        { source: "/about", destination: "/new/about" },
      ],
      afterFiles: [],
      fallback: [],
    };
  },
};

export default nextConfig;
