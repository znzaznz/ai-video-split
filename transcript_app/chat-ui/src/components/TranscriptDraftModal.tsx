import { useCallback, useEffect, useId, useState } from "react";
import type { ParsedItem } from "@/types/parsed";
import {
  copyToClipboard,
  formatAllSentencesForCopy,
  formatSentenceForCopy,
} from "@/lib/copyToClipboard";

type Props = {
  open: boolean;
  item: ParsedItem | null;
  onClose: () => void;
};

export function TranscriptDraftModal({ open, item, onClose }: Props) {
  const titleId = useId();
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const [copyAllHint, setCopyAllHint] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setCopiedKey(null);
      setCopyAllHint(null);
    }
  }, [open]);

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

  const flashCopied = useCallback((key: string) => {
    setCopiedKey(key);
  }, []);

  const handleCopySentence = useCallback(
    async (index: number) => {
      if (!item) return;
      const s = item.sentences[index];
      if (!s) return;
      const r = await copyToClipboard(formatSentenceForCopy(s));
      if (r.ok) flashCopied(`s-${index}`);
      else setCopyAllHint(r.error);
    },
    [item, flashCopied]
  );

  const handleCopyAll = useCallback(async () => {
    if (!item?.sentences.length) return;
    const r = await copyToClipboard(formatAllSentencesForCopy(item.sentences));
    if (r.ok) setCopyAllHint("已复制全文");
    else setCopyAllHint(r.error);
  }, [item]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open || !item) return null;

  const sentences = item.sentences;

  return (
    <div
      className="video-url-modal-backdrop transcript-draft-modal-backdrop"
      role="presentation"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="video-url-modal-panel transcript-draft-modal-panel"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="transcript-draft-modal-head">
          <div className="transcript-draft-modal-title-wrap">
            <h2 id={titleId} className="video-url-modal-title">
              转写原稿
            </h2>
            <p className="transcript-draft-modal-subtitle" title={item.path}>
              {item.label}
              <span className="transcript-draft-modal-meta"> · {sentences.length} 句</span>
            </p>
          </div>
          <div className="transcript-draft-modal-actions">
            <button
              type="button"
              className="video-url-modal-btn secondary"
              disabled={!sentences.length}
              onClick={() => void handleCopyAll()}
            >
              {copyAllHint ?? "复制全文"}
            </button>
            <button type="button" className="video-url-modal-btn secondary" onClick={onClose}>
              关闭
            </button>
          </div>
        </div>
        <div className="transcript-draft-modal-body">
          {sentences.length === 0 ? (
            <p className="transcript-draft-modal-empty">暂无句子数据</p>
          ) : (
            <ul className="transcript-sentence-list">
              {sentences.map((s, i) => {
                const rowKey = `s-${i}`;
                const copied = copiedKey === rowKey;
                return (
                  <li key={rowKey} className="transcript-sentence-row">
                    <div className="transcript-sentence-time" title={`${s.start_hms} – ${s.end_hms}`}>
                      <span className="transcript-sentence-time-start">{s.start_hms}</span>
                      <span className="transcript-sentence-time-sep"> – </span>
                      <span className="transcript-sentence-time-end">{s.end_hms}</span>
                    </div>
                    <p className="transcript-sentence-text">{s.text}</p>
                    <button
                      type="button"
                      className="transcript-sentence-copy"
                      title="复制该句（含时间）"
                      onClick={() => void handleCopySentence(i)}
                    >
                      {copied ? "已复制" : "复制"}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
