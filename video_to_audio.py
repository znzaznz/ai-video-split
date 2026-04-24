#!/usr/bin/env python3
"""
Extract audio from a local video file using FFmpeg (video -> audio only).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def default_output_path(video: Path, fmt: str) -> Path:
    ext = {"mp3": ".mp3", "m4a": ".m4a", "wav": ".wav"}[fmt]
    return video.with_suffix(ext)


def build_ffmpeg_cmd(
    video: Path,
    output: Path,
    fmt: str,
    copy_audio: bool,
) -> list[str]:
    cmd = ["ffmpeg", "-y", "-i", str(video), "-vn", "-map", "0:a:0"]

    if copy_audio:
        cmd += ["-c:a", "copy"]
    elif fmt == "mp3":
        cmd += ["-c:a", "libmp3lame", "-q:a", "2"]
    elif fmt == "m4a":
        cmd += ["-c:a", "aac", "-b:a", "192k"]
    elif fmt == "wav":
        cmd += ["-c:a", "pcm_s16le"]
    else:
        raise ValueError(f"unknown format: {fmt}")

    cmd.append(str(output))
    return cmd


def main() -> None:
    parser = argparse.ArgumentParser(description="将本地视频提取为音频文件。")
    parser.add_argument("video", type=Path, help="输入视频路径")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="输出音频路径（默认与视频同目录，扩展名为 .mp3/.m4a/.wav）",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=("mp3", "m4a", "wav"),
        default="mp3",
        help="输出格式（默认 mp3）",
    )
    parser.add_argument(
        "-c",
        "--copy",
        action="store_true",
        help="尽量复制音轨不重编码（默认输出 .m4a；失败时去掉该选项并改用重编码）",
    )
    args = parser.parse_args()

    video = args.video.resolve()
    if not video.exists():
        print(f"错误：文件不存在：{video}", file=sys.stderr)
        sys.exit(1)

    if args.output is not None:
        out = args.output.resolve()
    elif args.copy:
        out = video.with_suffix(".m4a")
    else:
        out = default_output_path(video, args.format)

    if args.output is None and out.suffix.lower() not in (".mp3", ".m4a", ".wav"):
        out = out.with_suffix({".mp3": ".mp3", ".m4a": ".m4a", ".wav": ".wav"}[args.format])

    cmd = build_ffmpeg_cmd(video, out, args.format, args.copy)

    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError:
        print("错误：未找到 ffmpeg。请先安装 FFmpeg 并确保 ffmpeg 在 PATH 中。", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as exc:
        print("错误：ffmpeg 执行失败（请查看上方 ffmpeg 输出）。", file=sys.stderr)
        sys.exit(exc.returncode or 1)

    print(f"输入：{video}")
    print(f"输出：{out}")


if __name__ == "__main__":
    main()
