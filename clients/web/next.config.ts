import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  images: {
    remotePatterns: [
      { protocol: "http", hostname: "localhost" },
      { protocol: "http", hostname: "minio" },
      { protocol: "https", hostname: "*.xyler.ai" },
    ],
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.API_PROXY_URL || "http://api:8080"}/api/:path*`,
      },
      {
        source: "/storage/:path*",
        destination: `${process.env.STORAGE_PROXY_URL || "http://minio:9000"}/:path*`,
      },
    ];
  },
};

export default nextConfig;
