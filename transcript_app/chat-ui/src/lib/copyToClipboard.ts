import type { TranscriptSentence } from "@/types/chat";

export function formatSentenceForCopy(s: TranscriptSentence): string {
  const time = `${s.start_hms}–${s.end_hms}`;
  const text = (s.text || "").trim();
  return text ? `${time} ${text}` : time;
}

export function formatAllSentencesForCopy(sentences: TranscriptSentence[]): string {
  return sentences.map(formatSentenceForCopy).join("\n");
}

export async function copyToClipboard(
  text: string
): Promise<{ ok: true } | { ok: false; error: string }> {
  const value = text ?? "";
  if (!value) {
    return { ok: false, error: "没有可复制的内容" };
  }
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
      return { ok: true };
    }
  } catch {
    /* fallback below */
  }
  try {
    const ta = document.createElement("textarea");
    ta.value = value;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.left = "-9999px";
    ta.style.top = "0";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    if (ok) return { ok: true };
    return { ok: false, error: "复制失败，请手动选择复制" };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}
