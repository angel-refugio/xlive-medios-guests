import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// El proxy evita CORS en desarrollo: /api/* se reenvía al backend en :8000.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
