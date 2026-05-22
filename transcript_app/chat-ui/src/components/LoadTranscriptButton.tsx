/** 打开「解析视频 / 导入 JSON」入口，与 ThemeToggle 同尺寸方框 */
export function LoadTranscriptButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      title="解析视频（链接）"
      aria-label="解析视频或导入转写稿"
      onClick={onClick}
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: 40,
        height: 36,
        padding: 0,
        borderRadius: 8,
        border: "1px solid var(--border)",
        background: "var(--panel)",
        color: "var(--text)",
      }}
    >
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
        <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
      </svg>
    </button>
  );
}
