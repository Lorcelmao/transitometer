import type { NextConfig } from "next";

// A fully static site (no server, functions or ISR): every page is HTML built from the committed
// JSON in public/data, so the public site works without the pipeline or any backend.
const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  reactStrictMode: true,
};

export default nextConfig;
