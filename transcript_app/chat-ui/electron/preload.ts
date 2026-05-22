import { contextBridge, ipcRenderer } from "electron";

/** 与 `src/types/gemini.ts` 保持一致 */
export type GeminiChatPayload = {
  system: string;
  contents: { role: "user" | "model"; text: string }[];
  model?: string;
};

export type GeminiStreamHandlers = {
  onChunk: (p: { delta: string }) => void;
  onDone: (p: { ok: boolean; error?: string; canceled?: boolean }) => void;
} | null;

let streamHandlers: GeminiStreamHandlers = null;

ipcRenderer.on("bbchat:gemini-chunk", (_e, p: { delta: string }) => {
  streamHandlers?.onChunk(p);
});
ipcRenderer.on("bbchat:gemini-done", (_e, p: { ok: boolean; error?: string; canceled?: boolean }) => {
  streamHandlers?.onDone(p);
});

contextBridge.exposeInMainWorld("bbChat", {
  platform: () => ipcRenderer.invoke("bbchat:platform") as Promise<{ kind: "electron" }>,
  getApiSettings: () =>
    ipcRenderer.invoke("bbchat:get-api-settings") as Promise<
      | { ok: true; hasGeminiKey: boolean; geminiMasked?: string }
      | { ok: false; error: string }
    >,
  saveApiSettings: (payload: { geminiApiKey: string }) =>
    ipcRenderer.invoke("bbchat:save-api-settings", payload) as Promise<
      | { ok: true; hasGeminiKey: boolean; geminiMasked?: string }
      | { ok: false; error: string }
    >,
  openTranscript: () =>
    ipcRenderer.invoke("bbchat:open-transcript") as Promise<
      | { ok: true; path: string; data: unknown }
      | { ok: false; canceled?: boolean; error?: string }
    >,
  parseBilibiliUrl: (url: string) =>
    ipcRenderer.invoke("bbchat:parse-bilibili-url", url) as Promise<
      | { ok: true; path: string; data: unknown }
      | { ok: false; error: string }
    >,
  parseVideoUrl: (url: string) =>
    ipcRenderer.invoke("bbchat:parse-video-url", url) as Promise<
      | { ok: true; path: string; data: unknown }
      | { ok: false; error: string }
    >,
  setGeminiStreamHandlers: (h: GeminiStreamHandlers) => {
    streamHandlers = h;
  },
  geminiChatStart: (payload: GeminiChatPayload) =>
    ipcRenderer.invoke("bbchat:gemini-chat-start", payload) as Promise<
      { ok: true } | { ok: false; error: string }
    >,
  geminiChatCancel: () => ipcRenderer.invoke("bbchat:gemini-chat-cancel") as Promise<{ ok: true }>,
  verifyCite: (payload: {
    claimText: string;
    quoteText: string;
    startLabel: string;
    endLabel: string;
  }) =>
    ipcRenderer.invoke("bbchat:verify-cite", payload) as Promise<
      { ok: true; report: string } | { ok: false; error: string }
    >,
  openExternal: (url: string) =>
    ipcRenderer.invoke("bbchat:open-external", url) as Promise<
      { ok: true } | { ok: false; error: string }
    >,
  saveAppPersist: (json: string) =>
    ipcRenderer.invoke("bbchat:save-app-persist", json) as Promise<
      { ok: true } | { ok: false; error: string }
    >,
  loadAppPersist: () =>
    ipcRenderer.invoke("bbchat:load-app-persist") as Promise<
      | { ok: true; json: string | null }
      | { ok: false; error: string }
    >,
  douyinOpenLogin: (url?: string) =>
    ipcRenderer.invoke("bbchat:douyin-open-login", { url }) as Promise<
      | { ok: true; cookieCount: number }
      | { ok: false; canceled?: boolean; error?: string }
    >,
  douyinSessionStatus: () =>
    ipcRenderer.invoke("bbchat:douyin-session-status") as Promise<
      { ok: true; hasCookies: boolean; entryCount: number } | { ok: false; error: string }
    >,
  onParseStatus: (
    handler: (p: { phase: "douyin-login" | "running" | "idle" }) => void
  ): (() => void) => {
    const fn = (_e: unknown, p: { phase: "douyin-login" | "running" | "idle" }) => handler(p);
    ipcRenderer.on("bbchat:parse-status", fn);
    return () => ipcRenderer.removeListener("bbchat:parse-status", fn);
  },
});
