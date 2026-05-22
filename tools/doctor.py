#!/usr/bin/env python3
"""环境 / Cookie / 抖音下载预检（排障用，不跑 ASR 计费）。"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from video_platform import detect_platform, extract_url_from_paste  # noqa: E402


def _load_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        key, val = k.strip(), v.strip().strip('"').strip("'")
        if key and val and not os.environ.get(key):
            os.environ[key] = val


def _status(ok: bool, msg: str) -> dict[str, object]:
    return {"ok": ok, "message": msg}


def _run(cmd: list[str], timeout: int = 120) -> tuple[int, str]:
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=ROOT,
        )
        out = ((p.stdout or "") + "\n" + (p.stderr or "")).strip()
        return p.returncode, out[-4000:]
    except FileNotFoundError:
        return 127, f"未找到命令: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "命令超时"


def _cookies_file_path() -> Path | None:
    raw = (os.environ.get("YT_DLP_COOKIES") or "").strip()
    if raw:
        p = Path(raw)
        if not p.is_absolute():
            p = (ROOT / p).resolve()
        return p if p.is_file() else None
    default = ROOT / "cookies.txt"
    return default if default.is_file() else None


def _count_cookie_entries(path: Path) -> int:
    n = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "\t" in line:
            n += 1
    return n


def check_yt_dlp() -> dict[str, object]:
    code, out = _run(["yt-dlp", "--version"])
    if code != 0:
        return _status(False, out or "yt-dlp 不可用")
    ver = (out.splitlines() or [""])[0]
    return _status(True, f"yt-dlp {ver}")


def check_ffmpeg() -> dict[str, object]:
    code, out = _run(["ffmpeg", "-version"])
    if code != 0:
        return _status(False, "ffmpeg 不可用")
    first = (out.splitlines() or [""])[0]
    return _status(True, first[:80])


def check_dashscope_key() -> dict[str, object]:
    key = (os.environ.get("DASHSCOPE_API_KEY") or "").strip()
    if key.startswith("sk-"):
        return _status(True, "DASHSCOPE_API_KEY 已配置")
    return _status(False, "缺少 DASHSCOPE_API_KEY（.env）")


def check_cookie_config() -> dict[str, object]:
    cf = _cookies_file_path()
    browser = (os.environ.get("YT_DLP_COOKIES_FROM_BROWSER") or "").strip()
    if cf:
        n = _count_cookie_entries(cf)
        if n > 0:
            doms = set()
            for line in cf.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("#") or "\t" not in line:
                    continue
                parts = line.split("\t")
                if parts:
                    doms.add(parts[0].lstrip("."))
            has_dy = any("douyin" in d for d in doms)
            return _status(
                has_dy,
                f"cookies 文件 {cf} 共 {n} 条"
                + ("" if has_dy else "，但未发现 douyin 域名"),
            )
        return _status(False, f"cookies 文件为空: {cf.resolve()}")
    if browser:
        return _status(
            False,
            f"仅配置 YT_DLP_COOKIES_FROM_BROWSER={browser}；Windows 建议改 cookies.txt",
        )
    return _status(False, "未配置 Cookie（抖音需 cookies.txt 或 YT_DLP_COOKIES）")


def check_douyin_simulate(url: str) -> dict[str, object]:
    u = extract_url_from_paste(url)
    if detect_platform(u) != "douyin":
        return _status(False, f"非抖音链接: {u}")

    cmd = ["yt-dlp", "--simulate", "--no-playlist", u]
    cf = _cookies_file_path()
    if cf and _count_cookie_entries(cf) > 0:
        cmd[1:1] = ["--cookies", str(cf)]
    else:
        browser = (os.environ.get("YT_DLP_COOKIES_FROM_BROWSER") or "").strip()
        if browser:
            cmd[1:1] = ["--cookies-from-browser", browser]

    code, out = _run(cmd, timeout=90)
    if code == 0:
        title_m = re.search(r"\[info\].*?:\s*(.+)$", out, re.M)
        title = title_m.group(1).strip() if title_m else "（已可解析）"
        return _status(True, f"抖音 simulate 通过: {title[:60]}")
    if "DPAPI" in out or "decrypt" in out.lower():
        return _status(False, "浏览器 Cookie 解密失败（DPAPI）。请导出 cookies.txt")
    if "Fresh cookies" in out:
        return _status(False, "需要新鲜 Cookie：浏览器打开视频后重新导出")
    return _status(False, out[-500:] if out else f"simulate 失败 exit={code}")


def run_douyin_only(url: str) -> tuple[dict[str, object], int]:
    _load_env()
    checks = {
        "cookies": check_cookie_config(),
        "douyin_simulate": check_douyin_simulate(url),
    }
    fails = [k for k, v in checks.items() if not v.get("ok")]
    return checks, 0 if not fails else 1


def run_all(url: str | None = None) -> int:
    _load_env()
    url = url or "https://www.douyin.com/video/7616288306686397748"
    checks = {
        "yt_dlp": check_yt_dlp(),
        "ffmpeg": check_ffmpeg(),
        "dashscope": check_dashscope_key(),
        "cookies": check_cookie_config(),
        "douyin_simulate": check_douyin_simulate(url),
    }
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    print()
    fails = [k for k, v in checks.items() if not v.get("ok")]
    if not fails:
        print("全部通过。可运行: python transcript_cli.py \"<链接>\"")
        return 0
    print("未通过:", ", ".join(fails))
    print("排障文档:", ROOT / "docs" / "troubleshoot-douyin.md")
    return 1


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(description="video-to-word 转写环境预检")
    p.add_argument("--url", default=None)
    p.add_argument("--douyin-only", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    if args.douyin_only:
        u = args.url or "https://www.douyin.com/video/7616288306686397748"
        checks, code = run_douyin_only(u)
        if args.json:
            print(json.dumps(checks, ensure_ascii=False))
        else:
            print(json.dumps(checks, ensure_ascii=False, indent=2))
        sys.exit(code)
    sys.exit(run_all(args.url))


if __name__ == "__main__":
    main()
