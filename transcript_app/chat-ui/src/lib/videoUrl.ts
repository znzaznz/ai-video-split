/** 与仓库根 video_platform.py 规则对齐 */

const URL_IN_TEXT_RE = /https?:\/\/[^\s\]\)"'<>]+/gi;

export function extractVideoUrlFromPaste(text: string): string {
  const raw = text.trim();
  if (!raw) return "";
  if (/^https?:\/\//i.test(raw)) {
    return raw.split(/\s/)[0]!.replace(/[.,;)\]}"']+$/, "");
  }
  const m = raw.match(URL_IN_TEXT_RE);
  if (!m?.[0]) return raw;
  return m[0].replace(/[.,;)\]}"']+$/, "");
}

function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "").toLowerCase();
  } catch {
    return "";
  }
}

export function isBilibiliUrlLike(raw: string): boolean {
  const s = extractVideoUrlFromPaste(raw).toLowerCase();
  return s.includes("bilibili.com") || s.includes("b23.tv");
}

export function isDouyinUrlLike(raw: string): boolean {
  const s = extractVideoUrlFromPaste(raw).toLowerCase();
  return s.includes("douyin.com") || s.includes("iesdouyin.com");
}

export function isSupportedVideoUrl(raw: string): boolean {
  return isBilibiliUrlLike(raw) || isDouyinUrlLike(raw);
}

export function extractBilibiliBvId(u: string): string | null {
  const m = u.match(/BV[a-z0-9]{10}/i);
  return m ? m[0]!.toUpperCase() : null;
}

export function extractDouyinVideoId(u: string): string | null {
  const m = u.match(/(?:\/video\/|\/share\/video\/|modal_id=)(\d{15,22})/i);
  return m ? m[1]! : null;
}

export function videoUrlMatchKey(u: string): string | null {
  const trimmed = u.trim();
  if (!trimmed) return null;
  const bv = extractBilibiliBvId(trimmed);
  if (bv) return `bv:${bv}`;
  const dy = extractDouyinVideoId(trimmed);
  if (dy) return `dy:${dy}`;
  try {
    const x = new URL(trimmed);
    const host = x.hostname.replace(/^www\./, "").toLowerCase();
    const pathOnly = x.pathname.replace(/\/+$/, "").toLowerCase();
    return `url:${host}${pathOnly}`;
  } catch {
    return null;
  }
}

export function manifestMatchesUserUrl(manifestSourceUrl: string, userUrl: string): boolean {
  const su = manifestSourceUrl.trim();
  const u = extractVideoUrlFromPaste(userUrl).trim();
  if (!su || !u) return false;
  const km = videoUrlMatchKey(su);
  const ku = videoUrlMatchKey(u);
  if (km && ku && km === ku) return true;
  const bvM = extractBilibiliBvId(su);
  const bvU = extractBilibiliBvId(u);
  if (bvM && bvU && bvM === bvU) return true;
  const dyM = extractDouyinVideoId(su);
  const dyU = extractDouyinVideoId(u);
  return !!(dyM && dyU && dyM === dyU);
}
