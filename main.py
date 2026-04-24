#!/usr/bin/env python3
"""
Main entry for video -> timestamped text.

Two input modes:
1) local: one or more local video files.
2) url: one or more public video URLs.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from video_to_text_paraformer import (
    DEFAULT_PRICE_PER_HOUR,
    MODEL_NAME,
    estimate_cost_cny,
    extract_audio,
    fetch_transcription_json,
    normalize_sentences,
    poll_task,
    request_json,
    submit_asr,
    write_outputs,
)


def get_subprocess_window_kwargs() -> dict[str, Any]:
    if sys.platform != "win32":
        return {}
    return {"creationflags": subprocess.CREATE_NO_WINDOW}


def sanitize_name(name: str) -> str:
    cleaned = re.sub(r"[^\w\-\.]+", "_", name.strip())
    cleaned = cleaned.strip("._")
    return cleaned or "item"


def build_multipart_form(fields: dict[str, str], file_field: str, file_path: Path) -> tuple[bytes, str]:
    boundary = "----DashScopeUploadBoundary7MA4YWxkTrZu0gW"
    lines: list[bytes] = []
    for key, value in fields.items():
        lines.append(f"--{boundary}\r\n".encode("utf-8"))
        lines.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
        lines.append(f"{value}\r\n".encode("utf-8"))

    filename = file_path.name
    lines.append(f"--{boundary}\r\n".encode("utf-8"))
    lines.append(
        f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'.encode(
            "utf-8"
        )
    )
    lines.append(b"Content-Type: application/octet-stream\r\n\r\n")
    lines.append(file_path.read_bytes())
    lines.append(b"\r\n")
    lines.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(lines)
    content_type = f"multipart/form-data; boundary={boundary}"
    return body, content_type


def upload_to_dashscope_tmp(api_key: str, local_audio: Path) -> str:
    policy_url = (
        "https://dashscope.aliyuncs.com/api/v1/uploads"
        f"?action=getPolicy&model={urllib.parse.quote(MODEL_NAME)}"
    )
    policy_headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    policy_resp = request_json(policy_url, "GET", policy_headers)
    data = policy_resp.get("data") or policy_resp.get("output") or {}

    upload_host = data.get("upload_host")
    object_key = data.get("upload_dir")
    if object_key and not object_key.endswith("/"):
        object_key = f"{object_key}/"
    object_key = f"{object_key or ''}{local_audio.name}"

    required = {
        "OSSAccessKeyId": data.get("oss_access_key_id") or data.get("OSSAccessKeyId"),
        "Signature": data.get("signature") or data.get("Signature"),
        "policy": data.get("policy"),
    }
    if not upload_host or not required["OSSAccessKeyId"] or not required["Signature"] or not required["policy"]:
        raise RuntimeError(
            "获取 DashScope 上传凭证失败，返回结构异常："
            f"{json.dumps(policy_resp, ensure_ascii=False)}"
        )

    form_fields = {
        "OSSAccessKeyId": required["OSSAccessKeyId"],
        "Signature": required["Signature"],
        "policy": required["policy"],
        "x-oss-object-acl": "private",
        "x-oss-forbid-overwrite": "true",
        "key": object_key,
        "success_action_status": "200",
    }
    body, content_type = build_multipart_form(form_fields, "file", local_audio)

    req = urllib.request.Request(
        url=upload_host,
        method="POST",
        data=body,
        headers={"Content-Type": content_type},
    )
    try:
        with urllib.request.urlopen(req, timeout=120):
            pass
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"上传音频失败: HTTP {exc.code}\n{detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"上传音频失败: {exc}") from exc

    return f"oss://{object_key}"


def is_bilibili_url(url: str) -> bool:
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return False
    return host.endswith("bilibili.com") or host == "b23.tv"


def extract_bilibili_bvid(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    stem = Path(parsed.path).stem or ""
    m = re.search(r"(BV[\w]+)", stem, flags=re.IGNORECASE)
    return m.group(1) if m else stem


def fetch_ytdlp_title(
    url: str,
    cancel_event: threading.Event | None = None,
    pause_event: threading.Event | None = None,
) -> str | None:
    cmd = [
        "yt-dlp",
        "--no-warnings",
        "--no-playlist",
        "--skip-download",
        "-J",
        url,
    ]
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            **get_subprocess_window_kwargs(),
        )
        while True:
            if cancel_event and cancel_event.is_set():
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except Exception:
                    proc.kill()
                return None
            while pause_event and pause_event.is_set():
                if cancel_event and cancel_event.is_set():
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                    except Exception:
                        proc.kill()
                    return None
                time.sleep(0.2)
            try:
                out, err = proc.communicate(timeout=0.5)
                break
            except subprocess.TimeoutExpired:
                continue
        if proc.returncode != 0:
            return None
        raw_out = out or ""
    except FileNotFoundError:
        return None

    try:
        data = json.loads(raw_out or "{}")
    except json.JSONDecodeError:
        return None

    title = str(data.get("title") or "").strip()
    return title or None


def fetch_bilibili_entries(
    url: str,
    cancel_event: threading.Event | None = None,
    pause_event: threading.Event | None = None,
) -> list[dict[str, str]]:
    """
    Best effort expansion for bilibili collection/playlist URLs.
    Returns a list of {"url": "...", "title": "..."} items.
    """
    cmd = [
        "yt-dlp",
        "--no-warnings",
        "--flat-playlist",
        "-J",
        url,
    ]
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            **get_subprocess_window_kwargs(),
        )
        while True:
            if cancel_event and cancel_event.is_set():
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except Exception:
                    proc.kill()
                return []
            while pause_event and pause_event.is_set():
                if cancel_event and cancel_event.is_set():
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                    except Exception:
                        proc.kill()
                    return []
                time.sleep(0.2)
            try:
                out, err = proc.communicate(timeout=0.5)
                break
            except subprocess.TimeoutExpired:
                continue
        if proc.returncode != 0:
            return []
        raw_out = out or ""
    except FileNotFoundError:
        return []

    try:
        data = json.loads(raw_out or "{}")
    except json.JSONDecodeError:
        return []

    entries = data.get("entries")
    if not isinstance(entries, list):
        title = str(data.get("title") or "").strip()
        return [{"url": url, "title": title}]

    results: list[dict[str, str]] = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        item_url = str(e.get("webpage_url") or e.get("url") or "").strip()
        if not item_url:
            continue
        if not item_url.startswith("http"):
            if re.match(r"^BV[\w]+$", item_url, flags=re.IGNORECASE):
                item_url = f"https://www.bilibili.com/video/{item_url}"
            else:
                continue
        item_title = str(e.get("title") or "").strip()
        results.append({"url": item_url, "title": item_title})

    if not results:
        title = str(data.get("title") or "").strip()
        return [{"url": url, "title": title}]
    return results


def pick_unique_dir(base_dir: Path, preferred: str, fallback: str) -> Path:
    preferred_clean = sanitize_name(preferred) or sanitize_name(fallback)
    candidate = preferred_clean
    suffix = 1
    while (base_dir / candidate).exists():
        candidate = f"{preferred_clean}_{suffix}"
        suffix += 1
    return base_dir / candidate


def load_done_urls(checkpoint_path: Path) -> set[str]:
    if not checkpoint_path.exists():
        return set()
    try:
        data = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        items = data.get("done_urls")
        if isinstance(items, list):
            return {str(x).strip() for x in items if str(x).strip()}
    except Exception:
        pass
    return set()


def save_done_urls(checkpoint_path: Path, done_urls: set[str]) -> None:
    checkpoint_path.write_text(
        json.dumps({"done_urls": sorted(done_urls)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def download_bilibili_audio(
    url: str,
    out_wav: Path,
    cancel_event: threading.Event | None = None,
    pause_event: threading.Event | None = None,
) -> None:
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "yt-dlp",
        "-f",
        "ba/b",
        "-x",
        "--audio-format",
        "wav",
        "--audio-quality",
        "0",
        "--no-playlist",
        "--no-warnings",
        "--newline",
        "-o",
        str(out_wav),
        url,
    ]
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            **get_subprocess_window_kwargs(),
        )
        while True:
            if cancel_event and cancel_event.is_set():
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    proc.kill()
                raise RuntimeError("任务已取消（下载阶段）。")
            while pause_event and pause_event.is_set():
                if cancel_event and cancel_event.is_set():
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except Exception:
                        proc.kill()
                    raise RuntimeError("任务已取消（下载阶段）。")
                time.sleep(0.2)
            try:
                out, err = proc.communicate(timeout=0.5)
                break
            except subprocess.TimeoutExpired:
                continue
        if proc.returncode != 0:
            detail = (out or "") + "\n" + (err or "")
            raise RuntimeError(f"B站音频下载失败：{detail.strip()}") from None
    except FileNotFoundError:
        raise RuntimeError("未找到 yt-dlp，请先安装：python -m pip install yt-dlp") from None

    if not out_wav.exists():
        raise RuntimeError("B站音频下载完成但未找到输出文件。")


def process_single_source(
    api_key: str,
    media_url: str,
    output_dir: Path,
    poll_interval: int,
    timeout: int,
    oss_resolve: bool = False,
    cancel_event: threading.Event | None = None,
    pause_event: threading.Event | None = None,
) -> dict[str, float]:
    task_id = submit_asr(api_key, media_url, oss_resolve=oss_resolve)
    print(f"[{output_dir.name}] 任务已提交: {task_id}")
    task_result = poll_task(
        api_key,
        task_id,
        poll_interval,
        timeout,
        cancel_event=cancel_event,
        pause_event=pause_event,
    )
    status = ((task_result.get("output") or {}).get("task_status") or "").upper()
    if status != "SUCCEEDED":
        raise RuntimeError(f"[{output_dir.name}] 识别失败，状态={status}，详情={json.dumps(task_result, ensure_ascii=False)}")

    results = (task_result.get("output") or {}).get("results") or []
    if not results:
        raise RuntimeError(f"[{output_dir.name}] 任务成功但无 results。")
    transcription_url = results[0].get("transcription_url")
    if not transcription_url:
        raise RuntimeError(f"[{output_dir.name}] 缺少 transcription_url。")

    raw = fetch_transcription_json(transcription_url)
    sentences = normalize_sentences(raw)
    if not sentences:
        raise RuntimeError(f"[{output_dir.name}] 未解析到句级时间戳。")

    write_outputs(sentences, output_dir)
    cost = estimate_cost_cny(task_result, sentences, price_per_hour=DEFAULT_PRICE_PER_HOUR)
    print(f"[{output_dir.name}] 完成，共 {len(sentences)} 句")
    print("")
    print(
        f"[{output_dir.name}] 费用：约 ¥{cost['estimated_cost_cny']:.6f} "
        f"(时长 {cost['billed_seconds']:.2f}s, 单价 ¥{cost['price_per_hour_cny']}/小时)"
    )
    print("")
    return cost


def run_local(
    args: argparse.Namespace,
    cancel_event: threading.Event | None = None,
    pause_event: threading.Event | None = None,
) -> dict[str, float]:
    out_root = args.out_dir.resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    audio_tmp = out_root / "_audio_tmp"
    audio_tmp.mkdir(parents=True, exist_ok=True)

    total_cost = 0.0
    total_seconds = 0.0
    processed_count = 0

    for video_str in args.videos:
        if cancel_event and cancel_event.is_set():
            print("已取消：后续本地视频不再处理。")
            break
        paused = True
        while pause_event and pause_event.is_set():
            if cancel_event and cancel_event.is_set():
                print("已取消：后续本地视频不再处理。")
                paused = False
                break
            time.sleep(0.2)
        if not paused:
            break

        video = Path(video_str).resolve()
        if not video.exists():
            print(f"跳过（不存在）：{video}", file=sys.stderr)
            continue

        name = sanitize_name(video.stem)
        local_audio = audio_tmp / f"{name}.wav"
        extract_audio(video, local_audio)
        print(f"[{name}] 已提取音频: {local_audio}")

        oss_url = upload_to_dashscope_tmp(args.api_key, local_audio)
        print(f"[{name}] 已上传临时存储: {oss_url}")

        item_out = out_root / name
        cost = process_single_source(
            api_key=args.api_key,
            media_url=oss_url,
            output_dir=item_out,
            poll_interval=args.poll_interval,
            timeout=args.timeout,
            oss_resolve=True,
            cancel_event=cancel_event,
            pause_event=pause_event,
        )
        total_cost += cost["estimated_cost_cny"]
        total_seconds += cost["billed_seconds"]
        processed_count += 1

    if processed_count > 1:
        print("")
        print(
            f"[批量汇总] 共 {processed_count} 个视频，"
            f"总时长 {total_seconds:.2f}s，"
            f"总费用约 ¥{total_cost:.6f}"
        )
        print("")
    return {
        "processed_count": float(processed_count),
        "total_seconds": total_seconds,
        "total_cost_cny": total_cost,
    }


def run_url(
    args: argparse.Namespace,
    cancel_event: threading.Event | None = None,
    pause_event: threading.Event | None = None,
) -> dict[str, float]:
    out_root = args.out_dir.resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    url_tmp = out_root / "_url_tmp"
    url_tmp.mkdir(parents=True, exist_ok=True)
    checkpoint_path = out_root / "_url_done_checkpoint.json"
    done_urls = load_done_urls(checkpoint_path)

    total_cost = 0.0
    total_seconds = 0.0
    processed_count = 0

    for idx, media_url in enumerate(args.urls, start=1):
        if cancel_event and cancel_event.is_set():
            print("已取消：后续链接不再处理。")
            break
        paused = True
        while pause_event and pause_event.is_set():
            if cancel_event and cancel_event.is_set():
                print("已取消：后续链接不再处理。")
                paused = False
                break
            time.sleep(0.2)
        if not paused:
            break

        if is_bilibili_url(media_url):
            bilibili_items = fetch_bilibili_entries(
                media_url, cancel_event=cancel_event, pause_event=pause_event
            )
            if not bilibili_items:
                bilibili_items = [{"url": media_url, "title": ""}]
            if len(bilibili_items) > 1:
                print(f"检测到 B 站合集/多分P，共 {len(bilibili_items)} 个条目，将逐个处理。")

            for sub_idx, item in enumerate(bilibili_items, start=1):
                entry_url = item.get("url") or media_url
                if entry_url in done_urls:
                    print(f"[skip] 已完成，跳过：{entry_url}")
                    continue
                parsed = urllib.parse.urlparse(entry_url)
                base_name = Path(parsed.path).stem or f"url_{idx}_{sub_idx}"
                name = sanitize_name(base_name)
                bv = extract_bilibili_bvid(entry_url) or name
                display_name = (item.get("title") or "").strip()
                if not display_name:
                    display_name = fetch_ytdlp_title(
                        entry_url, cancel_event=cancel_event, pause_event=pause_event
                    ) or ""
                display_name = display_name.strip() or bv
                item_out = out_root / sanitize_name(f"{display_name}_{sub_idx:02d}")
                task_key = item_out.name
                local_wav = url_tmp / f"{task_key}.wav"
                try:
                    if local_wav.exists() and local_wav.stat().st_size > 0:
                        print(f"[{task_key}] 复用已缓存音频：{local_wav}")
                    else:
                        print(f"[{task_key}] 检测到 B 站链接，先下载媒体并转音频：{entry_url}")
                        download_bilibili_audio(
                            entry_url, local_wav, cancel_event=cancel_event, pause_event=pause_event
                        )
                        print(f"[{task_key}] 已下载音频：{local_wav}")
                    oss_url = upload_to_dashscope_tmp(args.api_key, local_wav)
                    print(f"[{task_key}] 已上传临时存储: {oss_url}")
                    cost = process_single_source(
                        api_key=args.api_key,
                        media_url=oss_url,
                        output_dir=item_out,
                        poll_interval=args.poll_interval,
                        timeout=args.timeout,
                        oss_resolve=True,
                        cancel_event=cancel_event,
                        pause_event=pause_event,
                    )
                except Exception as exc:
                    print(f"[{task_key}] 媒体下载/转码失败，回退直链识别：{exc}")
                    cost = process_single_source(
                        api_key=args.api_key,
                        media_url=entry_url,
                        output_dir=item_out,
                        poll_interval=args.poll_interval,
                        timeout=args.timeout,
                        oss_resolve=False,
                        cancel_event=cancel_event,
                        pause_event=pause_event,
                    )
                total_cost += cost["estimated_cost_cny"]
                total_seconds += cost["billed_seconds"]
                processed_count += 1
                done_urls.add(entry_url)
                save_done_urls(checkpoint_path, done_urls)
        else:
            if media_url in done_urls:
                print(f"[skip] 已完成，跳过：{media_url}")
                continue
            parsed = urllib.parse.urlparse(media_url)
            base_name = Path(parsed.path).stem or f"url_{idx}"
            name = sanitize_name(base_name)
            item_out = out_root / sanitize_name(f"{name}_{idx:02d}")
            cost = process_single_source(
                api_key=args.api_key,
                media_url=media_url,
                output_dir=item_out,
                poll_interval=args.poll_interval,
                timeout=args.timeout,
                oss_resolve=False,
                cancel_event=cancel_event,
                pause_event=pause_event,
            )
            total_cost += cost["estimated_cost_cny"]
            total_seconds += cost["billed_seconds"]
            processed_count += 1
            done_urls.add(media_url)
            save_done_urls(checkpoint_path, done_urls)

    if processed_count > 1:
        print("")
        print(
            f"[批量汇总] 共 {processed_count} 个视频，"
            f"总时长 {total_seconds:.2f}s，"
            f"总费用约 ¥{total_cost:.6f}"
        )
        print("")
    return {
        "processed_count": float(processed_count),
        "total_seconds": total_seconds,
        "total_cost_cny": total_cost,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="视频转带时间戳文本主入口（local/url 双模式）。")
    parser.add_argument("--api-key", required=True, help="百炼 API Key（sk-...）")
    parser.add_argument("--out-dir", type=Path, default=Path("runs"), help="总输出目录")
    parser.add_argument("--poll-interval", type=int, default=2, help="任务轮询间隔（秒）")
    parser.add_argument("--timeout", type=int, default=900, help="单任务超时（秒）")

    subparsers = parser.add_subparsers(dest="mode", required=True)

    p_local = subparsers.add_parser("local", help="输入本地视频文件（一个或多个）")
    p_local.add_argument("videos", nargs="+", help="本地视频路径列表")

    p_url = subparsers.add_parser("url", help="输入视频链接（一个或多个）")
    p_url.add_argument("urls", nargs="+", help="视频 URL 列表")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
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
