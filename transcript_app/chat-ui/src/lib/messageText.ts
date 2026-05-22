import type { MessageSegment } from "@/types/chat";

/** 将一条对话消息转为可复制的纯文本（与发给模型的格式一致） */
export function segmentsToPlainText(segments: MessageSegment[]): string {
  return segments
    .map((s) => {
      if (s.kind === "text") return s.text;
      return s.refs.map((r) => `[${r.start_hms} - ${r.end_hms}] ${r.text}`).join("\n");
    })
    .join("\n")
    .trim();
}
