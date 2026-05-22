import { useCallback, useEffect, useState } from "react";
import type { TranscriptSentence } from "@/types/chat";
import { copyToClipboard, formatSentenceForCopy } from "@/lib/copyToClipboard";

type Props = {
  sentences: TranscriptSentence[];
  /** 无逐句数据时的整段原文 */
  fallbackQuote?: string;
  startLabel: string;
  endLabel: string;
  className?: string;
};

export function CiteQuoteRows({
  sentences,
  fallbackQuote = "",
  startLabel,
  endLabel,
  className = "",
}: Props) {
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const [copyAllHint, setCopyAllHint] = useState<string | null>(null);

  useEffect(() => {
    if (copiedKey === null) return;
    const t = window.setTimeout(() => setCopiedKey(null), 2000);
    return () => window.clearTimeout(t);
  }, [copiedKey]);

  useEffect(() => {
    if (!copyAllHint) return;
    const t = window.setTimeout(() => setCopyAllHint(null), 2000);
    return () => window.clearTimeout(t);
  }, [copyAllHint]);

  const copyOne = useCallback(async (index: number) => {
    const s = sentences[index];
    if (!s) return;
    const r = await copyToClipboard(formatSentenceForCopy(s));
    if (r.ok) setCopiedKey(`s-${index}`);
    else setCopyAllHint(r.error);
  }, [sentences]);

  const copyBlock = useCallback(async () => {
    const text =
      sentences.length > 0
        ? sentences.map(formatSentenceForCopy).join("\n")
        : fallbackQuote.trim()
          ? `${startLabel}–${endLabel} ${fallbackQuote.trim()}`
          : "";
    const r = await copyToClipboard(text);
    if (r.ok) setCopyAllHint("已复制");
    else setCopyAllHint(r.error);
  }, [sentences, fallbackQuote, startLabel, endLabel]);

  if (sentences.length > 0) {
    return (
      <div className={`cite-quote-rows${className ? ` ${className}` : ""}`}>
        <div className="cite-quote-rows-toolbar">
          <button type="button" className="cite-quote-copy-all" onClick={() => void copyBlock()}>
            {copyAllHint ?? "复制本段全部"}
          </button>
        </div>
        <ul className="cite-quote-sentence-list">
          {sentences.map((s, i) => {
            const key = `s-${i}`;
            return (
              <li key={key} className="cite-quote-sentence-row">
                <div className="cite-quote-sentence-time">
                  {s.start_hms}
                  <span className="cite-quote-sentence-time-sep"> – </span>
                  {s.end_hms}
                </div>
                <p className="cite-quote-sentence-text">{s.text}</p>
                <button
                  type="button"
                  className="cite-quote-sentence-copy"
                  onClick={(e) => {
                    e.stopPropagation();
                    void copyOne(i);
                  }}
                >
                  {copiedKey === key ? "已复制" : "复制"}
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    );
  }

  const quote = fallbackQuote.trim();
  return (
    <div className={`cite-quote-rows cite-quote-rows--fallback${className ? ` ${className}` : ""}`}>
      {quote ? (
        <>
          <div className="chat-cite-popover-quote">{quote}</div>
          <button
            type="button"
            className="cite-quote-copy-all cite-quote-copy-all--solo"
            onClick={() => void copyBlock()}
          >
            {copyAllHint ?? "复制原文"}
          </button>
        </>
      ) : (
        <div className="chat-cite-popover-quote">（当前稿中未匹配到重叠句，或尚未加载转写）</div>
      )}
    </div>
  );
}
