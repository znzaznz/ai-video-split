#!/usr/bin/env python3
"""
Video/audio to text with Alibaba DashScope Paraformer (model fixed to paraformer-v2).

Pipeline:
1) Optional: extract audio from local video.
2) Submit ASR task to DashScope (async).
3) Poll task status until success.
4) Download transcription JSON.
5) Export txt/json with sentence-level timestamps.

Notes:
- DashScope Paraformer recorded-file API generally expects URL-accessible audio.
- If you pass local video, this script can extract local audio for your own archival,
  but submission still uses --audio-url.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import threading

DASHSCOPE_BASE = "https://dashscope.aliyuncs.com/api/v1"
MODEL_NAME = "paraformer-v2"
OUTPUT_JSON_NAME = "result.json"
OUTPUT_TXT_NAME = "result.txt"
DEFAULT_PRICE_PER_HOUR = 0.288


def get_subprocess_window_kwargs() -> dict[str, Any]:
    if sys.platform != "win32":
        return {}
    return {"creationflags": subprocess.CREATE_NO_WINDOW}


def request_json(url: str, method: str, headers: dict[str, str], body: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")

    req = urllib.request.Request(url=url, method=method, headers=headers, data=data)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            text = resp.read().decode("utf-8")
            return json.loads(text) if text.strip() else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {url}\n{detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"请求失败: {url}\n{exc}") from exc


def extract_audio(video: Path, out_audio: Path) -> None:
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(out_audio),
    ]
    try:
        subprocess.run(cmd, check=True, **get_subprocess_window_kwargs())
    except FileNotFoundError:
        print("错误：未找到 ffmpeg，请先安装并加入 PATH。", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as exc:
        print("错误：提取音频失败。", file=sys.stderr)
        sys.exit(exc.returncode or 1)


def submit_asr(api_key: str, audio_url: str, oss_resolve: bool = False) -> str:
    url = f"{DASHSCOPE_BASE}/services/audio/asr/transcription"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
    }
    if oss_resolve:
        headers["X-DashScope-OssResourceResolve"] = "enable"
    body = {
        "model": MODEL_NAME,
        "input": {"file_urls": [audio_url]},
        "parameters": {
            "sentence_timestamp_enabled": True,
            "disfluency_removal_enabled": False,
            "language_hints": ["zh", "en"],
        },
    }
    data = request_json(url, "POST", headers, body)
    task_id = (data.get("output") or {}).get("task_id")
    if not task_id:
        raise RuntimeError(f"未拿到 task_id，响应: {json.dumps(data, ensure_ascii=False)}")
    return task_id


def poll_task(
    api_key: str,
    task_id: str,
    interval_sec: int,
    timeout_sec: int,
    cancel_event: threading.Event | None = None,
    pause_event: threading.Event | None = None,
) -> dict[str, Any]:
    url = f"{DASHSCOPE_BASE}/tasks/{task_id}"
    headers = {"Authorization": f"Bearer {api_key}"}

    start = time.time()
    while True:
        if cancel_event and cancel_event.is_set():
            raise RuntimeError("任务已取消（轮询阶段）。")
        while pause_event and pause_event.is_set():
            if cancel_event and cancel_event.is_set():
                raise RuntimeError("任务已取消（暂停等待阶段）。")
            time.sleep(0.2)

        data = request_json(url, "GET", headers)
        task_status = ((data.get("output") or {}).get("task_status") or "").upper()

        if task_status in {"SUCCEEDED", "FAILED", "CANCELED"}:
            return data

        if (time.time() - start) >= timeout_sec:
            raise TimeoutError(f"等待任务超时（>{timeout_sec}s），task_id={task_id}")
        slept = 0.0
        step = 0.2
        while slept < float(interval_sec):
            if cancel_event and cancel_event.is_set():
                raise RuntimeError("任务已取消（轮询阶段）。")
            while pause_event and pause_event.is_set():
                if cancel_event and cancel_event.is_set():
                    raise RuntimeError("任务已取消（暂停等待阶段）。")
                time.sleep(step)
            time.sleep(step)
            slept += step


def fetch_transcription_json(transcription_url: str) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(transcription_url, timeout=60) as resp:
            text = resp.read().decode("utf-8")
            return json.loads(text)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"下载识别结果失败: HTTP {exc.code}\n{detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"下载识别结果失败: {exc}") from exc


def to_hms_ms(ms: int) -> str:
    if ms < 0:
        ms = 0
    h = ms // 3600000
    rem = ms % 3600000
    m = rem // 60000
    rem %= 60000
    s = rem // 1000
    mm = rem % 1000
    return f"{h:02d}:{m:02d}:{s:02d},{mm:03d}"


def normalize_sentences(raw: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    # Common layouts seen in DashScope outputs.
    candidates = []
    if isinstance(raw, dict):
        if isinstance(raw.get("sentences"), list):
            candidates = raw["sentences"]
        elif isinstance(raw.get("transcripts"), list):
            for t in raw["transcripts"]:
                if isinstance(t, dict) and isinstance(t.get("sentences"), list):
                    candidates.extend(t["sentences"])
        elif isinstance(raw.get("results"), list):
            for r in raw["results"]:
                if isinstance(r, dict) and isinstance(r.get("sentences"), list):
                    candidates.extend(r["sentences"])

    for i, s in enumerate(candidates, start=1):
        text = str(s.get("text", "")).strip()
        if not text:
            continue

        begin = s.get("begin_time")
        end = s.get("end_time")
        if begin is None:
            begin = s.get("start_time", 0)
        if end is None:
            end = s.get("stop_time", begin)
        begin_ms = int(float(begin))
        end_ms = int(float(end))
        out.append(
            {
                "index": i,
                "start_ms": begin_ms,
                "end_ms": end_ms,
                "start_hms": to_hms_ms(begin_ms),
                "end_hms": to_hms_ms(end_ms),
                "text": text,
            }
        )
    return out


def estimate_cost_cny(task_result: dict[str, Any], sentences: list[dict[str, Any]], price_per_hour: float = DEFAULT_PRICE_PER_HOUR) -> dict[str, float]:
    """
    Best effort:
    1) Prefer usage duration fields returned by API.
    2) Fallback to last sentence end_ms.
    """
    usage = task_result.get("usage") or (task_result.get("output") or {}).get("usage") or {}
    candidates = [
        usage.get("duration"),
        usage.get("audio_duration"),
        usage.get("duration_seconds"),
        usage.get("audio_duration_seconds"),
        usage.get("duration_ms"),
    ]
    billed_seconds = 0.0
    for c in candidates:
        if c is None:
            continue
        v = float(c)
        # Heuristic: if very large, assume milliseconds.
        billed_seconds = v / 1000.0 if v > 100000 else v
        break

    if billed_seconds <= 0 and sentences:
        billed_seconds = max(0.0, float(sentences[-1]["end_ms"]) / 1000.0)

    cost_cny = (billed_seconds / 3600.0) * price_per_hour
    return {
        "billed_seconds": billed_seconds,
        "price_per_hour_cny": price_per_hour,
        "estimated_cost_cny": cost_cny,
    }


def write_outputs(sentences: list[dict[str, Any]], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_file = out_dir / OUTPUT_JSON_NAME
    txt_file = out_dir / OUTPUT_TXT_NAME
    # Cleanup legacy output files from older versions.
    for legacy in ("segments.json", "transcript.txt", "subtitles.srt"):
        legacy_path = out_dir / legacy
        if legacy_path.exists():
            legacy_path.unlink()

    with json_file.open("w", encoding="utf-8") as f:
        json.dump(sentences, f, ensure_ascii=False, indent=2)

    with txt_file.open("w", encoding="utf-8") as f:
        for s in sentences:
            f.write(f"[{s['start_hms']} - {s['end_hms']}] {s['text']}\n")

    print(f"输出：{json_file}")
    print(f"输出：{txt_file}")


def main() -> None:
    parser = argparse.ArgumentParser(description="使用百炼 paraformer-v2 转写音频，输出带时间戳文本。")
    parser.add_argument("--api-key", required=True, help="阿里百炼 API Key（sk-...）")
    parser.add_argument("--audio-url", required=True, help="可访问的音频 URL（paraformer 录音识别输入）")
    parser.add_argument("--video", type=Path, default=None, help="可选：本地视频路径，仅用于先提取本地音频")
    parser.add_argument("--audio-out", type=Path, default=Path("audio_16k_mono.wav"), help="视频提取音频输出路径")
    parser.add_argument("--out-dir", type=Path, default=Path("asr_output"), help="识别结果输出目录")
    parser.add_argument("--poll-interval", type=int, default=2, help="任务轮询间隔秒数")
    parser.add_argument("--timeout", type=int, default=900, help="任务最大等待秒数")
    args = parser.parse_args()

    if args.video:
        video = args.video.resolve()
        if not video.exists():
            print(f"错误：视频不存在：{video}", file=sys.stderr)
            sys.exit(1)
        audio_out = args.audio_out.resolve()
        extract_audio(video, audio_out)
        print(f"已提取本地音频：{audio_out}")

    try:
        task_id = submit_asr(args.api_key, args.audio_url)
        print(f"已提交任务：{task_id}")
        task_result = poll_task(args.api_key, task_id, args.poll_interval, args.timeout)

        status = ((task_result.get("output") or {}).get("task_status") or "").upper()
        if status != "SUCCEEDED":
            print(json.dumps(task_result, ensure_ascii=False, indent=2), file=sys.stderr)
            raise RuntimeError(f"识别任务未成功，状态={status}")

        results = (task_result.get("output") or {}).get("results") or []
        if not results:
            raise RuntimeError("任务成功但无 results。")
        transcription_url = results[0].get("transcription_url")
        if not transcription_url:
            raise RuntimeError("结果中缺少 transcription_url。")

        raw_transcript = fetch_transcription_json(transcription_url)
        sentences = normalize_sentences(raw_transcript)
        if not sentences:
            raise RuntimeError("解析不到句级时间戳，请检查返回结构。")

        write_outputs(sentences, args.out_dir.resolve())
        cost = estimate_cost_cny(task_result, sentences)
        print(f"总句数：{len(sentences)}")
        print("")
        print(
            "费用："
            f"约 ¥{cost['estimated_cost_cny']:.6f} "
            f"(时长 {cost['billed_seconds']:.2f}s, 单价 ¥{cost['price_per_hour_cny']}/小时)"
        )
        print("")
    except Exception as exc:
        print(f"错误：{exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
