import { useCallback, useEffect, useRef, useState } from "react";

const POPOVER_SELECTOR = ".chat-cite-popover--floating";
const BACKDROP_SELECTOR = ".chat-cite-popover-backdrop";

/** 点击药丸开关出处弹层；点外部或 Esc 关闭 */
export function useCitePopoverClick() {
  const [open, setOpen] = useState(false);
  const anchorRef = useRef<HTMLButtonElement>(null);

  const toggle = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    setOpen((v) => !v);
  }, []);

  const close = useCallback(() => setOpen(false), []);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    const onDoc = (e: MouseEvent) => {
      const t = e.target as Node;
      if (anchorRef.current?.contains(t)) return;
      if (document.querySelector(POPOVER_SELECTOR)?.contains(t)) return;
      if (document.querySelector(BACKDROP_SELECTOR)?.contains(t)) return;
      close();
    };
    document.addEventListener("keydown", onKey);
    const id = window.setTimeout(() => document.addEventListener("click", onDoc, true), 0);
    return () => {
      clearTimeout(id);
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("click", onDoc, true);
    };
  }, [open, close]);

  return { open, anchorRef, toggle, close };
}
