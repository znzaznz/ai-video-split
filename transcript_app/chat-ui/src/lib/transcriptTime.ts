import type { TranscriptSentence } from "@/types/chat";

/** 解析稿内或模型输出的 `HH:MM:SS` / `HH:MM:SS,mmm` */
export function parseFlexibleHmsToMs(h: string): number {
  const t = h.trim();
  const m = t.match(/^(\d{2}):(\d{2}):(\d{2})(?:,(\d{3}))?$/);
  if (!m) return NaN;
  const hh = Number(m[1]);
  const mm = Number(m[2]);
  const ss = Number(m[3]);
  const ms = m[4] ? Number(m[4]) : 0;
  if ([hh, mm, ss, ms].some((n) => !Number.isFinite(n))) return NaN;
  return ((hh * 60 + mm) * 60 + ss) * 1000 + ms;
}

/** 与模型括号内时间轴匹配：`(00:03:48-00:03:53)`，支持 `-` / `–` / `—` */
export const PAREN_TIME_RANGE_RE =
  /\(((\d{2}:\d{2}:\d{2})(?:,(\d{3}))?)\s*[-–—]\s*((\d{2}:\d{2}:\d{2})(?:,(\d{3}))?)\)/g;

/** 模型常把时间轴写在句末标点前，如「…(00:01-00:02)。」；渲染前把标点挪到时间轴前 */
const PUNCT_AFTER_CITE_RE = /^[\s]*([。，、；：！？」』）\]"']+)/;

export function normalizeCitationPunctuation(text: string): string {
  const re = new RegExp(PAREN_TIME_RANGE_RE.source, PAREN_TIME_RANGE_RE.flags);
  let out = "";
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    out += text.slice(last, m.index);
    const cite = m[0];
    const tail = text.slice(m.index + cite.length);
    const pm = tail.match(PUNCT_AFTER_CITE_RE);
    if (pm) {
      out += pm[1] + cite;
      last = m.index + cite.length + pm[0].length;
    } else {
      out += cite;
      last = m.index + cite.length;
    }
  }
  out += text.slice(last);
  return out;
}

export type CitationSlot = {
  index: number;
  label: string;
  startLabel: string;
  endLabel: string;
  /** 助手总结里、时间轴所在行的要点（查证主对象） */
  claimText: string;
  quoteText: string;
  /** 该时段内重叠的转写句（用于弹窗逐句复制） */
  quoteSentences: TranscriptSentence[];
};

/** 从助手回复中提取时间轴所在行的总结要点（去掉时间括号） */
export function extractClaimContext(normalized: string, citeStart: number, citeLength: number): string {
  let lineStart = normalized.lastIndexOf("\n", citeStart - 1);
  lineStart = lineStart < 0 ? 0 : lineStart + 1;
  let lineEnd = normalized.indexOf("\n", citeStart + citeLength);
  if (lineEnd < 0) lineEnd = normalized.length;

  let line = normalized.slice(lineStart, lineEnd);
  line = line.replace(new RegExp(PAREN_TIME_RANGE_RE.source, "g"), " ");
  line = line.replace(/\s+/g, " ").trim();
  line = line.replace(/^[-*•]\s+/, "").replace(/^\d+[.)]\s+/, "").trim();
  line = line.replace(/^#+\s+/, "").trim();
  return line;
}

/** 将时间轴替换为 Markdown 行内 code 占位 `〔n〕`，整段一次渲染，chip 才能跟在句末不换行 */
export function injectCitationMarkdownSlots(
  text: string,
  sentences: TranscriptSentence[] | null | undefined
): { body: string; slots: CitationSlot[] } {
  const normalized = normalizeCitationPunctuation(text);
  const re = new RegExp(PAREN_TIME_RANGE_RE.source, PAREN_TIME_RANGE_RE.flags);
  const slots: CitationSlot[] = [];
  let body = "";
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(normalized)) !== null) {
    body += normalized.slice(last, m.index);
    const range = matchTimeRange(m);
    if (range) {
      const index = slots.length;
      const quoteSentences = sentencesForRange(sentences, range.startMs, range.endMs);
      slots.push({
        index,
        label: range.full,
        startLabel: range.startRaw,
        endLabel: range.endRaw,
        claimText: extractClaimContext(normalized, m.index, m[0].length),
        quoteText: quoteTextForRange(sentences, range.startMs, range.endMs),
        quoteSentences,
      });
      body += `\`〔${index}〕\``;
    } else {
      body += m[0];
    }
    last = m.index + m[0].length;
  }
  body += normalized.slice(last);
  return { body, slots };
}

export type TimeRangeMatch = {
  full: string;
  startRaw: string;
  endRaw: string;
  startMs: number;
  endMs: number;
};

/** 与 `PAREN_TIME_RANGE_RE` 分组一致：m[1]/m[4] 为整段起止（可含毫秒逗号） */
export function matchTimeRange(m: RegExpExecArray): TimeRangeMatch | null {
  const startRaw = m[1] ?? "";
  const endRaw = m[4] ?? "";
  const startMs = parseFlexibleHmsToMs(startRaw);
  const endMs = parseFlexibleHmsToMs(endRaw);
  if (!Number.isFinite(startMs) || !Number.isFinite(endMs)) return null;
  return { full: m[0], startRaw, endRaw, startMs, endMs };
}

/** 取与区间有交集的句子，按时间排序 */
export function sentencesForRange(
  sentences: TranscriptSentence[] | null | undefined,
  startMs: number,
  endMs: number
): TranscriptSentence[] {
  if (!sentences?.length) return [];
  const lo = Math.min(startMs, endMs);
  const hi = Math.max(startMs, endMs);
  return sentences
    .filter((s) => s.start_ms < hi && s.end_ms > lo)
    .sort((a, b) => a.start_ms - b.start_ms);
}

/** 取与区间有交集的句子，按时间排序后拼成一段引用文案 */
export function quoteTextForRange(
  sentences: TranscriptSentence[] | null | undefined,
  startMs: number,
  endMs: number,
  maxChars = 2800
): string {
  const parts = sentencesForRange(sentences, startMs, endMs);
  let t = parts.map((p) => p.text.trim()).filter(Boolean).join(" ");
  if (t.length > maxChars) t = `${t.slice(0, maxChars)}…`;
  return t;
}
