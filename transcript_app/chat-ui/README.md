# chat-ui

**选型**：同一套 **Vite + React + TypeScript** 源码（`src/`）。

界面顶栏可切换 **浅色 / 深色**，偏好写入 `localStorage`（`bb-chat-theme`）；无记录时跟随系统 `prefers-color-scheme`。

| 命令 | 说明 |
|------|------|
| `npm install` | 安装依赖。已含 `.npmrc` 使用 `npmmirror` 拉 Electron 二进制；若仍失败可删 `node_modules/electron` 后重试，或自行设 `ELECTRON_MIRROR`。 |
| `npm run dev` | 启动 Vite + Electron。首次无 Gemini Key 会弹出**设置**；也可在顶栏「设置」填写（存本机 userData，不必改 `.env`）。对话/查证走主进程代理 `127.0.0.1:7890`。链接解析仍用仓库根 `.env` 的 `DASHSCOPE_API_KEY`；本地转写稿用「导入 result.json」。 |
| `npm run build` | 打桌面包所需的前端 + 主进程/预加载脚本（`dist/` + `dist-electron/`）。 |
| `npm run build:web` | **纯静态站** → `dist-web/`，可部署到任意静态托管或后续 Capacitor / PWA；**不在浏览器内直连 Gemini**（避免 Key 进前端）。 |
| `npm run preview:web` | 本地预览 `dist-web`。 |
| `npm run release` | `vite build` 后执行 `electron-builder` 打安装包（需本机 Electron 安装正常）。 |

架构说明见仓库根目录 `README.md` 中的「对话客户端」小节。
