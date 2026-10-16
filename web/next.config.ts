import type { NextConfig } from "next";

// Static export: the site is plain files on static hosting (docs/spec.md, 開源網站與商業化).
// NEXT_PUBLIC_BASE_PATH is set when served from a sub-path such as GitHub Pages.
const config: NextConfig = {
  output: "export",
  basePath: process.env.NEXT_PUBLIC_BASE_PATH || undefined,
  trailingSlash: true,
  images: { unoptimized: true },
};

export default config;
