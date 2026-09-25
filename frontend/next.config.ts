import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  eslint: {
    ignoreDuringBuilds: true,
  },
  typescript: {
    // TypeScript type-checking will run during development and CI
    ignoreBuildErrors: false,
  }
};

export default nextConfig;
