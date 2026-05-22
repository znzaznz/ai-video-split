import type { GeminiChatPayload } from "@/types/gemini";

declare global {
  interface Window {
    bbChat?: {
      platform: () => Promise<{ kind: "electron" }>;
      getApiSettings?: () => Promise<
        | { ok: true; hasGeminiKey: boolean; geminiMasked?: string }
        | { ok: false; error: string }
      >;
      saveApiSettings?: (payload: { geminiApiKey: string }) => Promise<
        | { ok: true; hasGeminiKey: boolean; geminiMasked?: string }
        | { ok: false; error: string }
      >;
      openTranscript: () => Promise<
        | { ok: true; path: string; data: unknown }
        | { ok: false; canceled?: boolean; error?: string }
      >;
      parseBilibiliUrl: (url: string) => Promise<
        | { ok: true; path: string; data: unknown }
        | { ok: false; error: string }
      >;
      parseVideoUrl?: (url: string) => Promise<
        | { ok: true; path: string; data: unknown }
        | { ok: false; error: string }
      >;
      setGeminiStreamHandlers: (
        handlers: {
          onChunk: (p: { delta: string }) => void;
          onDone: (p: { ok: boolean; error?: string; canceled?: boolean }) => void;
        } | null
      ) => void;
      geminiChatStart: (payload: GeminiChatPayload) => Promise<{ ok: true } | { ok: false; error: string }>;
      geminiChatCancel: () => Promise<{ ok: true }>;
      verifyCite: (payload: {
        claimText: string;
        quoteText: string;
        startLabel: string;
        endLabel: string;
      }) => Promise<{ ok: true; report: string } | { ok: false; error: string }>;
      openExternal: (url: string) => Promise<{ ok: true } | { ok: false; error: string }>;
      /** 将解析稿与对话状态写入应用目录（与 localStorage 镜像） */
      saveAppPersist?: (json: string) => Promise<{ ok: true } | { ok: false; error: string }>;
      loadAppPersist?: () => Promise<
        | { ok: true; json: string | null }
        | { ok: false; error: string }
      >;
      douyinOpenLogin?: (url?: string) => Promise<
        | { ok: true; cookieCount: number }
        | { ok: false; canceled?: boolean; error?: string }
      >;
      douyinSessionStatus?: () => Promise<
        { ok: true; hasCookies: boolean; entryCount: number } | { ok: false; error: string }
      >;
      onParseStatus?: (
        handler: (p: { phase: "douyin-login" | "running" | "idle" }) => void
      ) => () => void;
    };
  }
}

export {};
