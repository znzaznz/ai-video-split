import { useMemo, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { TranscriptSentence } from "@/types/chat";
import { citeVerifyCacheKey } from "@/lib/citeVerifyKey";
import { injectCitationMarkdownSlots, type CitationSlot } from "@/lib/transcriptTime";
import { MarkdownExternalLink } from "./MarkdownExternalLink";
import { TimestampSpanChip } from "./TimestampSpanChip";

export type CiteVerifyBridge = {
  reports: Record<string, string>;
  onPersist: (cacheKey: string, report: string) => void;
};

type Props = {
  text: string;
  sentences: TranscriptSentence[] | null | undefined;
  /** 助手：Markdown + 时间轴；用户：纯文本 + 时间轴 */
  enableMarkdown?: boolean;
  citeVerify?: CiteVerifyBridge | null;
};

function CiteChip({
  slot,
  citeVerifyRef,
}: {
  slot: CitationSlot;
  citeVerifyRef: React.MutableRefObject<CiteVerifyBridge | null | undefined>;
}) {
  const citeVerify = citeVerifyRef.current;
  const ck = citeVerifyCacheKey(slot.startLabel, slot.endLabel, slot.claimText, slot.quoteText);
  const saved = citeVerify?.reports[ck] ?? null;
  const onPersist = citeVerify ? (report: string) => citeVerify.onPersist(ck, report) : undefined;
  return (
    <TimestampSpanChip
      label={slot.label}
      startLabel={slot.startLabel}
      endLabel={slot.endLabel}
      claimText={slot.claimText}
      quoteText={slot.quoteText}
      quoteSentences={slot.quoteSentences}
      savedVerifyReport={saved}
      onVerifyPersist={onPersist}
    />
  );
}

function makeMarkdownComponents(
  slots: CitationSlot[],
  citeVerifyRef: React.MutableRefObject<CiteVerifyBridge | null | undefined>
) {
  return {
    a: MarkdownExternalLink,
    code: ({
      children,
      className,
      ...rest
    }: React.HTMLAttributes<HTMLElement> & { className?: string }) => {
      const raw = String(children).replace(/\n$/, "");
      const m = raw.match(/^〔(\d+)〕$/);
      if (m && !className) {
        const slot = slots[Number(m[1])];
        if (slot) return <CiteChip slot={slot} citeVerifyRef={citeVerifyRef} />;
      }
      return (
        <code className={className} {...rest}>
          {children}
        </code>
      );
    },
  };
}

function PlainWithCites({
  body,
  slots,
  citeVerifyRef,
}: {
  body: string;
  slots: CitationSlot[];
  citeVerifyRef: React.MutableRefObject<CiteVerifyBridge | null | undefined>;
}) {
  const re = /`〔(\d+)〕`/g;
  const nodes: React.ReactNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  let key = 0;
  while ((m = re.exec(body)) !== null) {
    if (m.index > last) {
      nodes.push(<span key={`t${key++}`}>{body.slice(last, m.index)}</span>);
    }
    const slot = slots[Number(m[1])];
    if (slot) nodes.push(<CiteChip key={`c${key++}`} slot={slot} citeVerifyRef={citeVerifyRef} />);
    else nodes.push(<span key={`x${key++}`}>{m[0]}</span>);
    last = m.index + m[0].length;
  }
  if (last < body.length) nodes.push(<span key={`t${key++}`}>{body.slice(last)}</span>);
  return <span className="chat-plain-wrap chat-rich-inline">{nodes}</span>;
}

export function RichAssistantContent({
  text,
  sentences,
  enableMarkdown = true,
  citeVerify = null,
}: Props) {
  const citeVerifyRef = useRef(citeVerify);
  citeVerifyRef.current = citeVerify;

  const { body, slots } = useMemo(
    () => injectCitationMarkdownSlots(text, sentences),
    [text, sentences]
  );

  const markdownComponents = useMemo(
    () => makeMarkdownComponents(slots, citeVerifyRef),
    [slots]
  );

  if (!enableMarkdown) {
    if (slots.length === 0) {
      return <span className="chat-plain-wrap">{body}</span>;
    }
    return <PlainWithCites body={body} slots={slots} citeVerifyRef={citeVerifyRef} />;
  }

  return (
    <div className="chat-markdown chat-markdown--with-cites">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
        {body}
      </ReactMarkdown>
    </div>
  );
}
