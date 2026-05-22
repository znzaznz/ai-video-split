import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import electron from "vite-plugin-electron/simple";

// 与 vite.web.config 共用 src/：Electron 桌面 + 纯 Web 同一套 React 组件，便于后续移动端 H5。
export default defineConfig({
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  plugins: [
    react(),
    electron({
      main: {
        entry: "electron/main.ts",
        vite: {
          plugins: [
            /**
             * package.json 为 type:module 时，vite-plugin-electron 默认 lib.formats 为 es，
             * 合并后仍可能产出带 import / import.meta 的「伪 .cjs」，Electron 按 CJS 加载即报错。
             * 在子构建 configResolved 后强制为 cjs，与 preload 的 CJS 策略一致。
             */
            {
              name: "electron-main-force-cjs",
              enforce: "post",
              configResolved(config) {
                const lib = config.build.lib as { formats?: string[] } | false | undefined;
                if (lib && typeof lib === "object" && Array.isArray(lib.formats)) {
                  lib.formats = ["cjs"];
                }
              },
            },
          ],
          build: {
            /**
             * 根 package 为 "type":"module" 时插件默认把主进程打成 ES 格式，
             * `import from "electron"` 会在 Node ESM 加载器里触发 CJS 互操作错误。
             * 主进程用 CJS + .cjs 扩展名，与 renderer 的 module 类型分离。
             */
            lib: {
              entry: "electron/main.ts",
              formats: ["cjs"],
              fileName: () => "main.cjs",
            },
            rollupOptions: {
              external: ["https-proxy-agent"],
              output: {
                format: "cjs",
                inlineDynamicImports: true,
              },
            },
          },
        },
      },
      preload: {
        input: path.join(__dirname, "electron/preload.ts"),
        vite: {
          build: {
            rollupOptions: {
              output: {
                /**
                 * 根目录 type:module 时插件会把 preload 打成 .mjs，但内容仍是 CJS（require）。
                 * Electron 按扩展名把 .mjs 当 ES 模块加载 → require 不可用 → preload 整段失败，
                 * contextBridge 未执行，window.bbChat 不存在（界面像「网页版」）。
                 */
                format: "cjs",
                entryFileNames: "preload.cjs",
                chunkFileNames: "preload-[name].cjs",
                inlineDynamicImports: true,
              },
            },
          },
        },
      },
      renderer: {},
    }),
  ],
  server: { port: 5173, strictPort: true },
});
