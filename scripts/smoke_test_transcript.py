#!/usr/bin/env python3
"""Smoke test: share URL, polish 2 sentences (uses .env key)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from video_platform import detect_platform, extract_url_from_paste  # noqa: E402


def load_key() -> str:
    for p in (ROOT / ".env", Path.cwd() / ".env"):
        if not p.is_file():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("DASHSCOPE_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("DASHSCOPE_API_KEY", "")


def main() -> int:
    paste = (
        "3.02 复制打开抖音 https://www.iesdouyin.com/share/video/7616288306686397748/ 05/26"
    )
    u = extract_url_from_paste(paste)
    print("extract_url:", u)
    print("platform:", detect_platform(u))
    assert detect_platform(u) == "douyin"

    key = load_key()
    print("dashscope_key:", "ok" if key.startswith("sk-") else "MISSING")
    if not key.startswith("sk-"):
        return 0

    import transcript_polish as tpol

    rj = ROOT / "runs" / "BV1nfdoBvEsh" / "result.json"
    if not rj.is_file():
        print("skip polish: no", rj)
        return 0
    sentences = json.loads(rj.read_text(encoding="utf-8"))[:2]
    out = tpol.polish_sentences(key, sentences, chunk_size=2)
    print("polish_sentences:", len(out), "text0:", out[0]["text"][:50])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
