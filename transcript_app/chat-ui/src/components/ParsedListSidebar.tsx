import type { ParsedItem } from "@/types/parsed";

type Props = {
  items: ParsedItem[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onOpenDraft: (id: string) => void;
  onRemoveItem: (id: string) => void;
  onClearAll: () => void;
};

/** ≥768px 显示：已加载的转写稿列表，点击切换当前解析上下文 */
export function ParsedListSidebar({
  items,
  activeId,
  onSelect,
  onOpenDraft,
  onRemoveItem,
  onClearAll,
}: Props) {
  const empty = items.length === 0;

  return (
    <aside className="app-sidebar" aria-label="已解析内容列表">
      <div className={`parsed-list-inner${empty ? " parsed-list-inner--empty" : ""}`}>
        <div className="parsed-list-title-row">
          <span className="parsed-list-title">已解析</span>
          {!empty && (
            <button type="button" className="parsed-list-clear-all" title="清空全部解析记录" onClick={onClearAll}>
              清空全部
            </button>
          )}
        </div>
        {empty ? (
          <div className="parsed-list-empty-state">
            <div className="parsed-list-empty-illu" aria-hidden />
            <p className="parsed-list-empty-line1">暂无解析记录</p>
            <p className="parsed-list-empty-line2">解析视频或导入 result.json 后将显示在这里</p>
          </div>
        ) : (
          <ul className="parsed-list-ul">
            {items.map((it) => {
              const active = it.id === activeId;
              return (
                <li key={it.id} className="parsed-list-li">
                  <div className="parsed-list-row">
                    <button
                      type="button"
                      className={`parsed-list-item${active ? " parsed-list-item--active" : ""}`}
                      onClick={() => onSelect(it.id)}
                      onDoubleClick={(e) => {
                        e.preventDefault();
                        onOpenDraft(it.id);
                      }}
                      title={`${it.path}\n双击查看原稿`}
                    >
                      <span className="parsed-list-item-label">{it.label}</span>
                      <span className="parsed-list-item-meta">{it.sentences.length} 句</span>
                    </button>
                    <button
                      type="button"
                      className="parsed-list-draft"
                      title="查看转写原稿（逐句复制）"
                      aria-label={`查看 ${it.label} 原稿`}
                      onClick={(e) => {
                        e.stopPropagation();
                        onOpenDraft(it.id);
                      }}
                    >
                      原稿
                    </button>
                    <button
                      type="button"
                      className="parsed-list-remove"
                      title="移除此记录"
                      aria-label={`移除 ${it.label}`}
                      onClick={(e) => {
                        e.stopPropagation();
                        onRemoveItem(it.id);
                      }}
                    >
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M3 6h18" />
                        <path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6" />
                        <path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" />
                        <line x1="10" y1="11" x2="10" y2="17" />
                        <line x1="14" y1="11" x2="14" y2="17" />
                      </svg>
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </aside>
  );
}
