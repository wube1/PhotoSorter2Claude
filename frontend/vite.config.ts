import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";

const version = readFileSync(new URL("../VERSION", import.meta.url), "utf-8").trim();

export default defineConfig({
  plugins: [react()],
  define: { __APP_VERSION__: JSON.stringify(version) },
  build: { outDir: "dist", assetsDir: "assets", sourcemap: false, target: "es2022" },
  server: {
    proxy: { "/api": "http://127.0.0.1:8080", "/healthz": "http://127.0.0.1:8080" },
  },
});
