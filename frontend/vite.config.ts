import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/chat": "http://localhost:8000",
      "/sessions": "http://localhost:8000",
      "/topics": "http://localhost:8000",
      "/reflect": "http://localhost:8000",
      "/files": "http://localhost:8000",
      "/tasks": "http://localhost:8000",
      "/health": "http://localhost:8000",
    },
  },
});
