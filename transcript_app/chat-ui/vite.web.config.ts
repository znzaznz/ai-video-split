import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/** 浏览器 / 移动端 H5：不含 Electron，输出静态资源，可部署任意静态托管或 Capacitor 包壳 */
export default defineConfig({
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  plugins: [react()],
  base: "./",
  build: {
    outDir: "dist-web",
    emptyOutDir: true,
  },
  server: { port: 5174, strictPort: true },
});
