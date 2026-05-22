import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { MessageSegment, TranscriptSentence } from "@/types/chat";
import type { GeminiChatPayload } from "@/types/gemini";
import type { ParsedItem } from "@/types/parsed";
import { parseVideoUrl, openTranscriptFile } from "@/lib/platform";
import { useTheme } from "@/hooks/useTheme";
import { CitationCluster } from "@/components/CitationCluster";
import { RichAssistantContent, type CiteVerifyBridge } from "@/components/RichAssistantContent";
import { ThemeToggle } from "@/components/ThemeToggle";
import { LoadTranscriptButton } from "@/components/LoadTranscriptButton";
import { ParsedListSidebar } from "@/components/ParsedListSidebar";
import { ChatMessageActions } from "@/components/ChatMessageActions";
import { TranscriptDraftModal } from "@/components/TranscriptDraftModal";
import { VideoUrlModal } from "@/components/VideoUrlModal";
import { SettingsModal } from "@/components/SettingsModal";
import { getApiSettings } from "@/lib/apiSettings";
import { loadPersisted, savePersisted, CHAT_UI_STORAGE_KEY, type PersistedMessage, type PersistV2 } from "@/lib/chatPersistence";
import { roughTokenEstimate } from "@/lib/estimateTokens";
import { segmentsToPlainText } from "@/lib/messageText";

function uid(): string {
  return crypto.randomUUID?.() ?? `m-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

/** 侧栏与引导语：流水线在「任务目录/result.json」，用目录名（与 task_manifest.task_name 一致）而非文件名 */
function labelFromPath(path: string): string {
  const parts = path.split(/[/\\]/);
  const file = parts[parts.length - 1] || path;
  const parent = parts.length >= 2 ? parts[parts.length - 2] : "";
  if (parent && /^result\.json$/i.test(file)) return parent;
  return file || path;
}

function buildIntroSegments(path: string, sents: TranscriptSentence[]): MessageSegment[] {
  const name = labelFromPath(path);
  return [
    {
      kind: "text",
      text: `已加载转写「${name}」，共 ${sents.length} 句。可直接在下方提问`,
    },
  ];
}

function apiThreadFromMessages(msgs: { role: "user" | "assistant"; segments: MessageSegment[] }[]) {
  let t = [...msgs];
  while (t.length && t[0].role === "assistant") t = t.slice(1);
  return t;
}

function buildSystemPrompt(sentences: TranscriptSentence[] | null, pathLabel: string): string {
  const base = `你是协助理解视频口播转写稿的助手。回答要冷静、清楚；材料不足就说明依据不足，不要编造。
若引用转写内容，请尽量带上原稿中的时间区间，使用半角括号包裹，格式如 (00:03:48-00:03:53)（与稿内时间轴一致，便于用户悬浮查看原话）。
回答可使用 Markdown：适当使用 ### 小标题、**加粗**、列表等，便于阅读。
【篇幅】默认回答控制在约 1000–2000 token 当量（精炼、抓重点），不要长篇铺陈。仅当用户明确要求更长、更细、全文整理、逐条展开等时，才可写得更长。`;
  if (!sentences?.length) {
    return `${base}\n当前用户尚未加载 result.json。请提示用户通过顶栏链接按钮或中间区域打开弹窗，输入 B 站链接或导入句级稿后再深入问答。`;
  }
  const raw = JSON.stringify(sentences);
  const max = 380_000;
  const truncated = raw.length > max;
  const json = truncated ? raw.slice(0, max) + "\n…(已截断，后续句未传入)" : raw;
  return `${base}\n以下为用户已加载的转写文件：${pathLabel}\n句级 JSON：\n${json}`;
}

export function App() {
  const [theme, setTheme] = useTheme();
  const [parsedItems, setParsedItems] = useState<ParsedItem[]>([]);
  const [activeItemId, setActiveItemId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [urlModalOpen, setUrlModalOpen] = useState(false);
  const [parseModalError, setParseModalError] = useState<string | null>(null);
  const [parseBusy, setParseBusy] = useState(false);
  const [parsePhase, setParsePhase] = useState<"idle" | "douyin-login" | "running">("idle");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsShowDefer, setSettingsShowDefer] = useState(false);
  const [hasGeminiKey, setHasGeminiKey] = useState(false);
  const [geminiMasked, setGeminiMasked] = useState<string | undefined>();
  const [savedHint, setSavedHint] = useState<string | null>(null);
  const [draftModalItem, setDraftModalItem] = useState<ParsedItem | null>(null);
  const listRef = useRef<HTMLDivElement>(null);

  /** 内联：助手正在生成（列表底部、输入框上方） */
  type PendingAssistant =
    | { id: string; kind: "pending"; phase: "loading" | "streaming"; text: string }
    | { id: string; kind: "error"; text: string; error: string };

  const [pendingAssistant, setPendingAssistant] = useState<PendingAssistant | null>(null);
  const pendingAccumRef = useRef("");
  const pendingIdRef = useRef("");

  const activeItem = useMemo(
    () => parsedItems.find((i) => i.id === activeItemId) ?? null,
    [parsedItems, activeItemId]
  );
  const sentences = activeItem?.sentences ?? null;
  const transcriptPath = activeItem?.path ?? null;
  const transcriptTitle = activeItem?.label ?? (transcriptPath ? labelFromPath(transcriptPath) : "(未加载)");

  const [messages, setMessages] = useState<
    { id: string; role: "user" | "assistant"; segments: MessageSegment[] }[]
  >([]);
  const messagesRef = useRef(messages);
  messagesRef.current = messages;

  const [verifyByItemId, setVerifyByItemId] = useState<Record<string, Record<string, string>>>({});

  const handlePersistVerify = useCallback((cacheKey: string, report: string) => {
    if (!activeItemId) return;
    setVerifyByItemId((prev) => ({
      ...prev,
      [activeItemId]: { ...(prev[activeItemId] ?? {}), [cacheKey]: report },
    }));
  }, [activeItemId]);

  /** 每条侧栏稿 id → 一套对话，切换稿时恢复；仅「清空对话 / 清空全部」会丢 */
  const threadsRef = useRef<Record<string, PersistedMessage[]>>({});
  const [hydrated, setHydrated] = useState(false);

  const tokenEstimate = useMemo(() => {
    const system = buildSystemPrompt(sentences, transcriptTitle);
    const apiThread = apiThreadFromMessages(messages);
    let conv = "";
    for (const msg of apiThread) {
      conv += `${segmentsToPlainText(msg.segments)}\n\n`;
    }
    const systemTokens = roughTokenEstimate(system);
    const convTokens = roughTokenEstimate(conv);
    return { systemTokens, convTokens, totalIn: systemTokens + convTokens };
  }, [messages, sentences, transcriptTitle]);

  const scrollToBottom = () => {
    requestAnimationFrame(() => {
      const el = listRef.current;
      if (el) el.scrollTop = el.scrollHeight;
    });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, pendingAssistant]);

  useEffect(() => {
    return () => {
      window.bbChat?.setGeminiStreamHandlers?.(null);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      let saved: PersistV2 | null = loadPersisted();
      if (!saved?.items?.length && window.bbChat?.loadAppPersist) {
        try {
          const disk = await window.bbChat.loadAppPersist();
          if (disk.ok && disk.json) {
            const parsed = JSON.parse(disk.json) as PersistV2;
            if (parsed?.v === 2 && Array.isArray(parsed.items) && parsed.items.length > 0) {
              saved = parsed;
              savePersisted(parsed);
            }
          }
        } catch {
          /* 损坏或版本不兼容则忽略 */
        }
      }
      if (cancelled) return;
      if (saved?.items?.length) {
        threadsRef.current = { ...saved.threadsByItemId };
        setVerifyByItemId(
          saved.verifyByItemId && typeof saved.verifyByItemId === "object"
            ? { ...saved.verifyByItemId }
            : {}
        );
        setParsedItems(saved.items.map((it) => ({ ...it, label: labelFromPath(it.path) })));
        const act = saved.activeId;
        const actValid = !!(act && saved.items.some((x) => x.id === act));
        const chosenId = actValid ? act! : saved.items[0]!.id;
        setActiveItemId(chosenId);
        const it = saved.items.find((x) => x.id === chosenId)!;
        const thread = threadsRef.current[chosenId];
        if (thread?.length) {
          setMessages(thread);
          messagesRef.current = thread;
        } else {
          const intro = [
            { id: uid(), role: "assistant" as const, segments: buildIntroSegments(it.path, it.sentences) },
          ];
          setMessages(intro);
          messagesRef.current = intro;
          threadsRef.current[chosenId] = intro;
        }
      }
      setHydrated(true);
    };
    void run();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    if (activeItemId) threadsRef.current[activeItemId] = messages;
    const t = window.setTimeout(() => {
      const payload: PersistV2 = {
        v: 2,
        items: parsedItems,
        activeId: activeItemId,
        threadsByItemId: { ...threadsRef.current },
        verifyByItemId: { ...verifyByItemId },
      };
      savePersisted(payload);
      const json = JSON.stringify(payload);
      void window.bbChat?.saveAppPersist?.(json);
    }, 450);
    return () => window.clearTimeout(t);
  }, [hydrated, parsedItems, activeItemId, messages, verifyByItemId]);

  const refreshApiSettings = useCallback(async () => {
    const s = await getApiSettings();
    setHasGeminiKey(s.hasGeminiKey);
    setGeminiMasked(s.geminiMasked);
    return s;
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    void (async () => {
      const s = await getApiSettings();
      setHasGeminiKey(s.hasGeminiKey);
      setGeminiMasked(s.geminiMasked);
      if (!s.hasGeminiKey) {
        setSettingsShowDefer(true);
        setSettingsOpen(true);
      }
    })();
  }, [hydrated]);

  const clearParseModalError = useCallback(() => setParseModalError(null), []);

  useEffect(() => {
    const unsub = window.bbChat?.onParseStatus?.((p) => {
      setParsePhase(p.phase);
    });
    return () => unsub?.();
  }, []);

  const ingestTranscriptResult = useCallback(
    (r: { path: string; sentences: TranscriptSentence[] }) => {
      const label = labelFromPath(r.path);
      const existing = parsedItems.find((p) => p.path === r.path);
      if (existing) {
        setParsedItems((prev) =>
          prev.map((p) => (p.path === r.path ? { ...p, sentences: r.sentences, label } : p))
        );
        setActiveItemId(existing.id);
        return;
      }
      const activeId = uid();
      if (activeItemId) {
        threadsRef.current[activeItemId] = [...messagesRef.current];
      }
      setParsedItems((prev) => [...prev, { id: activeId, path: r.path, label, sentences: r.sentences }]);
      setActiveItemId(activeId);
      const intro = [
        { id: uid(), role: "assistant" as const, segments: buildIntroSegments(r.path, r.sentences) },
      ];
      setMessages(intro);
      messagesRef.current = intro;
      threadsRef.current[activeId] = intro;
    },
    [parsedItems, activeItemId]
  );

  const openParseModal = useCallback(() => {
    setParseModalError(null);
    setUrlModalOpen(true);
  }, []);

  const openDraftModal = useCallback(
    (id: string) => {
      const it = parsedItems.find((p) => p.id === id);
      if (it) setDraftModalItem(it);
    },
    [parsedItems]
  );

  const handleSubmitParseUrl = useCallback(
    async (url: string) => {
      setParseModalError(null);
      setParseBusy(true);
      try {
        const r = await parseVideoUrl(url);
        if (!r.ok) {
          setParseModalError(r.error);
          return;
        }
        ingestTranscriptResult(r);
        setUrlModalOpen(false);
      } catch (e) {
        setParseModalError(e instanceof Error ? e.message : String(e));
      } finally {
        setParseBusy(false);
        setParsePhase("idle");
      }
    },
    [ingestTranscriptResult]
  );

  const handleImportJsonFromModal = useCallback(async () => {
    setParseModalError(null);
    setParseBusy(true);
    try {
      const r = await openTranscriptFile();
      if (!r.ok) {
        if (r.error !== "已取消") setParseModalError(r.error);
        return;
      }
      ingestTranscriptResult(r);
      setUrlModalOpen(false);
    } catch (e) {
      setParseModalError(e instanceof Error ? e.message : String(e));
    } finally {
      setParseBusy(false);
      setParsePhase("idle");
    }
  }, [ingestTranscriptResult]);

  const selectParsedItem = useCallback(
    (id: string) => {
      if (id === activeItemId) return;
      if (activeItemId) {
        threadsRef.current[activeItemId] = [...messagesRef.current];
      }
      const it = parsedItems.find((x) => x.id === id);
      if (!it) return;
      setActiveItemId(id);
      const cached = threadsRef.current[id];
      if (cached?.length) {
        setMessages(cached);
        messagesRef.current = cached;
      } else {
        const intro = [
          { id: uid(), role: "assistant" as const, segments: buildIntroSegments(it.path, it.sentences) },
        ];
        setMessages(intro);
        messagesRef.current = intro;
        threadsRef.current[id] = intro;
      }
    },
    [activeItemId, parsedItems]
  );

  const removeMessage = useCallback((id: string) => {
    setMessages((prev) => {
      const n = prev.filter((m) => m.id !== id);
      messagesRef.current = n;
      return n;
    });
  }, []);

  const clearConversation = useCallback(() => {
    if (!activeItem || !sentences?.length) {
      setMessages([]);
      messagesRef.current = [];
    } else {
      const intro = [
        { id: uid(), role: "assistant" as const, segments: buildIntroSegments(activeItem.path, sentences) },
      ];
      setMessages(intro);
      messagesRef.current = intro;
      threadsRef.current[activeItem.id] = intro;
    }
    setPendingAssistant(null);
    pendingAccumRef.current = "";
  }, [activeItem, sentences?.length]);

  const removeParsedItem = useCallback(
    (id: string) => {
      delete threadsRef.current[id];
      setVerifyByItemId((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
      const next = parsedItems.filter((p) => p.id !== id);
      setParsedItems(next);
      if (activeItemId !== id) return;
      if (next.length > 0) {
        const pick = next[0];
        setActiveItemId(pick.id);
        const cached = threadsRef.current[pick.id];
        if (cached?.length) {
          setMessages(cached);
          messagesRef.current = cached;
        } else {
          const intro = [
            { id: uid(), role: "assistant" as const, segments: buildIntroSegments(pick.path, pick.sentences) },
          ];
          setMessages(intro);
          messagesRef.current = intro;
          threadsRef.current[pick.id] = intro;
        }
      } else {
        setActiveItemId(null);
        setMessages([]);
        messagesRef.current = [];
      }
    },
    [parsedItems, activeItemId]
  );

  const clearAllParsedItems = useCallback(() => {
    if (parsedItems.length === 0) return;
    if (!window.confirm("确定清空全部解析记录？侧栏列表与当前对话都会清空。")) return;
    threadsRef.current = {};
    setVerifyByItemId({});
    setParsedItems([]);
    setActiveItemId(null);
    setMessages([]);
    messagesRef.current = [];
    setPendingAssistant(null);
    pendingAccumRef.current = "";
    try {
      localStorage.removeItem(CHAT_UI_STORAGE_KEY);
    } catch {
      /* ignore */
    }
    void window.bbChat?.saveAppPersist?.(
      JSON.stringify({
        v: 2,
        items: [],
        activeId: null,
        threadsByItemId: {},
        verifyByItemId: {},
      } satisfies PersistV2)
    );
  }, [parsedItems.length]);

  const cancelGeminiStream = useCallback(() => {
    void window.bbChat?.geminiChatCancel?.();
  }, []);

  const dismissPendingAssistant = useCallback(() => {
    setPendingAssistant(null);
    pendingAccumRef.current = "";
  }, []);

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || busy) return;

    if (window.bbChat) {
      let keyOk = hasGeminiKey;
      if (!keyOk) {
        const s = await getApiSettings();
        keyOk = s.hasGeminiKey;
        setHasGeminiKey(s.hasGeminiKey);
        setGeminiMasked(s.geminiMasked);
      }
      if (!keyOk) {
        setSettingsShowDefer(true);
        setSettingsOpen(true);
        setErr("请先在设置中填写 Gemini API Key");
        return;
      }
    }

    setInput("");
    setErr(null);
    const userMsg = { id: uid(), role: "user" as const, segments: [{ kind: "text" as const, text }] };
    const nextThread = [...messagesRef.current, userMsg];
    setMessages(nextThread);
    messagesRef.current = nextThread;
    setBusy(true);

    if (!window.bbChat) {
      const inElectronShell =
        typeof navigator !== "undefined" && navigator.userAgent.includes("Electron");
      const reply = {
        id: uid(),
        role: "assistant" as const,
        segments: [
          {
            kind: "text" as const,
            text: inElectronShell
              ? "当前 Electron 窗口未成功加载 preload（window.bbChat 未注入），无法走主进程 Gemini。请关掉窗口后重新执行 chat-ui 下的 npm run dev，并确认 dist-electron 下存在 preload.cjs（若只有旧的 preload.mjs，先删 dist-electron 再 dev）。"
              : "网页版目前不在浏览器里直连 Gemini（避免把 API Key 写进前端 bundle）。请使用 `npm run dev` 的 Electron 窗口发起对话；或后续接你自己的后端网关。",
          },
        ],
      };
      const withReply = [...nextThread, reply];
      setMessages(withReply);
      messagesRef.current = withReply;
      setBusy(false);
      return;
    }

    const system = buildSystemPrompt(sentences, transcriptTitle);
    const apiThread = apiThreadFromMessages(nextThread);
    const contents: GeminiChatPayload["contents"] = [];
    for (const msg of apiThread) {
      if (msg.role === "user") {
        contents.push({ role: "user", text: segmentsToPlainText(msg.segments) });
      } else {
        contents.push({ role: "model", text: segmentsToPlainText(msg.segments) });
      }
    }

    const pid = uid();
    pendingIdRef.current = pid;
    pendingAccumRef.current = "";
    setPendingAssistant({ id: pid, kind: "pending", phase: "loading", text: "" });

    window.bbChat.setGeminiStreamHandlers({
      onChunk: ({ delta }) => {
        pendingAccumRef.current += delta;
        setPendingAssistant({
          id: pendingIdRef.current,
          kind: "pending",
          phase: "streaming",
          text: pendingAccumRef.current,
        });
      },
      onDone: (p) => {
        window.bbChat?.setGeminiStreamHandlers?.(null);
        setBusy(false);
        if (p.ok) {
          const body = pendingAccumRef.current.trim();
          const ast = {
            id: uid(),
            role: "assistant" as const,
            segments: [{ kind: "text" as const, text: body || "(空回复)" }],
          };
          const done = [...messagesRef.current, ast];
          setMessages(done);
          messagesRef.current = done;
          setPendingAssistant(null);
          pendingAccumRef.current = "";
        } else if (p.canceled) {
          const partial = pendingAccumRef.current.trim();
          const line = partial ? `${partial}\n\n（已停止）` : "（已停止）";
          const ast = {
            id: uid(),
            role: "assistant" as const,
            segments: [{ kind: "text" as const, text: line }],
          };
          const done = [...messagesRef.current, ast];
          setMessages(done);
          messagesRef.current = done;
          setPendingAssistant(null);
          pendingAccumRef.current = "";
        } else {
          setErr(p.error || "未知错误");
          setPendingAssistant({
            id: pendingIdRef.current,
            kind: "error",
            text: pendingAccumRef.current.trim(),
            error: p.error || "未知错误",
          });
        }
      },
    });

    let startRes: { ok: true } | { ok: false; error: string };
    try {
      startRes = await window.bbChat.geminiChatStart({ system, contents });
    } catch (e) {
      window.bbChat.setGeminiStreamHandlers(null);
      setBusy(false);
      const msg = e instanceof Error ? e.message : String(e);
      setErr(msg);
      setPendingAssistant({
        id: pendingIdRef.current,
        kind: "error",
        text: "",
        error: msg,
      });
      return;
    }

    if (!startRes.ok) {
      window.bbChat.setGeminiStreamHandlers(null);
      setBusy(false);
      setErr(startRes.error);
      setPendingAssistant({
        id: pendingIdRef.current,
        kind: "error",
        text: "",
        error: startRes.error,
      });
    }
  }, [busy, input, sentences, transcriptTitle, hasGeminiKey]);

  return (
    <div className="app-outer">
      <div className="app-layout">
        <div className="app-main">
          <header
            style={{
              flexShrink: 0,
              paddingBottom: 12,
              borderBottom: "1px solid var(--border)",
              display: "flex",
              flexWrap: "wrap",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 12,
            }}
          >
            <div style={{ minWidth: 0, flex: "1 1 auto" }}>
              <h1
                style={{
                  margin: 0,
                  fontSize: "1.25rem",
                  fontWeight: 700,
                  letterSpacing: "0.02em",
                  lineHeight: 1.3,
                }}
              >
                转写查证
              </h1>
              <p
                style={{
                  margin: "6px 0 0",
                  color: "var(--muted)",
                  fontSize: 13,
                  lineHeight: 1.45,
                }}
              >
                加载视频转写稿，对话理解要点，出处可联网查证
              </p>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
              {savedHint && (
                <span style={{ fontSize: 12, color: "var(--cite)" }}>{savedHint}</span>
              )}
              <button
                type="button"
                className="video-url-modal-btn secondary"
                style={{ padding: "6px 12px", fontSize: 13 }}
                onClick={() => {
                  setSettingsShowDefer(false);
                  setSettingsOpen(true);
                }}
              >
                设置
              </button>
              <ThemeToggle theme={theme} onToggle={() => setTheme(theme === "dark" ? "light" : "dark")} />
              <LoadTranscriptButton onClick={openParseModal} />
            </div>
          </header>

          {transcriptPath && (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 10,
                paddingTop: 8,
                flexWrap: "wrap",
              }}
            >
              <div
                style={{ fontSize: 12, color: "var(--muted)", minWidth: 0, flex: "1 1 auto" }}
                title={transcriptPath}
              >
                当前稿：{transcriptTitle}
              </div>
              {sentences && (
                <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
                  <button
                    type="button"
                    className="chat-toolbar-btn"
                    title="查看当前稿全部转写句，支持逐句复制"
                    onClick={() => {
                      if (activeItemId) openDraftModal(activeItemId);
                    }}
                  >
                    查看原稿
                  </button>
                  {messages.length > 0 && (
                    <button
                      type="button"
                      className="chat-toolbar-btn"
                      disabled={busy}
                      title="清空当前稿下的全部对话消息"
                      onClick={clearConversation}
                    >
                      清空对话
                    </button>
                  )}
                </div>
              )}
            </div>
          )}

          {err && (
            <div
              style={{
                marginTop: 8,
                padding: "8px 10px",
                borderRadius: 8,
                border: "1px solid var(--err-border)",
                background: "var(--err-bg)",
                color: "var(--err-text)",
                fontSize: 13,
                whiteSpace: "pre-wrap",
              }}
            >
              {err}
            </div>
          )}

          <div
            ref={listRef}
            className={`chat-list${!sentences?.length ? " chat-list--empty" : ""}`}
            style={{
              flex: 1,
              overflowY: "auto",
              padding: "14px 0",
              display: "flex",
              flexDirection: "column",
              gap: 12,
              minHeight: 0,
            }}
          >
            {!sentences?.length ? (
              <button
                type="button"
                className="empty-upload-trigger empty-upload-box"
                onClick={openParseModal}
              >
                点击输入要解析的 B 站视频链接
              </button>
            ) : (
              <>
                {messages.map((msg) => (
                  <div
                    key={msg.id}
                    style={{
                      alignSelf: msg.role === "user" ? "flex-end" : "flex-start",
                      display: "flex",
                      alignItems: "flex-start",
                      gap: 6,
                      maxWidth: "92%",
                    }}
                  >
                    <div
                      style={{
                        flex: "1 1 auto",
                        minWidth: 0,
                        padding: "10px 12px",
                        borderRadius: 12,
                        background: msg.role === "user" ? "var(--accent)" : "var(--panel)",
                        color: msg.role === "user" ? "#fff" : "var(--text)",
                        border: msg.role === "user" ? "none" : "1px solid var(--border)",
                        fontSize: 14,
                      }}
                    >
                      <MessageBody
                        role={msg.role}
                        segments={msg.segments}
                        sentences={sentences}
                        citeVerify={
                          activeItemId
                            ? ({
                                reports: verifyByItemId[activeItemId] ?? {},
                                onPersist: handlePersistVerify,
                              } satisfies CiteVerifyBridge)
                            : null
                        }
                      />
                    </div>
                    <ChatMessageActions
                      segments={msg.segments}
                      disabled={busy}
                      onDelete={() => removeMessage(msg.id)}
                    />
                  </div>
                ))}
                {pendingAssistant && (
                  <div
                    key={pendingAssistant.id}
                    style={{
                      alignSelf: "flex-start",
                      display: "flex",
                      alignItems: "flex-start",
                      gap: 6,
                      maxWidth: "92%",
                    }}
                  >
                    <div
                      className={
                        pendingAssistant.kind === "error"
                          ? "chat-pending-bubble chat-pending-bubble--error"
                          : "chat-pending-bubble"
                      }
                    >
                      {pendingAssistant.kind === "pending" &&
                      pendingAssistant.phase === "loading" &&
                      !pendingAssistant.text ? (
                        <div className="chat-pending-loading">
                          <div className="chat-inline-spinner" aria-hidden />
                          <span>正在生成…</span>
                        </div>
                      ) : pendingAssistant.kind === "error" ? (
                        <div>
                          <div style={{ fontWeight: 600, marginBottom: 6 }}>生成失败</div>
                          <div style={{ fontSize: 13, lineHeight: 1.45 }}>{pendingAssistant.error}</div>
                          {pendingAssistant.text ? (
                        <div className="chat-pending-partial" style={{ marginTop: 8 }}>
                          <RichAssistantContent
                            text={pendingAssistant.text}
                            sentences={sentences}
                            enableMarkdown
                            citeVerify={
                              activeItemId
                                ? ({
                                    reports: verifyByItemId[activeItemId] ?? {},
                                    onPersist: handlePersistVerify,
                                  } satisfies CiteVerifyBridge)
                                : null
                            }
                          />
                        </div>
                          ) : null}
                        </div>
                      ) : (
                        <div
                          className="chat-pending-stream"
                          style={{ fontSize: 14, lineHeight: 1.55 }}
                        >
                          <RichAssistantContent
                            text={pendingAssistant.text || "\u00a0"}
                            sentences={sentences}
                            enableMarkdown
                            citeVerify={
                              activeItemId
                                ? ({
                                    reports: verifyByItemId[activeItemId] ?? {},
                                    onPersist: handlePersistVerify,
                                  } satisfies CiteVerifyBridge)
                                : null
                            }
                          />
                        </div>
                      )}
                    </div>
                    {pendingAssistant.kind === "pending" ? (
                      <button
                        type="button"
                        className="chat-inline-stop"
                        title="停止生成"
                        aria-label="停止生成"
                        onClick={cancelGeminiStream}
                      >
                        停止
                      </button>
                    ) : (
                      <button
                        type="button"
                        title="关闭"
                        aria-label="关闭错误提示"
                        onClick={dismissPendingAssistant}
                        className="chat-msg-delete"
                      >
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <path d="M3 6h18" />
                          <path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6" />
                          <path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" />
                          <line x1="10" y1="11" x2="10" y2="17" />
                          <line x1="14" y1="11" x2="14" y2="17" />
                        </svg>
                      </button>
                    )}
                  </div>
                )}
              </>
            )}
          </div>

          <div style={{ flexShrink: 0, display: "flex", flexDirection: "column", gap: 6 }}>
            <div className="chat-token-bar" title="按字符量粗略估算输入侧 token，非官方计费；含系统提示中的整稿 JSON">
              <span>
                上下文估算 <strong>{tokenEstimate.totalIn.toLocaleString()}</strong> tokens
              </span>
              <span className="chat-token-bar-muted">
                系统 {tokenEstimate.systemTokens.toLocaleString()} + 对话 {tokenEstimate.convTokens.toLocaleString()}
              </span>
              <span className="chat-token-bar-muted">· 单次输出上限 8192</span>
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <textarea
              value={input}
              disabled={busy}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void send();
                }
              }}
              placeholder="请输入你想知道的信息"
              rows={2}
              style={{
                flex: 1,
                resize: "none",
                padding: "10px 12px",
                borderRadius: 10,
                border: "1px solid var(--border)",
                background: "var(--input-bg)",
                color: "var(--text)",
                lineHeight: 1.5,
              }}
            />
            <button
              type="button"
              disabled={busy || !input.trim()}
              onClick={() => void send()}
              style={{
                padding: "10px 16px",
                borderRadius: 10,
                border: "none",
                background: busy ? "var(--btn-disabled)" : "var(--accent)",
                color: "#fff",
                fontWeight: 600,
              }}
            >
              {busy ? "…" : "发送"}
            </button>
            </div>
          </div>
        </div>

        <ParsedListSidebar
          items={parsedItems}
          activeId={activeItemId}
          onSelect={selectParsedItem}
          onOpenDraft={openDraftModal}
          onRemoveItem={removeParsedItem}
          onClearAll={clearAllParsedItems}
        />
      </div>

      <TranscriptDraftModal
        open={!!draftModalItem}
        item={draftModalItem}
        onClose={() => setDraftModalItem(null)}
      />

      <SettingsModal
        open={settingsOpen}
        showDefer={settingsShowDefer}
        initialMasked={geminiMasked}
        onClose={() => setSettingsOpen(false)}
        onDefer={() => setSettingsShowDefer(false)}
        onSaved={() => {
          void refreshApiSettings().then(() => {
            setSavedHint("API Key 已保存");
            window.setTimeout(() => setSavedHint(null), 2000);
          });
        }}
      />

      <VideoUrlModal
        open={urlModalOpen}
        onClose={() => {
          if (!parseBusy) setUrlModalOpen(false);
        }}
        busy={parseBusy}
        busyLabel={
          parsePhase === "douyin-login"
            ? "等待登录抖音…"
            : parsePhase === "running"
              ? "下载并转写中…"
              : "解析中…"
        }
        error={parseModalError}
        onClearError={clearParseModalError}
        onSubmitUrl={handleSubmitParseUrl}
        onImportJsonFile={handleImportJsonFromModal}
      />
    </div>
  );
}

function MessageBody({
  role,
  segments,
  sentences,
  citeVerify,
}: {
  role: "user" | "assistant";
  segments: MessageSegment[];
  sentences: TranscriptSentence[] | null;
  citeVerify?: CiteVerifyBridge | null;
}) {
  return (
    <div className={role === "assistant" ? "chat-msg-body chat-msg-body--assistant" : "chat-msg-body"}>
      {segments.map((s, i) =>
        s.kind === "text" ? (
          <div key={i} className="chat-msg-segment">
            <RichAssistantContent
              text={s.text}
              sentences={sentences}
              enableMarkdown={role === "assistant"}
              citeVerify={citeVerify}
            />
          </div>
        ) : (
          <span key={i} className="chat-msg-cite-inline">
            <CitationCluster
              label={s.label}
              refs={s.refs}
              sentences={sentences}
              verifyReports={citeVerify?.reports ?? null}
              onVerifyPersist={citeVerify?.onPersist}
            />
          </span>
        )
      )}
    </div>
  );
}
