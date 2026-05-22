/** 与主进程 IPC 约定一致（preload 侧手写对齐，避免 preload 依赖 src 打包边界） */
export type GeminiChatPayload = {
  system: string;
  contents: { role: "user" | "model"; text: string }[];
  model?: string;
};
