import { useCallback, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { computeCitePopoverLayout, type CitePopoverLayout } from "@/lib/citePopoverLayout";

type FloatingProps = {
  open: boolean;
  anchorRef: React.RefObject<HTMLElement | null>;
  onClose?: () => void;
  className?: string;
  children: React.ReactNode;
};

/** 出处弹层：蒙层 + fixed portal，点击蒙层关闭，滚轮不带动背后内容 */
export function CitePopoverFloating({
  open,
  anchorRef,
  onClose,
  className = "chat-cite-popover",
  children,
}: FloatingProps) {
  const popoverRef = useRef<HTMLDivElement>(null);
  const [layout, setLayout] = useState<CitePopoverLayout | null>(null);

  const measure = useCallback(() => {
    const anchor = anchorRef.current;
    const pop = popoverRef.current;
    if (!anchor || !pop) return;
    const rect = pop.getBoundingClientRect();
    setLayout(
      computeCitePopoverLayout(anchor.getBoundingClientRect(), {
        width: rect.width,
        height: rect.height,
      })
    );
  }, [anchorRef]);

  useLayoutEffect(() => {
    if (!open) {
      setLayout(null);
      return;
    }
    measure();
    const id = requestAnimationFrame(measure);
    return () => cancelAnimationFrame(id);
  }, [open, measure, children]);

  useLayoutEffect(() => {
    if (!open) return;
    const onChange = () => measure();
    window.addEventListener("resize", onChange);
    window.addEventListener("scroll", onChange, true);
    return () => {
      window.removeEventListener("resize", onChange);
      window.removeEventListener("scroll", onChange, true);
    };
  }, [open, measure]);

  useLayoutEffect(() => {
    if (!open) return;
    const blockBgWheel = (e: WheelEvent) => {
      const pop = popoverRef.current;
      if (pop?.contains(e.target as Node)) return;
      e.preventDefault();
    };
    document.addEventListener("wheel", blockBgWheel, { passive: false, capture: true });
    return () => document.removeEventListener("wheel", blockBgWheel, { capture: true });
  }, [open]);

  if (!open) return null;

  return createPortal(
    <>
      <div
        className="chat-cite-popover-backdrop"
        aria-hidden
        onClick={(e) => {
          e.stopPropagation();
          onClose?.();
        }}
        onWheel={(e) => e.preventDefault()}
      />
      <div
        ref={popoverRef}
        role="dialog"
        aria-modal="true"
        className={`${className} chat-cite-popover--floating${layout?.placement === "top" ? " chat-cite-popover--above" : ""}`}
        style={{
          position: "fixed",
          top: layout?.top ?? -9999,
          left: layout?.left ?? 0,
          visibility: layout ? "visible" : "hidden",
          zIndex: 10000,
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </>,
    document.body
  );
}
