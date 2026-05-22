import type { TranscriptSentence } from "@/types/chat";
import { useCitePopoverClick } from "@/hooks/useCitePopoverClick";
import { CitePopoverFloating } from "./CitePopoverFloating";
import { CitePopoverPanel } from "./CitePopoverPanel";

type Props = {
  label: string;
  startLabel: string;
  endLabel: string;
  claimText: string;
  quoteText: string;
  quoteSentences?: TranscriptSentence[];
  /** 持久化恢复的查证报告；有则弹窗内展示「原稿 / 查证结果」 */
  savedVerifyReport?: string | null;
  /** 查证成功后写入持久化 */
  onVerifyPersist?: (report: string) => void;
};

/** 模型输出中的时间轴括号：点击展示该时段在稿中的原话 */
export function TimestampSpanChip({
  label,
  startLabel,
  endLabel,
  claimText,
  quoteText,
  quoteSentences = [],
  savedVerifyReport = null,
  onVerifyPersist,
}: Props) {
  const { open, anchorRef, toggle, close } = useCitePopoverClick();
  const shortLabel = label.replace(/^\(|\)$/g, "");

  return (
    <span className="chat-ts-chip-wrap">
      <button
        ref={anchorRef}
        type="button"
        className={`chat-ts-chip-btn${open ? " chat-ts-chip-btn--open" : ""}`}
        aria-expanded={open}
        aria-haspopup="dialog"
        title="点击查看稿内原话，可联网查证"
        onClick={toggle}
      >
        <span className="chat-ts-chip-dot" aria-hidden>
          ●
        </span>
        <span className="chat-ts-chip-label">{shortLabel}</span>
      </button>
      <CitePopoverFloating open={open} anchorRef={anchorRef} onClose={close}>
        <CitePopoverPanel
          claimText={claimText.trim()}
          quoteText={quoteText.trim()}
          quoteSentences={quoteSentences}
          startLabel={startLabel}
          endLabel={endLabel}
          persistedReport={savedVerifyReport}
          onPersistReport={onVerifyPersist}
        />
      </CitePopoverFloating>
    </span>
  );
}
