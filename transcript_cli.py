#!/usr/bin/env python3
"""CLI：B 站 / 抖音 / 本地视频 → 转写（供 transcript_app 与 chat-ui 调用）。"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import transcript_pipeline as tp
import transcript_polish as tpol
from video_platform import extract_url_from_paste


def load_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="视频转写纠错 CLI（B 站 / 抖音 / 本地，输出 runs/）",
    )
    parser.add_argument(
        "urls",
        nargs="*",
        help="视频链接或分享文案；与 --local 二选一",
    )
    parser.add_argument("--local", type=Path, default=None, help="本地视频文件")
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="仅运行 tools/doctor.py 预检",
    )
    parser.add_argument("--api-key", default="", help="百炼 sk- API Key")
    parser.add_argument("--out-dir", type=Path, default=Path("runs"))
    parser.add_argument("--poll-interval", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument(
        "--keywords",
        default="",
        help="本期关键词（热词与纠错词表）",
    )
    parser.add_argument(
        "--no-llm-correct",
        action="store_true",
        help="纠错模式下不使用 LLM（等同 --post-asr-mode none 若未指定模式）",
    )
    parser.add_argument(
        "--post-asr-mode",
        choices=("correct", "polish", "none"),
        default=None,
        help="转写后处理：纠错（默认）/ 轻量润色 / 仅转写",
    )
    parser.add_argument(
        "--polish-model",
        default=tpol.DEFAULT_POLISH_MODEL,
        help="润色模型（post-asr-mode=polish 时）",
    )
    return parser


def _ensure_utf8_stdio() -> None:
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_stdio()
    root = Path(__file__).resolve().parent
    env = load_env_file(root / ".env")
    env.update(load_env_file(Path.cwd() / ".env"))
    for key in ("DASHSCOPE_API_KEY", "YT_DLP_COOKIES", "YT_DLP_COOKIES_FROM_BROWSER"):
        val = (env.get(key) or "").strip()
        if val and not os.environ.get(key):
            os.environ[key] = val

    parser = build_parser()
    args = parser.parse_args(argv)

    api_key = (args.api_key or os.environ.get("DASHSCOPE_API_KEY", "") or env.get("DASHSCOPE_API_KEY", "")).strip()
    if args.doctor:
        from tools.doctor import run_all

        test_url = extract_url_from_paste(args.urls[0]) if args.urls else None
        return run_all(test_url)

    if not api_key.startswith("sk-"):
        print("错误：需要有效的 DASHSCOPE_API_KEY（sk- 开头）。", file=sys.stderr)
        return 2

    ns = tp.argparse_namespace(
        api_key=api_key,
        out_dir=args.out_dir.resolve(),
        poll_interval=args.poll_interval,
        timeout=args.timeout,
        user_keywords=args.keywords,
        keywords=args.keywords,
        no_llm_correct=args.no_llm_correct,
        post_asr_mode=args.post_asr_mode,
        polish_model=args.polish_model,
        mode="local" if args.local else "url",
        videos=[str(args.local.resolve())] if args.local else None,
        urls=[extract_url_from_paste(u) for u in args.urls] if args.urls else None,
    )

    try:
        if args.local:
            if args.urls:
                print("警告：--local 模式下忽略位置参数链接。", file=sys.stderr)
            tp.run_local(ns, copy_video_to_task=False)
        else:
            if not args.urls:
                print("错误：请提供链接或使用 --local。", file=sys.stderr)
                return 2
            tp.run_url(ns)
    except Exception as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
