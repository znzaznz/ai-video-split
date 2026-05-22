/** 在系统默认浏览器打开链接，避免在 Electron 窗口内跳转 */
export async function openExternalLink(href: string): Promise<void> {
  const url = href.trim();
  if (!url) return;
  if (window.bbChat?.openExternal) {
    const r = await window.bbChat.openExternal(url);
    if (!r.ok && r.error) console.warn("[openExternal]", r.error);
    return;
  }
  window.open(url, "_blank", "noopener,noreferrer");
}
