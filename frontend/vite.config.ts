import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The browser only ever calls relative /api URLs; the dev server proxies them to FastAPI.
// `--mode static` builds the recorded-snapshot demo instead (no backend; see docs/STATIC_DEMO.md):
// relative base so it works from any sub-path (e.g. GitHub Pages), snapshot JSON copied from static-demo/.
export default defineConfig(({ mode }) => {
  const isStatic = mode === "static";
  return {
    plugins: [react()],
    base: isStatic ? "./" : "/",
    publicDir: isStatic ? "static-demo" : "public",
    build: { outDir: isStatic ? "dist-static" : "dist" },
    server: {
      host: "0.0.0.0",
      port: 5173,
      allowedHosts: true,
      proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: true } },
    },
    preview: { host: "0.0.0.0", port: 4173, allowedHosts: true },
  };
});
