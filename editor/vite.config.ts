import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "/",
  server: { proxy: { "/api": "http://localhost:8787", "/files": "http://localhost:8787", "/fonts": "http://localhost:8787" } },
  build: { outDir: "dist", emptyOutDir: true, target: "es2020" },
});
