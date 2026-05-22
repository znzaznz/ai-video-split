import { useEffect, useId, useRef, useState } from "react";
import { getPlatform, prepareDouyinLogin } from "@/lib/platform";
import { isDouyinUrlLike, isSupportedVideoUrl } from "@/lib/videoUrl";

export { isBilibiliUrlLike, isDouyinUrlLike, isSupportedVideoUrl } from "@/lib/videoUrl";

type Props = {
  open: boolean;
  onClose: () => void;
  busy: boolean;
  /** 解析中按钮文案：登录抖音阶段 vs 下载转写 / 导入 */
  busyLabel?: string;
  error: string | null;
  onClearError: () => void;
  onSubmitUrl: (url: string) => void | Promise<void>;
  onImportJsonFile: () => void | Promise<void>;
};

export function VideoUrlModal({
  open,
  onClose,
  busy,
  busyLabel,
  error,
  onClearError,
  onSubmitUrl,
  onImportJsonFile,
}: Props) {
  const titleId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [url, setUrl] = useState("");
  const [loginBusy, setLoginBusy] = useState(false);
  const [loginHint, setLoginHint] = useState<string | null>(null);
  const isDouyin = isDouyinUrlLike(url);
  const isElectron = getPlatform() === "electron";

  useEffect(() => {
    if (!open) return;
    setUrl("");
    setLoginHint(null);
    onClearError();
    const t = requestAnimationFrame(() => inputRef.current?.focus());
    return () => cancelAnimationFrame(t);
  }, [open, onClearError]);

  const handleDouyinLogin = async () => {
    setLoginHint(null);
    if (error) onClearError();
    setLoginBusy(true);
    try {
      const r = await prepareDouyinLogin(url.trim() || undefined);
      if (r.ok) {
        setLoginHint(`已同步 ${r.cookieCount} 条抖音 Cookie，可点击「开始解析」。`);
      } else if (!r.canceled) {
        setLoginHint(r.error);
      }
    } finally {
      setLoginBusy(false);
    }
  };

  if (!open) return null;

  return (
    <div
      className="video-url-modal-backdrop"
      role="presentation"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !busy && !loginBusy) onClose();
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
          解析视频
        </h2>
        <p className="video-url-modal-desc">
          请输入 B 站或抖音视频链接（也支持粘贴带链接的分享文案），由本机 Python 流水线下载并转写。若已有转写结果，请用下方「导入
          result.json」（本地新视频请先用切片机或命令行转写后再导入）。
        </p>
        {isDouyin && isElectron && (
          <p className="video-url-modal-douyin-hint">
            抖音需先登录同步 Cookie（仅首次或过期时）。点「开始解析」后窗口会关闭，下载在后台进行，不必保持视频播放。
          </p>
        )}
        {loginHint && <p className="video-url-modal-login-hint">{loginHint}</p>}
        <label className="video-url-modal-label" htmlFor="video-url-input">
          视频地址
        </label>
        <input
          id="video-url-input"
          ref={inputRef}
          type="url"
          inputMode="url"
          autoComplete="off"
          placeholder="B 站 BV 链接或 douyin.com/video/…"
          value={url}
          disabled={busy || loginBusy}
          onChange={(e) => {
            setUrl(e.target.value);
            if (error) onClearError();
            if (loginHint) setLoginHint(null);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !busy && !loginBusy && url.trim()) {
              e.preventDefault();
              void onSubmitUrl(url.trim());
            }
          }}
          className="video-url-modal-input"
        />
        {error && <div className="video-url-modal-error">{error}</div>}
        <div className="video-url-modal-actions">
          <button
            type="button"
            className="video-url-modal-btn secondary"
            disabled={busy || loginBusy}
            onClick={() => onClose()}
          >
            取消
          </button>
          {isDouyin && isElectron && (
            <button
              type="button"
              className="video-url-modal-btn secondary"
              disabled={busy || loginBusy}
              onClick={() => void handleDouyinLogin()}
            >
              {loginBusy ? "登录中…" : "登录抖音"}
            </button>
          )}
          <button
            type="button"
            className="video-url-modal-btn primary"
            disabled={
              busy ||
              loginBusy ||
              (!busy && (!url.trim() || !isSupportedVideoUrl(url)))
            }
            onClick={() => void onSubmitUrl(url.trim())}
          >
            {busy ? busyLabel || "解析中…" : "开始解析"}
          </button>
        </div>
        <div className="video-url-modal-footer">
          <button
            type="button"
            className="video-url-modal-linkish"
            disabled={busy || loginBusy}
            onClick={() => void onImportJsonFile()}
          >
            导入本地已转写稿（result.json）
          </button>
        </div>
      </div>
    </div>
  );
}
