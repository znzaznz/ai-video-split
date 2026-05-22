import { extractVideoUrlFromPaste, isSupportedVideoUrl } from "@/lib/videoUrl";
import { isTranscriptSentenceArray, type TranscriptSentence } from "@/types/chat";

export function getPlatform(): "electron" | "web" {
  return window.bbChat ? "electron" : "web";
}

export async function parseVideoUrl(
  url: string
): Promise<{ ok: true; path: string; sentences: TranscriptSentence[] } | { ok: false; error: string }> {
  const trimmed = extractVideoUrlFromPaste(url);
  if (!trimmed) return { ok: false, error: "链接为空" };
  if (!isSupportedVideoUrl(trimmed)) {
    return {
      ok: false,
      error: "仅支持 bilibili.com / b23.tv / douyin.com / iesdouyin.com 的视频链接。",
    };
  }

  const invoke = window.bbChat?.parseVideoUrl ?? window.bbChat?.parseBilibiliUrl;
  if (invoke) {
    const r = await invoke(trimmed);
    if (!r.ok) return { ok: false, error: r.error || "解析失败" };
    if (!isTranscriptSentenceArray(r.data)) {
      return { ok: false, error: "不是有效的 result.json 句级数组" };
    }
    return { ok: true, path: r.path, sentences: r.data };
  }

  return {
    ok: false,
    error:
      "网页版无法从链接跑本机转写。请用 Electron 窗口（npm run dev）输入 B 站/抖音链接，或改用下方「导入 result.json」。",
  };
}

/** @deprecated 使用 parseVideoUrl */
export async function parseBilibiliVideoUrl(
  url: string
): Promise<{ ok: true; path: string; sentences: TranscriptSentence[] } | { ok: false; error: string }> {
  return parseVideoUrl(url);
}

export async function prepareDouyinLogin(
  url?: string
): Promise<{ ok: true; cookieCount: number } | { ok: false; error: string; canceled?: boolean }> {
  if (getPlatform() !== "electron" || !window.bbChat?.douyinOpenLogin) {
    return {
      ok: false,
      error: "抖音内置登录仅支持 Electron 桌面版（npm run dev），网页版请手动导出 cookies.txt。",
    };
  }
  const trimmed = url ? extractVideoUrlFromPaste(url) : "";
  const r = await window.bbChat.douyinOpenLogin(trimmed || undefined);
  if (r.ok) return { ok: true, cookieCount: r.cookieCount };
  if (r.canceled) return { ok: false, error: "已取消", canceled: true };
  return { ok: false, error: r.error || "登录失败" };
}

export async function openTranscriptFile(): Promise<
  | { ok: true; path: string; sentences: TranscriptSentence[] }
  | { ok: false; error: string }
> {
  if (window.bbChat) {
    const r = await window.bbChat.openTranscript();
    if (!r.ok) {
      if ("canceled" in r && r.canceled) return { ok: false, error: "已取消" };
      return { ok: false, error: r.error || "打开失败" };
    }
    if (!isTranscriptSentenceArray(r.data)) {
      return { ok: false, error: "不是有效的 result.json 句级数组" };
    }
    return { ok: true, path: r.path, sentences: r.data };
  }

  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".json,application/json";
    input.onchange = () => {
      const file = input.files?.[0];
      if (!file) {
        resolve({ ok: false, error: "未选择文件" });
        return;
      }
      const reader = new FileReader();
      reader.onload = () => {
        try {
          const data = JSON.parse(String(reader.result)) as unknown;
          if (!isTranscriptSentenceArray(data)) {
            resolve({ ok: false, error: "不是有效的 result.json 句级数组" });
            return;
          }
          resolve({ ok: true, path: file.name, sentences: data });
        } catch {
          resolve({ ok: false, error: "JSON 解析失败" });
        }
      };
      reader.onerror = () => resolve({ ok: false, error: "读取文件失败" });
      reader.readAsText(file, "utf-8");
    };
    input.click();
  });
}
