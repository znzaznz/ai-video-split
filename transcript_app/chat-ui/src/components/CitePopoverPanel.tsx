import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { citeVerifyCacheKey } from "@/lib/citeVerifyKey";
import {
  getCiteVerifyInflight,
  getCiteVerifyState,
  resolveInitialCiteVerifyState,
  runCiteVerify,
  setCiteVerifyState,
  type CiteVerifyState,
} from "@/lib/citeVerifySession";
import type { TranscriptSentence } from "@/types/chat";
import { CiteQuoteRows } from "./CiteQuoteRows";
import { MarkdownExternalLink } from "./MarkdownExternalLink";

type Props = {
  claimText: string;
  quoteText: string;
  quoteSentences?: TranscriptSentence[];
  startLabel: string;
  endLabel: string;
  nav?: ReactNode;
  /** 已从持久化恢复的查证报告（有则直接展示「原稿 / 查证结果」） */
  persistedReport?: string | null;
  /** 查证成功写入持久化 */
  onPersistReport?: (report: string) => void;
};

type CiteTab = "draft" | "verify";

export function CitePopoverPanel({
  claimText,
  quoteText,
  quoteSentences = [],
  startLabel,
  endLabel,
  nav,
  persistedReport = null,
  onPersistReport,
}: Props) {
  const claim = claimText.trim();
  const quote = quoteText.trim();
  const verifyTarget = claim || quote;
  const cacheKey = citeVerifyCacheKey(startLabel, endLabel, claimText, quoteText);
  const [state, setState] = useState<CiteVerifyState>(() =>
    resolveInitialCiteVerifyState(cacheKey, persistedReport)
  );
  const [activeTab, setActiveTab] = useState<CiteTab>("draft");
  const prevShowTabsRef = useRef(false);

  useEffect(() => {
    if (!persistedReport) return;
    const done: CiteVerifyState = { status: "done", report: persistedReport };
    setState((prev) => {
      if (prev.status === "done" && prev.report === persistedReport) return prev;
      return done;
    });
    setCiteVerifyState(cacheKey, done);
  }, [cacheKey, persistedReport]);

  useEffect(() => {
    const inflight = getCiteVerifyInflight(cacheKey);
    if (inflight) {
      setState({ status: "loading" });
      let cancelled = false;
      void inflight.then((result) => {
        if (!cancelled) setState(result);
      });
      return () => {
        cancelled = true;
      };
    }
    const session = getCiteVerifyState(cacheKey);
    if (session && session.status !== "idle") {
      setState(session);
    }
  }, [cacheKey]);

  const executeVerify = useCallback(
    async (opts?: { bypassCache?: boolean }) => {
      if (!opts?.bypassCache) {
        const cached = getCiteVerifyState(cacheKey);
        if (cached?.status === "done") {
          setState(cached);
          return;
        }
      }
      setState({ status: "loading" });
      const result = await runCiteVerify(
        cacheKey,
        {
          claimText: verifyTarget,
          quoteText: quote,
          startLabel,
          endLabel,
        },
        { bypassCache: opts?.bypassCache, onPersist: onPersistReport }
      );
      setState(result);
    },
    [cacheKey, endLabel, onPersistReport, quote, startLabel, verifyTarget]
  );

  const runVerify = useCallback(
    async (e: React.MouseEvent, opts?: { bypassCache?: boolean }) => {
      e.stopPropagation();
      await executeVerify(opts);
    },
    [executeVerify]
  );

  const showTabs = state.status === "done" || state.status === "error";

  useEffect(() => {
    if (showTabs && !prevShowTabsRef.current) {
      setActiveTab("draft");
    }
    prevShowTabsRef.current = showTabs;
  }, [showTabs]);

  const headerBtnLabel =
    state.status === "loading"
      ? "查证中…"
      : state.status === "done"
        ? "重新查证"
        : "联网查证";

  return (
    <div
      className={`chat-cite-popover-inner${showTabs ? " chat-cite-popover-inner--verified" : ""}`}
    >
      {nav}
      <div className="chat-cite-popover-head">
        <span className="chat-cite-popover-time">
          {startLabel}
          {" — "}
          {endLabel}
        </span>
        <button
          type="button"
          className="chat-cite-verify-btn"
          disabled={!verifyTarget || state.status === "loading"}
          onClick={(e) =>
            void runVerify(e, { bypassCache: state.status === "done" })
          }
        >
          {headerBtnLabel}
        </button>
      </div>
      <div className="chat-cite-popover-body">
        {!showTabs ? (
          <CiteQuoteRows
            sentences={quoteSentences}
            fallbackQuote={quote}
            startLabel={startLabel}
            endLabel={endLabel}
          />
        ) : (
          <>
            <div
              className="chat-cite-popover-tabs"
              role="tablist"
              aria-label="原稿与查证"
            >
              <button
                type="button"
                role="tab"
                id="cite-tab-draft"
                aria-controls="cite-tabpanel"
                aria-selected={activeTab === "draft"}
                className={`chat-cite-popover-tab${activeTab === "draft" ? " chat-cite-popover-tab--active" : ""}`}
                onClick={(e) => {
                  e.stopPropagation();
                  setActiveTab("draft");
                }}
              >
                原稿
              </button>
              <button
                type="button"
                role="tab"
                id="cite-tab-verify"
                aria-controls="cite-tabpanel"
                aria-selected={activeTab === "verify"}
                className={`chat-cite-popover-tab${activeTab === "verify" ? " chat-cite-popover-tab--active" : ""}`}
                onClick={(e) => {
                  e.stopPropagation();
                  setActiveTab("verify");
                }}
              >
                查证结果
              </button>
            </div>
            <div
              id="cite-tabpanel"
              role="tabpanel"
              aria-labelledby={
                activeTab === "draft" ? "cite-tab-draft" : "cite-tab-verify"
              }
              className="chat-cite-popover-tab-panel"
            >
              {activeTab === "draft" ? (
                <CiteQuoteRows
                  className="chat-cite-popover-quote--tab"
                  sentences={quoteSentences}
                  fallbackQuote={quote}
                  startLabel={startLabel}
                  endLabel={endLabel}
                />
              ) : state.status === "done" ? (
                <div className="chat-cite-verify-report chat-cite-verify-report--tab">
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    components={{ a: MarkdownExternalLink }}
                  >
                    {state.report}
                  </ReactMarkdown>
                </div>
              ) : (
                <div className="chat-cite-verify-error chat-cite-verify-error--tab">
                  {state.error}
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
