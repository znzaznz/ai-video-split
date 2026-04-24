#!/usr/bin/env python3
"""
List frame-level cut points for a video.

Outputs:
1) all_frames.csv     - every frame (re-encode cut points)
2) keyframes.csv      - keyframes only (stream copy/no-reencode preferred points)
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path


def run_ffprobe(video_path: Path) -> dict:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "frame=pts_time,best_effort_timestamp_time,pkt_dts_time,key_frame,pict_type,coded_picture_number",
        "-of",
        "json",
        str(video_path),
    ]
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError:
        print("错误：未找到 ffprobe。请先安装 FFmpeg 并确保 ffprobe 在 PATH 中。", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as exc:
        print("错误：ffprobe 执行失败。", file=sys.stderr)
        print(exc.stderr, file=sys.stderr)
        sys.exit(1)

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        print("错误：ffprobe 返回了无效 JSON。", file=sys.stderr)
        sys.exit(1)


def frame_time(frame: dict) -> float:
    for key in ("pts_time", "best_effort_timestamp_time", "pkt_dts_time"):
        value = frame.get(key)
        if value is not None:
            return float(value)
    return -1.0


def write_csv(rows: list[dict], output_file: Path) -> None:
    fieldnames = ["frame_index", "time_sec", "time_hms", "is_keyframe", "pict_type"]
    with output_file.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def sec_to_hms(sec: float) -> str:
    if sec < 0:
        return ""
    hours = int(sec // 3600)
    minutes = int((sec % 3600) // 60)
    seconds = sec % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:06.3f}"


def build_rows(frames: list[dict]) -> tuple[list[dict], list[dict]]:
    all_rows: list[dict] = []
    key_rows: list[dict] = []

    for idx, frame in enumerate(frames):
        t = frame_time(frame)
        row = {
            "frame_index": idx,
            "time_sec": f"{t:.6f}" if t >= 0 else "",
            "time_hms": sec_to_hms(t),
            "is_keyframe": int(frame.get("key_frame", 0)),
            "pict_type": frame.get("pict_type", ""),
        }
        all_rows.append(row)
        if row["is_keyframe"] == 1:
            key_rows.append(row)

    return all_rows, key_rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description="列出视频所有可切帧（含关键帧）。"
    )
    parser.add_argument("video", type=Path, help="输入视频路径")
    parser.add_argument(
        "-o",
        "--out-dir",
        type=Path,
        default=Path("."),
        help="输出目录（默认当前目录）",
    )
    args = parser.parse_args()

    video_path = args.video.resolve()
    out_dir = args.out_dir.resolve()

    if not video_path.exists():
        print(f"错误：视频文件不存在：{video_path}", file=sys.stderr)
        sys.exit(1)

    out_dir.mkdir(parents=True, exist_ok=True)

    data = run_ffprobe(video_path)
    frames = data.get("frames", [])
    if not frames:
        print("错误：没有读取到视频帧，请确认文件包含视频流。", file=sys.stderr)
        sys.exit(1)

    all_rows, key_rows = build_rows(frames)
    all_csv = out_dir / "all_frames.csv"
    key_csv = out_dir / "keyframes.csv"
    write_csv(all_rows, all_csv)
    write_csv(key_rows, key_csv)

    print(f"视频：{video_path}")
    print(f"总帧数：{len(all_rows)}")
    print(f"关键帧数：{len(key_rows)}")
    print(f"全部帧切点：{all_csv}")
    print(f"关键帧切点：{key_csv}")
    print("\n说明：")
    print("- all_frames.csv: 每一帧都可作为切点（通常需要重新编码）。")
    print("- keyframes.csv: 关键帧切点（更适合无损直切/流拷贝）。")


if __name__ == "__main__":
    main()
