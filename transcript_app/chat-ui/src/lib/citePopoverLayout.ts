const GAP = 8;
const MARGIN = 12;
const MAX_POPOVER_W = 520;

/** 弹层最大高度；内容少时随正文收缩，超出则在内部滚动 */
export const POPOVER_PANEL_MAX_H = 320;

export type CitePopoverLayout = {
  top: number;
  left: number;
  placement: "top" | "bottom";
};

/** 根据锚点、弹层实测尺寸与视口，自适应上下方与水平位置 */
export function computeCitePopoverLayout(
  anchor: DOMRect,
  popover: { width: number; height: number }
): CitePopoverLayout {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const maxW = Math.min(MAX_POPOVER_W, vw * 0.94);
  const popW = Math.min(popover.width || maxW, maxW);
  const panelMaxH = Math.min(POPOVER_PANEL_MAX_H, vh - MARGIN * 2);
  const popH = Math.min(popover.height || 120, panelMaxH);

  let left = anchor.left;
  if (left + popW > vw - MARGIN) {
    left = Math.max(MARGIN, anchor.right - popW);
  }
  if (left < MARGIN) left = MARGIN;

  const spaceBelow = vh - MARGIN - (anchor.bottom + GAP);
  const spaceAbove = anchor.top - GAP - MARGIN;

  let placement: "top" | "bottom" = "bottom";
  let top: number;

  const fitsBelow = spaceBelow >= popH;
  const fitsAbove = spaceAbove >= popH;

  if (fitsBelow || (!fitsAbove && spaceBelow >= spaceAbove)) {
    placement = "bottom";
    top = anchor.bottom + GAP;
    if (top + popH > vh - MARGIN) {
      top = Math.max(MARGIN, vh - MARGIN - popH);
    }
  } else {
    placement = "top";
    top = anchor.top - GAP - popH;
    if (top < MARGIN) top = MARGIN;
  }

  return { top, left, placement };
}
