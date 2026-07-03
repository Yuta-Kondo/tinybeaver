import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      // pdf.js pulls in path2d-polyfill only for legacy browsers; stub it out.
      "path2d-polyfill": fileURLToPath(new URL("./src/lib/empty.ts", import.meta.url)),
    },
  },
  // pdf.js ships top-level await; es2022 supports it (modern browsers only).
  build: { target: "es2022" },
  esbuild: { target: "es2022" },
  optimizeDeps: { esbuildOptions: { target: "es2022" } },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/__tests__/setup.ts"],
  },
  server: {
    proxy: {
      "/chat": "http://localhost:8000",
      "/sessions": "http://localhost:8000",
      "/topics": "http://localhost:8000",
      "/reflect": "http://localhost:8000",
      "/files": "http://localhost:8000",
      "/tasks": "http://localhost:8000",
      "/health": "http://localhost:8000",
      "/auth": "http://localhost:8000",
      "/emails": "http://localhost:8000",
      "/push": "http://localhost:8000",
    },
  },
});
