/**
 * 若 shell 里残留 ELECTRON_RUN_AS_NODE=1，子进程里的 electron 会当成纯 Node，
 * require("electron") 没有 app —— 开发时先清掉再启动 Vite。
 */
import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
delete process.env.ELECTRON_RUN_AS_NODE;

const viteCli = path.join(root, "node_modules", "vite", "bin", "vite.js");
const child = spawn(process.execPath, [viteCli, ...process.argv.slice(2)], {
  stdio: "inherit",
  env: process.env,
  cwd: root,
});
child.on("exit", (code, signal) => {
  process.exit(code ?? (signal ? 1 : 0));
});
