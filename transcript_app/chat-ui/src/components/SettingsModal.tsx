import { useEffect, useId, useState } from "react";
import { saveGeminiApiKey } from "@/lib/apiSettings";

type Props = {
  open: boolean;
  /** 首次无 Key 自动打开时可显示「稍后再说」 */
  showDefer?: boolean;
  initialMasked?: string;
  onClose: () => void;
  onDefer?: () => void;
  onSaved: () => void;
};

export function SettingsModal({
  open,
  showDefer,
  initialMasked,
  onClose,
  onDefer,
  onSaved,
}: Props) {
  const titleId = useId();
  const [key, setKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setKey("");
    setShowKey(false);
    setError(null);
  }, [open]);

  if (!open) return null;

  const handleSave = async () => {
    setError(null);
    const trimmed = key.trim();
    if (!trimmed) {
      setError("请填写 Gemini API Key");
      return;
    }
    setBusy(true);
    try {
      const r = await saveGeminiApiKey(trimmed);
      if (!r.ok) {
        setError(r.error);
        return;
      }
      onSaved();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="video-url-modal-backdrop"
      role="presentation"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !busy) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="video-url-modal-panel"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <h2 id={titleId} className="video-url-modal-title">
          设置
        </h2>
        <p className="video-url-modal-desc">
          对话与出处查证需要 Gemini API Key。在{" "}
          <a
            href="https://aistudio.google.com/apikey"
            target="_blank"
            rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
          >
            Google AI Studio
          </a>{" "}
          创建后粘贴在下方。密钥仅保存在本机用户目录，不会写入仓库。
        </p>
        <p className="video-url-modal-douyin-hint" style={{ marginTop: 0 }}>
          链接解析 / 转写仍使用项目根目录 .env 中的 DASHSCOPE_API_KEY（若已配置）。
        </p>
        {initialMasked && (
          <p className="video-url-modal-login-hint">当前已配置：{initialMasked}</p>
        )}
        <label className="video-url-modal-label" htmlFor="gemini-api-key-input">
          Gemini API Key
        </label>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input
            id="gemini-api-key-input"
            type={showKey ? "text" : "password"}
            autoComplete="off"
            placeholder="粘贴 API Key"
            value={key}
            disabled={busy}
            onChange={(e) => {
              setKey(e.target.value);
              if (error) setError(null);
            }}
            className="video-url-modal-input"
            style={{ flex: 1, margin: 0 }}
          />
          <button
            type="button"
            className="video-url-modal-btn secondary"
            disabled={busy}
            onClick={() => setShowKey((v) => !v)}
          >
            {showKey ? "隐藏" : "显示"}
          </button>
        </div>
        {error && <div className="video-url-modal-error">{error}</div>}
        <div className="video-url-modal-actions">
          {showDefer && (
            <button
              type="button"
              className="video-url-modal-btn secondary"
              disabled={busy}
              onClick={() => {
                onDefer?.();
                onClose();
              }}
            >
              稍后再说
            </button>
          )}
          <button
            type="button"
            className="video-url-modal-btn secondary"
            disabled={busy}
            onClick={() => onClose()}
          >
            取消
          </button>
          <button
            type="button"
            className="video-url-modal-btn primary"
            disabled={busy}
            onClick={() => void handleSave()}
          >
            {busy ? "保存中…" : "保存"}
          </button>
        </div>
      </div>
    </div>
  );
}
