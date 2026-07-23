import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const defaultBackendPort = mode === "simulation" ? 8001 : 8000;
  const backendUrl = process.env.HAZARD_GUARD_BACKEND_URL || `http://127.0.0.1:${defaultBackendPort}`;
  const backendWsUrl = backendUrl.replace(/^http/, "ws");

  return {
    build: {
      outDir: "dist/client",
    },
    optimizeDeps: {
      include: ["react", "react-dom/client"],
    },
    server: {
      host: "0.0.0.0",
      allowedHosts: ["terminal.local"],
      proxy: {
        "/api": backendUrl,
        "/ws": { target: backendWsUrl, ws: true },
      },
      warmup: {
        clientFiles: ["./src/main.jsx"],
      },
    },
    plugins: [react()],
  };
});
