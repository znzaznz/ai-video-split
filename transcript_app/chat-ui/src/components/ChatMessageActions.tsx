import { useCallback, useEffect, useState } from "react";
import type { MessageSegment } from "@/types/chat";
import { copyToClipboard } from "@/lib/copyToClipboard";
import { segmentsToPlainText } from "@/lib/messageText";

type Props = {
  segments: MessageSegment[];
  disabled?: boolean;
  onDelete: () => void;
  deleteTitle?: string;
};

function CopyIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20 6 9 17l-5-5" />
    </svg>
  );
}

function DeleteIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 6h18" />
      <path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6" />
      <path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" />
      <line x1="10" y1="11" x2="10" y2="17" />
      <line x1="14" y1="11" x2="14" y2="17" />
    </svg>
  );
}

export function ChatMessageActions({
  segments,
  disabled = false,
  onDelete,
  deleteTitle = "删除此条",
}: Props) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const t = window.setTimeout(() => setCopied(false), 2000);
    return () => window.clearTimeout(t);
  }, [copied]);

  const handleCopy = useCallback(async () => {
    const text = segmentsToPlainText(segments);
    const r = await copyToClipboard(text);
    if (r.ok) setCopied(true);
  }, [segments]);

  const empty = !segmentsToPlainText(segments);

  return (
    <div className="chat-msg-actions">
      <button
        type="button"
        className={`chat-msg-icon-btn chat-msg-copy${copied ? " chat-msg-copy--done" : ""}`}
        title={copied ? "已复制" : "复制本条对话"}
        aria-label={copied ? "已复制" : "复制本条对话"}
        disabled={disabled || empty}
        onClick={() => void handleCopy()}
      >
        {copied ? <CheckIcon /> : <CopyIcon />}
      </button>
      <button
        type="button"
        className="chat-msg-icon-btn chat-msg-delete"
        title={deleteTitle}
        aria-label={deleteTitle}
        disabled={disabled}
        onClick={onDelete}
      >
        <DeleteIcon />
      </button>
    </div>
  );
}
