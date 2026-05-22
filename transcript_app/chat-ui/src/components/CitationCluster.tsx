import { useState } from "react";
import { useCitePopoverClick } from "@/hooks/useCitePopoverClick";
import type { CitationRef, TranscriptSentence } from "@/types/chat";
import { citeVerifyCacheKey } from "@/lib/citeVerifyKey";
import { parseFlexibleHmsToMs, sentencesForRange } from "@/lib/transcriptTime";
import { CitePopoverFloating } from "./CitePopoverFloating";
import { CitePopoverPanel } from "./CitePopoverPanel";

type Props = {
  label: string;
  refs: CitationRef[];
  sentences?: TranscriptSentence[] | null;
  verifyReports?: Record<string, string> | null;
  onVerifyPersist?: (cacheKey: string, report: string) => void;
};

/** 内联出处药丸：点击展开时间与原文 */
export function CitationCluster({
  label,
  refs,
  sentences = null,
  verifyReports = null,
  onVerifyPersist,
}: Props) {
  const [idx, setIdx] = useState(0);
  const { open, anchorRef, toggle, close } = useCitePopoverClick();

  const extra = refs.length > 1 ? `+${refs.length - 1}` : "";
  const r = refs[idx] ?? refs[0];
  const persistOn = typeof onVerifyPersist === "function";
  const persistKey = r ? citeVerifyCacheKey(r.start_hms, r.end_hms, label, r.text) : "";
  const savedForRef =
    persistOn && persistKey && verifyReports ? verifyReports[persistKey] ?? null : null;

  const quoteSentences = (() => {
    if (!r || !sentences?.length) return [];
    const startMs = parseFlexibleHmsToMs(r.start_hms);
    const endMs = parseFlexibleHmsToMs(r.end_hms);
    if (!Number.isFinite(startMs) || !Number.isFinite(endMs)) return [];
    return sentencesForRange(sentences, startMs, endMs);
  })();

  const nav =
    refs.length > 1 ? (
      <div className="chat-cite-popover-nav">
        <span>
          <button
            type="button"
            className="chat-cite-nav-btn"
            aria-label="上一条出处"
            disabled={idx <= 0}
            onClick={(e) => {
              e.stopPropagation();
              setIdx((i) => Math.max(0, i - 1));
            }}
          >
            ←
          </button>
          <button
            type="button"
            className="chat-cite-nav-btn"
            aria-label="下一条出处"
            disabled={idx >= refs.length - 1}
            onClick={(e) => {
              e.stopPropagation();
              setIdx((i) => Math.min(refs.length - 1, i + 1));
            }}
          >
            →
          </button>
        </span>
        <span>
          {idx + 1}/{refs.length}
        </span>
      </div>
    ) : undefined;

  return (
    <span className="chat-ts-chip-wrap chat-cite-cluster-wrap">
      <button
        ref={anchorRef}
        type="button"
        className={`chat-ts-chip-btn${open ? " chat-ts-chip-btn--open" : ""}`}
        aria-expanded={open}
        aria-haspopup="dialog"
        title="点击查看出处，可联网查证"
        onClick={toggle}
      >
        <span className="chat-ts-chip-dot" aria-hidden>
          ●
        </span>
        {label}
        {extra ? <span style={{ opacity: 0.85 }}>{extra}</span> : null}
      </button>
      {r ? (
        <CitePopoverFloating open={open} anchorRef={anchorRef} onClose={close}>
          <CitePopoverPanel
            key={`${r.start_hms}-${r.end_hms}-${idx}`}
            claimText={label}
            quoteText={r.text}
            quoteSentences={quoteSentences}
            startLabel={r.start_hms}
            endLabel={r.end_hms}
            nav={nav}
            persistedReport={savedForRef}
            onPersistReport={
              persistOn && onVerifyPersist
                ? (report) => onVerifyPersist(persistKey, report)
                : undefined
            }
          />
        </CitePopoverFloating>
      ) : null}
    </span>
  );
}
