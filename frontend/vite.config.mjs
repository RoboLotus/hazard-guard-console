import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(() => {
  return {
    build: {
      outDir: "dist/client",
    },
    optimizeDeps: {
      include: ["react", "react-dom/client"],
    },
    server: {
      host: "127.0.0.1",
      port: 5179,
      strictPort: true,
      allowedHosts: ["terminal.local"],
      warmup: {
        clientFiles: ["./src/main.jsx"],
      },
    },
    plugins: [react(), {
      name: "recorded-demo-no-controls",
      configureServer(server) {
        server.middlewares.use((req, res, next) => {
          if (/^\/(api|ws)(\/|\?|$)/.test(req.url || "")) {
            res.statusCode = 403; res.end("Recorded demo: robot control is disabled"); return;
          }
          next();
        });
      },
    }],
  };
});
