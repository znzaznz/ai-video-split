#!/usr/bin/env python3
"""B 站 / 抖音链接识别、从分享文案抽 URL、manifest 匹配键。"""

from __future__ import annotations

import re
import urllib.parse
from pathlib import Path

Platform = str  # "bilibili" | "douyin"

_SUPPORTED_URL_RE = re.compile(
    r"https?://[^\s\]\)\"'<>]+",
    flags=re.IGNORECASE,
)

_DOUYIN_VIDEO_ID_RE = re.compile(
    r"(?:/video/|/share/video/|modal_id=)(\d{15,22})",
    flags=re.IGNORECASE,
)

_BV_RE = re.compile(r"(BV[\w]{10})", flags=re.IGNORECASE)


def extract_url_from_paste(text: str) -> str:
    """从整段分享文案中取出第一个支持的平台 URL；若已是 URL 则原样 trim。"""
    raw = (text or "").strip()
    if not raw:
        return ""
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw.split()[0].rstrip(".,;)]}\"'")
    m = _SUPPORTED_URL_RE.search(raw)
    if not m:
        return raw
    url = m.group(0).rstrip(".,;)]}\"'")
    return url


def _host(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return ""


def is_bilibili_url(url: str) -> bool:
    host = _host(url)
    return host.endswith("bilibili.com") or host == "b23.tv"


def is_douyin_url(url: str) -> bool:
    host = _host(url)
    return "douyin.com" in host or host.endswith("iesdouyin.com")


def detect_platform(url: str) -> Platform | None:
    u = (url or "").strip()
    if not u:
        return None
    if is_bilibili_url(u):
        return "bilibili"
    if is_douyin_url(u):
        return "douyin"
    return None


def extract_bilibili_bvid(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    stem = Path(parsed.path).stem or ""
    m = _BV_RE.search(stem) or _BV_RE.search(url)
    return m.group(1).upper() if m else stem


def extract_douyin_video_id(url: str) -> str | None:
    m = _DOUYIN_VIDEO_ID_RE.search(url)
    return m.group(1) if m else None


def extract_match_key(url: str) -> str | None:
    """与 Electron manifest 对齐：bv:… / dy:… / url:host/path。"""
    u = (url or "").strip()
    if not u:
        return None
    bv = extract_bilibili_bvid(u)
    if bv and _BV_RE.match(bv):
        return f"bv:{bv.upper()}"
    dy = extract_douyin_video_id(u)
    if dy:
        return f"dy:{dy}"
    try:
        x = urllib.parse.urlparse(u)
        host = x.hostname.replace("www.", "").lower() if x.hostname else ""
        path_only = x.path.rstrip("/").lower()
        return f"url:{host}{path_only}"
    except Exception:
        return None


def normalize_entry_url(url: str) -> str:
    return (url or "").strip()


def platform_label(platform: Platform | None) -> str:
    if platform == "bilibili":
        return "B 站"
    if platform == "douyin":
        return "抖音"
    return "未知"
