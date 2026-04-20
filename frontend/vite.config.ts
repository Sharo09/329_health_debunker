// frontend/vite.config.ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      // Any request the browser makes to /api/... gets forwarded to the
      // FastAPI backend running on port 8000. This is local dev only.
      "/api": "http://localhost:8000",
    },
  },
});
