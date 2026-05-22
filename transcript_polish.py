#!/usr/bin/env python3
"""用 DashScope 轻量 Qwen 对 ASR 句级结果做轻度书面化（保留时间戳）。"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Any

TEXT_GEN_URL_ENV = "DASHSCOPE_TEXT_GEN_URL"

DEFAULT_POLISH_MODEL = "qwen-turbo"
TEXT_GEN_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"


def _post_json(url: str, headers: dict[str, str], body: dict[str, Any], timeout_sec: int = 120) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url=url, method="POST", headers=headers, data=data)
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            text = resp.read().decode("utf-8")
            return json.loads(text) if text.strip() else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {url}\n{detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"请求失败: {url}\n{exc}") from exc


POLISH_SYSTEM = """你是语音识别后处理助手。用户会给出若干带序号的句子（来自 ASR 转写）。
请对每一句做轻度整理：修正明显的错字与同音误识，去掉多余口头禅（如无意义的「嗯」「啊」「那个」重复），略作标点与语气通顺，不改变原意。
要求：不要编造事实；不要改动可能的人名、品牌、数字、型号；不要把两句合并成一句；不要添加原文没有的信息。
你必须只输出一个 JSON 数组：数组长度与输入句数完全相同，第 i 个字符串为第 i 句润色后的纯文本（不要序号、不要时间戳、不要解释）。"""


def _extract_json_array(text: str) -> list[Any] | None:
    text = text.strip()
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if m:
        try:
            data = json.loads(m.group(1).strip())
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end > start:
        try:
            data = json.loads(text[start : end + 1])
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass
    return None


def _call_qwen_polish(
    api_key: str,
    model: str,
    numbered_block: str,
    n_lines: int,
    base_url: str,
) -> list[str]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    user_msg = (
        f"共 {n_lines} 句。请按顺序输出长度为 {n_lines} 的 JSON 字符串数组。\n\n"
        f"{numbered_block}"
    )
    body: dict[str, Any] = {
        "model": model,
        "input": {
            "messages": [
                {"role": "system", "content": POLISH_SYSTEM},
                {"role": "user", "content": user_msg},
            ]
        },
        "parameters": {
            "result_format": "message",
            "temperature": 0.2,
            "max_tokens": min(4096, 320 + n_lines * 160),
        },
    }
    data = _post_json(base_url, headers, body, timeout_sec=120)
    if data.get("code"):
        raise RuntimeError(
            f"文本润色 API 错误: {data.get('code')} {data.get('message', '')} "
            f"{json.dumps(data, ensure_ascii=False)}"
        )
    out_msg = (
        (data.get("output") or {}).get("choices", [{}])[0].get("message", {}).get("content")
        or (data.get("output") or {}).get("text")
        or ""
    )
    if isinstance(out_msg, list):
        parts = []
        for block in out_msg:
            if isinstance(block, dict) and block.get("text"):
                parts.append(str(block["text"]))
        out_msg = "".join(parts)
    else:
        out_msg = str(out_msg)

    arr = _extract_json_array(out_msg)
    if not arr or len(arr) != n_lines:
        raise RuntimeError(
            f"润色返回格式异常：期望 {n_lines} 条，解析得到 {len(arr) if arr else 0} 条。"
            f"原始片段：{out_msg[:800]!r}"
        )
    return [str(x).strip() if x is not None else "" for x in arr]


def polish_sentences(
    api_key: str,
    sentences: list[dict[str, Any]],
    *,
    model: str = DEFAULT_POLISH_MODEL,
    chunk_size: int = 24,
    text_api_url: str | None = None,
    sleep_between_chunks: float = 0.35,
) -> list[dict[str, Any]]:
    if not sentences:
        return []

    base = (text_api_url or os.environ.get(TEXT_GEN_URL_ENV) or TEXT_GEN_URL).strip()
    polished: list[dict[str, Any]] = []
    idx_global = 0

    for start in range(0, len(sentences), chunk_size):
        chunk = sentences[start : start + chunk_size]
        lines = [f"{i + 1}. {s['text']}" for i, s in enumerate(chunk)]
        block = "\n".join(lines)
        try:
            new_texts = _call_qwen_polish(api_key, model, block, len(chunk), base)
        except Exception as exc:
            print(f"[润色] 批次 {start // chunk_size + 1} 失败，本批沿用原句：{exc}", file=sys.stderr)
            new_texts = [s["text"] for s in chunk]

        for j, s in enumerate(chunk):
            idx_global += 1
            t = new_texts[j] if j < len(new_texts) else s["text"]
            if not t:
                t = s["text"]
            polished.append(
                {
                    "index": idx_global,
                    "start_ms": s["start_ms"],
                    "end_ms": s["end_ms"],
                    "start_hms": s["start_hms"],
                    "end_hms": s["end_hms"],
                    "text": t,
                }
            )
        if start + chunk_size < len(sentences) and sleep_between_chunks > 0:
            time.sleep(sleep_between_chunks)

    return polished
