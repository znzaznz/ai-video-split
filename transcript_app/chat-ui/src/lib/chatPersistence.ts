import type { MessageSegment } from "@/types/chat";
import type { ParsedItem } from "@/types/parsed";

export const CHAT_UI_STORAGE_KEY = "bilibili-chat-ui-persist-v2";

const STORAGE_KEY = CHAT_UI_STORAGE_KEY;

export type PersistedMessage = {
  id: string;
  role: "user" | "assistant";
  segments: MessageSegment[];
};

export type PersistV2 = {
  v: 2;
  items: ParsedItem[];
  activeId: string | null;
  /** 每条侧栏稿 id 对应一套对话（含系统引导气泡） */
  threadsByItemId: Record<string, PersistedMessage[]>;
  /** 每条侧栏稿 id → 出处查证缓存键 → Markdown 报告 */
  verifyByItemId?: Record<string, Record<string, string>>;
};

export function loadPersisted(): PersistV2 | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw) as PersistV2;
    if (data?.v !== 2 || !Array.isArray(data.items)) return null;
    if (typeof data.threadsByItemId !== "object" || data.threadsByItemId === null) {
      data.threadsByItemId = {};
    }
    if (typeof data.verifyByItemId !== "object" || data.verifyByItemId === null) {
      data.verifyByItemId = {};
    }
    return data;
  } catch {
    return null;
  }
}

export function savePersisted(payload: PersistV2): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
  } catch {
    /* 配额满或隐私模式 */
  }
}
