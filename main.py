#!/usr/bin/env python3
"""
Main entry for video -> timestamped text (clip app: copies source video into task dir).

Two input modes:
1) local: one or more local video files.
2) url: one or more public video URLs.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import threading
from pathlib import Path
from typing import Any

import transcript_pipeline as tp


MANIFEST_NAME = tp.MANIFEST_NAME


def copy_local_video_to_task_dir(video: Path, item_out: Path) -> Path:
    """Copy local video into task dir as source.<ext> for self-contained clipping."""
    item_out.mkdir(parents=True, exist_ok=True)
    ext = video.suffix.lower() if video.suffix else ".mp4"
    if ext not in {".mp4", ".mkv", ".webm", ".m4v", ".mov"}:
        ext = ".mp4"
    dest = item_out / f"source{ext}"
    if dest.resolve() != video.resolve():
        shutil.copy2(video, dest)
        print(f"[{item_out.name}] 已复制视频到任务目录: {dest}")
    return dest


def find_merged_source_video(item_out: Path) -> Path | None:
    return tp.find_merged_source_video(item_out)


def run_local(
    args: argparse.Namespace,
    cancel_event: threading.Event | None = None,
    pause_event: threading.Event | None = None,
) -> dict[str, float]:
    return tp.run_local(
        args,
        cancel_event=cancel_event,
        pause_event=pause_event,
        copy_video_to_task=True,
        copy_video_fn=copy_local_video_to_task_dir,
    )


def run_url(
    args: argparse.Namespace,
    cancel_event: threading.Event | None = None,
    pause_event: threading.Event | None = None,
) -> dict[str, float]:
    return tp.run_url(args, cancel_event=cancel_event, pause_event=pause_event)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="视频转带时间戳文本主入口（local/url 双模式）。")
    parser.add_argument("--api-key", required=True, help="百炼 API Key（sk-...）")
    parser.add_argument("--out-dir", type=Path, default=Path("runs"), help="总输出目录")
    parser.add_argument("--poll-interval", type=int, default=2, help="任务轮询间隔（秒）")
    parser.add_argument("--timeout", type=int, default=900, help="单任务超时（秒）")
    parser.add_argument(
        "--keywords",
        default="",
        help="本期关键词（逗号分隔），用于热词与转写纠错词表",
    )
    parser.add_argument(
        "--no-llm-correct",
        action="store_true",
        help="转写后不使用 LLM 纠错（仍会做规则纠错）",
    )

    subparsers = parser.add_subparsers(dest="mode", required=True)

    p_local = subparsers.add_parser("local", help="输入本地视频文件（一个或多个）")
    p_local.add_argument("videos", nargs="+", help="本地视频路径列表")

    p_url = subparsers.add_parser("url", help="输入视频链接（一个或多个）")
    p_url.add_argument("urls", nargs="+", help="视频 URL 列表")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.user_keywords = getattr(args, "keywords", "") or ""
    try:
        if args.mode == "local":
            run_local(args)
        elif args.mode == "url":
            run_url(args)
        else:
            parser.error("未知模式")
    except Exception as exc:
        print(f"错误：{exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
