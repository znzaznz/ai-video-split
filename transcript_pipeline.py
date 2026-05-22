#!/usr/bin/env python3
"""
Shared pipeline: video/URL -> ASR -> transcript correction.

Used by main.py (clip app) and transcript_app (standalone exe).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

import transcript_correct as tc
import transcript_polish as tpol
from video_platform import (
    Platform,
    detect_platform,
    extract_bilibili_bvid,
    extract_douyin_video_id,
    extract_url_from_paste,
    is_bilibili_url,
    normalize_entry_url,
    platform_label,
)
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


MANIFEST_NAME = "task_manifest.json"
TRANSCRIPT_USAGE_STATS_NAME = "transcript_usage_stats.json"
CHECKPOINT_NAME = "_done_checkpoint.json"
LEGACY_URL_CHECKPOINT = "_url_done_checkpoint.json"
LEGACY_BILIBILI_CHECKPOINT = "_bilibili_done_checkpoint.json"


def merge_job_cost(asr: dict[str, float], llm_cost: float) -> dict[str, float]:
    asr_cny = float(asr.get("estimated_cost_cny", 0.0))
    llm_cny = float(llm_cost)
    return {
        "asr_cost_cny": asr_cny,
        "llm_correct_cost_cny": llm_cny,
        "estimated_cost_cny": asr_cny + llm_cny,
        "billed_seconds": float(asr.get("billed_seconds", 0.0)),
        "price_per_hour_cny": float(asr.get("price_per_hour_cny", DEFAULT_PRICE_PER_HOUR)),
    }


def print_job_cost(task_name: str, cost: dict[str, float], sentence_count: int) -> None:
    print(f"[{task_name}] 完成，共 {sentence_count} 句")
    print(
        f"[{task_name}] 费用：转写约 {cost['asr_cost_cny']:.6f} 元 "
        f"(时长 {cost['billed_seconds']:.2f}s, 单价 {cost['price_per_hour_cny']} 元/小时)"
    )
    if cost.get("llm_correct_cost_cny", 0) > 0:
        label = cost.get("post_asr_label", "纠错")
        print(f"[{task_name}] 费用：{label} LLM 约 {cost['llm_correct_cost_cny']:.6f} 元")
    print(f"[{task_name}] 费用：合计约 {cost['estimated_cost_cny']:.6f} 元")
    print("")


def new_run_cost_totals() -> dict[str, float]:
    return {
        "processed_count": 0.0,
        "total_seconds": 0.0,
        "total_cost_cny": 0.0,
        "asr_cost_cny": 0.0,
        "llm_correct_cost_cny": 0.0,
    }


def add_job_cost_to_totals(totals: dict[str, float], job: dict[str, float]) -> None:
    totals["total_cost_cny"] += float(job.get("estimated_cost_cny", 0.0))
    totals["asr_cost_cny"] += float(job.get("asr_cost_cny", 0.0))
    totals["llm_correct_cost_cny"] += float(job.get("llm_correct_cost_cny", 0.0))
    totals["total_seconds"] += float(job.get("billed_seconds", 0.0))


def print_batch_cost_summary(totals: dict[str, float], processed_count: int, skipped_count: int = 0) -> None:
    if processed_count <= 0 and skipped_count <= 0:
        return
    print("")
    if processed_count > 0:
        print(
            f"[批量汇总] 新处理 {processed_count} 个，"
            f"总时长 {totals['total_seconds']:.2f}s，"
            f"合计约 {totals['total_cost_cny']:.6f} 元 "
            f"(转写 {totals['asr_cost_cny']:.6f} + 纠错 {totals['llm_correct_cost_cny']:.6f} 元)"
        )
    if skipped_count > 0:
        print(f"[批量汇总] 跳过 {skipped_count} 个。")
    print("")


def get_runtime_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def load_env_values(env_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not env_path.exists():
        return values
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        values[key.strip()] = val.strip().strip('"').strip("'")
    return values


def save_env_key(api_key: str) -> None:
    env_path = get_runtime_base_dir() / ".env"
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    updated = False
    for i, raw in enumerate(lines):
        if raw.strip().startswith("DASHSCOPE_API_KEY="):
            lines[i] = f"DASHSCOPE_API_KEY={api_key}"
            updated = True
            break
    if not updated:
        lines.insert(0, f"DASHSCOPE_API_KEY={api_key}")
    env_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def apply_dotenv_to_environ() -> None:
    for key, val in find_env_values().items():
        os.environ.setdefault(key, val)


def find_env_values() -> dict[str, str]:
    root = get_runtime_base_dir()
    candidates = [
        Path.cwd() / ".env",
        root / ".env",
        Path(sys.executable).resolve().parent / ".env",
        Path(sys.executable).resolve().parent.parent / ".env",
    ]
    seen: set[str] = set()
    for p in candidates:
        key = str(p.resolve()) if p.exists() else str(p)
        if key in seen:
            continue
        seen.add(key)
        values = load_env_values(p)
        if values:
            return values
    return {}


def resolve_transcript_stats_path() -> Path:
    return get_runtime_base_dir() / TRANSCRIPT_USAGE_STATS_NAME


def load_transcript_usage_stats(stats_path: Path) -> dict[str, float]:
    default = {
        "total_cost_cny": 0.0,
        "total_seconds": 0.0,
        "total_jobs": 0.0,
        "asr_cost_cny": 0.0,
        "llm_correct_cost_cny": 0.0,
    }
    if not stats_path.exists():
        return dict(default)
    try:
        data = json.loads(stats_path.read_text(encoding="utf-8"))
        asr = float(data.get("asr_cost_cny", data.get("total_cost_cny", 0.0)))
        llm = float(data.get("llm_correct_cost_cny", 0.0))
        total = float(data.get("total_cost_cny", asr + llm))
        return {
            "total_cost_cny": total,
            "total_seconds": float(data.get("total_seconds", 0.0)),
            "total_jobs": float(data.get("total_jobs", 0.0)),
            "asr_cost_cny": asr,
            "llm_correct_cost_cny": llm,
        }
    except Exception:
        return dict(default)


def save_transcript_usage_stats(stats_path: Path, stats: dict[str, float]) -> None:
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")


def format_transcript_cost_summary(stats: dict[str, float]) -> str:
    hours = float(stats.get("total_seconds", 0.0)) / 3600.0
    asr = float(stats.get("asr_cost_cny", 0.0))
    llm = float(stats.get("llm_correct_cost_cny", 0.0))
    total = float(stats.get("total_cost_cny", asr + llm))
    return (
        f"累计费用：{total:.6f} 元（转写{asr:.6f} + 纠错{llm:.6f} 元）    "
        f"(累计时长 {hours:.3f}h, 任务 {int(stats.get('total_jobs', 0))})"
    )


def argparse_namespace(**kwargs):
    class NS:
        pass

    ns = NS()
    for k, v in kwargs.items():
        setattr(ns, k, v)
    return ns


class QueueWriter:
    def __init__(self, logger_func) -> None:
        self.logger_func = logger_func
        self._buf = ""

    def write(self, s: str) -> int:
        if not s:
            return 0
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                self.logger_func(line)
        return len(s)

    def flush(self) -> None:
        if self._buf.strip():
            self.logger_func(self._buf.strip())
        self._buf = ""


def normalize_post_asr_mode(args: argparse.Namespace) -> str:
    mode = str(
        getattr(args, "post_asr_mode", None)
        or os.environ.get("TRANSCRIPT_POST_ASR_MODE", "correct")
        or "correct"
    ).strip().lower()
    if mode not in ("correct", "polish", "none"):
        mode = "correct"
    if bool(getattr(args, "no_llm_correct", False)) and mode == "correct":
        return "none"
    return mode


def correction_kwargs_from_args(args: argparse.Namespace) -> dict[str, Any]:
    kw = getattr(args, "user_keywords", None) or getattr(args, "keywords", "") or ""
    mode = normalize_post_asr_mode(args)
    enable_llm = mode == "correct" and not bool(getattr(args, "no_llm_correct", False))
    return {
        "user_keywords": str(kw),
        "enable_llm_correct": enable_llm,
        "post_asr_mode": mode,
        "polish_model": str(getattr(args, "polish_model", tpol.DEFAULT_POLISH_MODEL) or tpol.DEFAULT_POLISH_MODEL),
    }


def manifest_transcript_fields(item_out: Path) -> dict[str, str]:
    return {"result_json": str((item_out / "result.json").resolve())}


def write_task_manifest(output_dir: Path, payload: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / MANIFEST_NAME
    data = dict(payload)
    data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


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


def _cookies_file_has_entries(path: Path) -> bool:
    if not path.is_file():
        return False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "\t" in line:
            return True
    return False


def yt_dlp_cookie_args() -> list[str]:
    apply_dotenv_to_environ()
    root = get_runtime_base_dir()
    cookies_file = (os.environ.get("YT_DLP_COOKIES") or "").strip()
    if cookies_file:
        p = Path(cookies_file)
        if not p.is_absolute():
            p = (root / p).resolve()
        if p.is_file() and _cookies_file_has_entries(p):
            return ["--cookies", str(p)]
    default = root / "cookies.txt"
    if _cookies_file_has_entries(default):
        return ["--cookies", str(default.resolve())]
    browser = (os.environ.get("YT_DLP_COOKIES_FROM_BROWSER") or "").strip()
    if browser:
        return ["--cookies-from-browser", browser]
    return []


def _format_download_error(exc: BaseException, platform: Platform) -> str:
    text = str(exc)
    if platform != "douyin":
        return text
    extra = []
    if "DPAPI" in text or "decrypt" in text.lower():
        extra.append(
            "Windows 无法从浏览器读取 Cookie：请导出 Netscape cookies.txt 到仓库根目录，"
            "并在 .env 设置 YT_DLP_COOKIES=cookies.txt。"
        )
    elif "Fresh cookies" in text:
        extra.append("请在浏览器打开该抖音视频并过验证后，重新导出 cookies.txt。")
    else:
        extra.append("运行 python tools/doctor.py 做预检；详见 docs/troubleshoot-douyin.md。")
    extra.append("Electron「转写查证」可点击「登录抖音」同步 Cookie 后重试。")
    return f"{text}\n" + " ".join(extra)


def resolve_checkpoint_path(out_root: Path) -> Path:
    new_path = out_root / CHECKPOINT_NAME
    for legacy in (LEGACY_URL_CHECKPOINT, LEGACY_BILIBILI_CHECKPOINT):
        leg = out_root / legacy
        if new_path.exists():
            break
        if leg.exists():
            done = load_done_urls(leg)
            if done:
                save_done_urls(new_path, done)
            break
    return new_path


def load_done_urls_merged(out_root: Path) -> tuple[Path, set[str]]:
    path = resolve_checkpoint_path(out_root)
    done = load_done_urls(path)
    for legacy in (LEGACY_URL_CHECKPOINT, LEGACY_BILIBILI_CHECKPOINT):
        leg = out_root / legacy
        if leg.exists() and leg != path:
            done |= load_done_urls(leg)
    return path, done


def fetch_douyin_entry(
    url: str,
    cancel_event: threading.Event | None = None,
    pause_event: threading.Event | None = None,
) -> list[dict[str, str]]:
    title = fetch_ytdlp_title(url, cancel_event=cancel_event, pause_event=pause_event) or ""
    return [{"url": normalize_entry_url(url), "title": title}]


def fetch_ytdlp_title(
    url: str,
    cancel_event: threading.Event | None = None,
    pause_event: threading.Event | None = None,
) -> str | None:
    cmd = [
        "yt-dlp",
        *yt_dlp_cookie_args(),
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
    cmd = [
        "yt-dlp",
        *yt_dlp_cookie_args(),
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


def local_video_fingerprint(video: Path) -> str:
    p = video.resolve()
    st = p.stat()
    return f"{p}|{st.st_size}|{int(st.st_mtime)}"


def load_done_local_keys(checkpoint_path: Path) -> set[str]:
    if not checkpoint_path.exists():
        return set()
    try:
        data = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        items = data.get("done_local_keys")
        if isinstance(items, list):
            return {str(x).strip() for x in items if str(x).strip()}
    except Exception:
        pass
    return set()


def save_done_local_keys(checkpoint_path: Path, keys: set[str]) -> None:
    checkpoint_path.write_text(
        json.dumps({"done_local_keys": sorted(keys)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def is_valid_result_json(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size <= 2:
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return isinstance(data, list) and len(data) > 0
    except Exception:
        return False


def find_completed_task_for_local_video(out_root: Path, video: Path) -> Path | None:
    fp = local_video_fingerprint(video)
    resolved = str(video.resolve())

    for manifest in out_root.rglob(MANIFEST_NAME):
        if "_audio_tmp" in manifest.parts or "_url_tmp" in manifest.parts:
            continue
        task_dir = manifest.parent
        result_json = task_dir / "result.json"
        if not is_valid_result_json(result_json):
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except Exception:
            continue
        if str(data.get("mode") or "") == "url":
            continue
        if str(data.get("source_fingerprint") or "") == fp:
            return task_dir
        for key in ("local_video", "source_video", "source_path"):
            prev = str(data.get(key) or "").strip()
            if not prev:
                continue
            try:
                if Path(prev).resolve() == video.resolve():
                    return task_dir
            except Exception:
                if prev == resolved:
                    return task_dir
    return None


def find_merged_source_video(item_out: Path) -> Path | None:
    for ext in (".mp4", ".mkv", ".webm", ".m4v"):
        p = item_out / f"source{ext}"
        if p.is_file() and p.stat().st_size > 0:
            return p
    for p in sorted(item_out.glob("source.*")):
        if p.is_file() and p.suffix.lower() in {".mp4", ".mkv", ".webm", ".m4v"}:
            return p
    return None


def extract_wav_for_asr(video: Path, out_wav: Path) -> None:
    out_wav.parent.mkdir(parents=True, exist_ok=True)
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
        str(out_wav),
    ]
    try:
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            **get_subprocess_window_kwargs(),
        )
    except FileNotFoundError as exc:
        raise RuntimeError("未找到 ffmpeg，请安装并加入 PATH。") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "") + "\n" + (exc.stdout or "")
        raise RuntimeError(f"从视频提取 wav 失败：{detail.strip()}") from exc
    if not out_wav.exists() or out_wav.stat().st_size <= 0:
        raise RuntimeError("从视频提取 wav 完成但输出文件无效。")


def _yt_dlp_popen_communicate(
    proc: subprocess.Popen,
    cancel_event: threading.Event | None,
    pause_event: threading.Event | None,
) -> None:
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
        raise RuntimeError(detail.strip() or "yt-dlp 失败")


def download_source_video(
    url: str,
    platform: Platform,
    item_out: Path,
    cancel_event: threading.Event | None = None,
    pause_event: threading.Event | None = None,
) -> Path:
    item_out.mkdir(parents=True, exist_ok=True)
    out_template = str(item_out / "source.%(ext)s")
    if platform == "bilibili":
        format_args = [
            "-f",
            "bv*+ba/bestvideo+bestaudio/best",
            "--merge-output-format",
            "mp4",
        ]
        not_found_msg = "B 站视频下载完成但未找到 source 视频文件。"
    else:
        format_args = [
            "-f",
            "bestvideo+bestaudio/best/best",
            "--merge-output-format",
            "mp4",
        ]
        not_found_msg = "抖音视频下载完成但未找到 source 视频文件。"

    cmd = [
        "yt-dlp",
        *yt_dlp_cookie_args(),
        *format_args,
        "--no-playlist",
        "--no-warnings",
        "--newline",
        "-o",
        out_template,
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
        _yt_dlp_popen_communicate(proc, cancel_event, pause_event)
    except FileNotFoundError:
        raise RuntimeError("未找到 yt-dlp，请先安装：python -m pip install yt-dlp") from None

    video_path = find_merged_source_video(item_out)
    if not video_path:
        raise RuntimeError(not_found_msg)
    return video_path


def download_bilibili_source_video(
    url: str,
    item_out: Path,
    cancel_event: threading.Event | None = None,
    pause_event: threading.Event | None = None,
) -> Path:
    return download_source_video(url, "bilibili", item_out, cancel_event, pause_event)


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
    task_title: str = "",
    user_keywords: str = "",
    enable_llm_correct: bool = True,
    post_asr_mode: str = "correct",
    polish_model: str = tpol.DEFAULT_POLISH_MODEL,
) -> dict[str, float]:
    vocabulary_id: str | None = None
    try:
        vocabulary_id = tc.prepare_asr_vocabulary(
            api_key, output_dir, task_title=task_title or output_dir.name, user_keywords=user_keywords
        )
    except Exception as exc:
        print(f"[{output_dir.name}] 热词准备失败（继续转写）：{exc}")

    task_id = submit_asr(
        api_key, media_url, oss_resolve=oss_resolve, vocabulary_id=vocabulary_id
    )
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

    mode = (post_asr_mode or "correct").strip().lower()
    if mode not in ("correct", "polish", "none"):
        mode = "correct"

    llm_cost = 0.0
    post_label = "纠错"
    try:
        if mode == "polish":
            post_label = "润色"
            print(f"[{output_dir.name}] 转写后轻量润色（{polish_model}）…")
            polished = tpol.polish_sentences(api_key, sentences, model=polish_model)
            write_outputs(polished, output_dir)
        elif mode == "none":
            post_label = "无"
            write_outputs(sentences, output_dir)
        else:
            _, llm_cost = tc.run_post_asr_correction(
                api_key=api_key,
                output_dir=output_dir,
                sentences=sentences,
                task_title=task_title or output_dir.name,
                user_keywords=user_keywords,
                enable_llm=enable_llm_correct,
            )
    except Exception as exc:
        if mode == "polish":
            print(f"[{output_dir.name}] 润色失败，写入原稿：{exc}")
        elif mode == "correct":
            print(f"[{output_dir.name}] 转写后纠错失败，写入未纠错稿：{exc}")
        else:
            print(f"[{output_dir.name}] 写入原稿失败：{exc}")
        write_outputs(sentences, output_dir)

    asr_cost = estimate_cost_cny(task_result, sentences, price_per_hour=DEFAULT_PRICE_PER_HOUR)
    job_cost = merge_job_cost(asr_cost, llm_cost)
    job_cost["post_asr_label"] = post_label
    job_cost["post_asr_mode"] = mode
    print_job_cost(output_dir.name, job_cost, len(sentences))
    return job_cost


def run_local(
    args: argparse.Namespace,
    cancel_event: threading.Event | None = None,
    pause_event: threading.Event | None = None,
    *,
    copy_video_to_task: bool = False,
    copy_video_fn: Callable[[Path, Path], Path] | None = None,
) -> dict[str, float]:
    out_root = args.out_dir.resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    audio_tmp = out_root / "_audio_tmp"
    audio_tmp.mkdir(parents=True, exist_ok=True)
    local_checkpoint = out_root / "_local_done_checkpoint.json"
    done_local_keys = load_done_local_keys(local_checkpoint)
    batch_keys: set[str] = set()

    totals = new_run_cost_totals()
    processed_count = 0
    skipped_count = 0
    ck = correction_kwargs_from_args(args)

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

        fp = local_video_fingerprint(video)
        if fp in batch_keys:
            print(f"[skip] 本批重复，跳过：{video}")
            skipped_count += 1
            continue
        batch_keys.add(fp)

        if fp in done_local_keys:
            print(f"[skip] 已完成（记录），跳过：{video}")
            skipped_count += 1
            continue

        existing = find_completed_task_for_local_video(out_root, video)
        if existing is not None:
            print(f"[skip] 已完成，跳过：{video}")
            print(f"       已有任务：{existing}")
            done_local_keys.add(fp)
            save_done_local_keys(local_checkpoint, done_local_keys)
            skipped_count += 1
            continue

        name = sanitize_name(video.stem)
        item_out = out_root / name
        if is_valid_result_json(item_out / "result.json"):
            manifest_path = item_out / MANIFEST_NAME
            same_file = True
            if manifest_path.is_file():
                try:
                    data = json.loads(manifest_path.read_text(encoding="utf-8"))
                    if str(data.get("source_fingerprint") or "") not in ("", fp):
                        prev_lv = str(data.get("local_video") or "")
                        if prev_lv:
                            try:
                                same_file = Path(prev_lv).resolve() == video.resolve()
                            except Exception:
                                same_file = False
                except Exception:
                    pass
            if same_file:
                print(f"[skip] 已完成，跳过：{video}")
                print(f"       任务目录：{item_out}")
                done_local_keys.add(fp)
                save_done_local_keys(local_checkpoint, done_local_keys)
                skipped_count += 1
                continue

        if copy_video_to_task:
            if copy_video_fn is None:
                raise RuntimeError("copy_video_to_task 需要 copy_video_fn")
            source_video = copy_video_fn(video, item_out)
        else:
            source_video = video
            item_out.mkdir(parents=True, exist_ok=True)

        local_audio = audio_tmp / f"{name}.wav"
        extract_audio(source_video, local_audio)
        print(f"[{name}] 已提取音频: {local_audio}")

        oss_url = upload_to_dashscope_tmp(args.api_key, local_audio)
        print(f"[{name}] 已上传临时存储: {oss_url}")

        cost = process_single_source(
            api_key=args.api_key,
            media_url=oss_url,
            output_dir=item_out,
            poll_interval=args.poll_interval,
            timeout=args.timeout,
            oss_resolve=True,
            cancel_event=cancel_event,
            pause_event=pause_event,
            task_title=name,
            **ck,
        )
        write_task_manifest(
            item_out,
            {
                "task_name": name,
                "mode": "local",
                "local_video": str(source_video.resolve()),
                "source_fingerprint": fp,
                "user_keywords": ck.get("user_keywords", ""),
                **manifest_transcript_fields(item_out),
            },
        )
        done_local_keys.add(fp)
        save_done_local_keys(local_checkpoint, done_local_keys)
        add_job_cost_to_totals(totals, cost)
        processed_count += 1

    print_batch_cost_summary(totals, processed_count, skipped_count)
    return {
        "processed_count": float(processed_count),
        "total_seconds": totals["total_seconds"],
        "total_cost_cny": totals["total_cost_cny"],
        "asr_cost_cny": totals["asr_cost_cny"],
        "llm_correct_cost_cny": totals["llm_correct_cost_cny"],
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
    checkpoint_path, done_urls = load_done_urls_merged(out_root)

    totals = new_run_cost_totals()
    processed_count = 0
    ck = correction_kwargs_from_args(args)

    for idx, raw_input in enumerate(args.urls, start=1):
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

        media_url = normalize_entry_url(extract_url_from_paste(raw_input))
        if not media_url:
            print(f"跳过（无法解析链接）：{raw_input!r}", file=sys.stderr)
            continue

        platform = detect_platform(media_url)
        if not platform:
            print(
                f"跳过（仅支持 B 站 / 抖音）：{media_url}",
                file=sys.stderr,
            )
            continue

        if platform == "bilibili":
            items = fetch_bilibili_entries(
                media_url, cancel_event=cancel_event, pause_event=pause_event
            )
            if not items:
                items = [{"url": media_url, "title": ""}]
            if len(items) > 1:
                print(f"检测到 B 站合集/多分P，共 {len(items)} 个条目，将逐个处理。")
        else:
            items = fetch_douyin_entry(
                media_url, cancel_event=cancel_event, pause_event=pause_event
            )

        for sub_idx, item in enumerate(items, start=1):
            entry_url = normalize_entry_url(item.get("url") or media_url)
            if entry_url in done_urls:
                print(f"[skip] 已完成，跳过：{entry_url}")
                continue

            parsed = urllib.parse.urlparse(entry_url)
            base_name = Path(parsed.path).stem or f"url_{idx}_{sub_idx}"
            name = sanitize_name(base_name)
            id_fallback = (
                extract_bilibili_bvid(entry_url)
                if platform == "bilibili"
                else (extract_douyin_video_id(entry_url) or name)
            )
            display_name = (item.get("title") or "").strip()
            if not display_name:
                display_name = (
                    fetch_ytdlp_title(entry_url, cancel_event=cancel_event, pause_event=pause_event)
                    or ""
                )
            display_name = display_name.strip() or str(id_fallback)
            item_out = out_root / sanitize_name(f"{display_name}_{sub_idx:02d}")
            task_key = item_out.name
            local_wav = url_tmp / f"{task_key}.wav"
            local_video_path: Path | None = find_merged_source_video(item_out)
            oss_url: str | None = None
            plat_label = platform_label(platform)

            try:
                wav_ok = local_wav.exists() and local_wav.stat().st_size > 0
                if wav_ok and local_video_path:
                    print(f"[{task_key}] 复用已缓存音视频：wav={local_wav} video={local_video_path}")
                elif local_video_path and not wav_ok:
                    print(f"[{task_key}] 复用已下载视频并提取音频：{local_video_path}")
                    extract_wav_for_asr(local_video_path, local_wav)
                    print(f"[{task_key}] 已提取音频：{local_wav}")
                elif wav_ok and not local_video_path:
                    print(f"[{task_key}] 仅有历史 wav、缺少视频缓存，重新下载：{entry_url}")
                    local_video_path = download_source_video(
                        entry_url, platform, item_out, cancel_event, pause_event
                    )
                    extract_wav_for_asr(local_video_path, local_wav)
                else:
                    print(f"[{task_key}] 检测到{plat_label}链接，先下载视频并转音频：{entry_url}")
                    local_video_path = download_source_video(
                        entry_url, platform, item_out, cancel_event, pause_event
                    )
                    print(f"[{task_key}] 已下载视频：{local_video_path}")
                    extract_wav_for_asr(local_video_path, local_wav)
                    print(f"[{task_key}] 已提取音频：{local_wav}")
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
                    task_title=display_name,
                    **ck,
                )
            except Exception as exc:
                msg = _format_download_error(exc, platform)
                print(f"[{task_key}] 媒体下载/转码/上传失败：{msg}", file=sys.stderr)
                if platform == "douyin":
                    raise RuntimeError(
                        f"[{task_key}] 抖音须先下载音视频再识别。请先修 Cookie：python tools/doctor.py\n{msg}"
                    ) from exc
                print(f"[{task_key}] 回退直链识别：{exc}")
                cost = process_single_source(
                    api_key=args.api_key,
                    media_url=entry_url,
                    output_dir=item_out,
                    poll_interval=args.poll_interval,
                    timeout=args.timeout,
                    oss_resolve=False,
                    cancel_event=cancel_event,
                    pause_event=pause_event,
                    task_title=display_name,
                    **ck,
                )
                local_video_path = None
                oss_url = None

            write_task_manifest(
                item_out,
                {
                    "task_name": task_key,
                    "mode": platform,
                    "source_url": entry_url,
                    "local_video": str(local_video_path.resolve()) if local_video_path else "",
                    "local_audio": str(local_wav.resolve()) if oss_url else "",
                    "user_keywords": ck.get("user_keywords", ""),
                    "post_asr_mode": ck.get("post_asr_mode", "correct"),
                    **manifest_transcript_fields(item_out),
                },
            )
            add_job_cost_to_totals(totals, cost)
            processed_count += 1
            done_urls.add(entry_url)
            save_done_urls(checkpoint_path, done_urls)

    if processed_count > 1:
        print_batch_cost_summary(totals, processed_count)
    return {
        "processed_count": float(processed_count),
        "total_seconds": totals["total_seconds"],
        "total_cost_cny": totals["total_cost_cny"],
        "asr_cost_cny": totals["asr_cost_cny"],
        "llm_correct_cost_cny": totals["llm_correct_cost_cny"],
    }
