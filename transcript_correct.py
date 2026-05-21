#!/usr/bin/env python3
"""
Post-ASR transcript correction: per-task glossary, optional ASR hotwords, optional LLM polish.

Layers implemented:
  1) ASR hotwords via DashScope AsrPhraseManager (best-effort; skipped if SDK missing)
  2) Rule replacement from task glossary (title + user keywords)
  4) LLM sentence text correction (timestamps unchanged)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def _subprocess_kwargs() -> dict[str, Any]:
    if sys.platform != "win32":
        return {}
    return {"creationflags": subprocess.CREATE_NO_WINDOW}


def ensure_dashscope() -> bool:
    """Import dashscope; auto pip install when missing (non-frozen runtime)."""
    try:
        import dashscope  # noqa: F401
        return True
    except ImportError:
        pass

    if getattr(sys, "frozen", False):
        print("热词：内置 dashscope 未加载，请使用最新打包的 exe 或联系更新。", flush=True)
        return False

    print("热词：未检测到 dashscope，正在自动安装…", flush=True)
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "dashscope", "-q"],
            check=True,
            capture_output=True,
            text=True,
            **_subprocess_kwargs(),
        )
        import dashscope  # noqa: F401
        print("热词：dashscope 安装完成。", flush=True)
        return True
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or exc.stdout or str(exc)).strip()
        print(f"热词：自动安装 dashscope 失败：{err}", flush=True)
        return False
    except ImportError:
        print("热词：安装后仍无法导入 dashscope。", flush=True)
        return False

KNOWN_BRANDS = (
    "蔚来",
    "理想",
    "问界",
    "小米",
    "比亚迪",
    "特斯拉",
    "极氪",
    "领克",
    "华为",
    "阿维塔",
    "小鹏",
    "吉利",
    "长城",
    "奔驰",
    "宝马",
    "奥迪",
    "丰田",
    "本田",
    "日产",
)

CHAT_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
CHAT_MODEL = "qwen-plus"
GLOSSARY_CHAT_MODEL = "qwen-turbo"
DEFAULT_INPUT_CNY_PER_1K = 0.004
DEFAULT_OUTPUT_CNY_PER_1K = 0.012
LLM_CORRECT_MAX_CHARS_PER_BATCH = 11000


def _env_flag(name: str, default: str = "1") -> bool:
    return os.environ.get(name, default).strip().lower() not in ("0", "false", "no", "off")


def _ollama_config() -> tuple[str, str]:
    base = (os.environ.get("OLLAMA_BASE_URL") or "http://127.0.0.1:11434").rstrip("/")
    model = (os.environ.get("OLLAMA_MODEL") or "qwen2.5:7b").strip()
    return base, model


def request_json(url: str, method: str, headers: dict[str, str], body: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url=url, method=method, headers=headers, data=data)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            text = resp.read().decode("utf-8")
            return json.loads(text) if text.strip() else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {url}\n{detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"请求失败: {url}\n{exc}") from exc


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


def split_user_hints(text: str) -> list[str]:
    if not text.strip():
        return []
    parts = re.split(r"[,，;；\n|/]+", text)
    return [p.strip() for p in parts if p.strip()]


def extract_terms_from_title(title: str) -> list[str]:
    if not title.strip():
        return []
    found: list[str] = []
    seen: set[str] = set()

    def add(term: str) -> None:
        t = term.strip()
        if not t or len(t) < 2 or t in seen:
            return
        seen.add(t)
        found.append(t)

    for brand in KNOWN_BRANDS:
        if brand in title:
            add(brand)
    for m in re.finditer(r"[\u4e00-\u9fff]{2,12}[A-Za-z]?\d+[A-Za-z0-9]*", title):
        add(m.group())
    for m in re.finditer(r"[A-Za-z]+\d+[A-Za-z0-9]*", title):
        add(m.group())
    for part in re.split(r"[,，_\-|/、\s]+", title):
        part = re.sub(r"^\d+款", "", part).strip()
        if 2 <= len(part) <= 32:
            add(part)
    return found


def expand_aliases(canonical: str) -> list[str]:
    c = canonical.strip()
    if not c:
        return []
    aliases: list[str] = []
    upper = c.upper()

    if "蔚来" in c or "ES9" in upper:
        aliases.extend(
            [
                "未来js9",
                "未来 js9",
                "未来 js 9",
                "未来js 9",
                "未来J9",
                "未来 J9",
                "未来 J 9",
                "es 9",
                "es9",
                "ES 9",
                "gs 9",
                "gs9",
                "g 9",
                "吉S9",
                "吉 S 9",
                "米S9",
                "米 S 9",
                "机九",
                "以S 9",
                "以 S 9",
            ]
        )
    if "理想" in c or re.search(r"\bL\s*9\b", c, re.I):
        aliases.extend(
            [
                "L9 Levis",
                "L 9Levis",
                "L九雷维斯",
                "L 9 la",
                "L9l",
                "L 9l",
                "L九",
            ]
        )
    if "问界" in c or re.search(r"\bM\s*9\b", c, re.I):
        aliases.extend(["新M9", "标轴版M9", "米S 9", "友伤"])
    if "9系" in c or "酒系" in c:
        aliases.append("酒系")

    out: list[str] = []
    seen: set[str] = set()
    for a in aliases:
        a = a.strip()
        if not a or a == c or a in seen:
            continue
        seen.add(a)
        out.append(a)
    return out


def sample_sentences_for_glossary(sentences: list[dict[str, Any]], max_chars: int = 6000) -> str:
    if not sentences:
        return ""
    n = len(sentences)
    if n <= 40:
        indices = list(range(n))
    else:
        head = list(range(min(15, n)))
        mid_start = max(0, n // 2 - 7)
        mid = list(range(mid_start, min(mid_start + 15, n)))
        tail = list(range(max(0, n - 15), n))
        indices = sorted(set(head + mid + tail))
    parts: list[str] = []
    total = 0
    for i in indices:
        text = str(sentences[i].get("text") or "").strip()
        if not text:
            continue
        chunk = text if len(text) <= 400 else text[:400] + "…"
        if total + len(chunk) > max_chars:
            break
        parts.append(chunk)
        total += len(chunk)
    return "\n".join(parts)


def _parse_entities_json(content: str) -> list[dict[str, Any]]:
    content = content.strip()
    match = re.search(r"\[.*\]", content, flags=re.S)
    json_text = match.group(0) if match else content
    arr = json.loads(json_text)
    if not isinstance(arr, list):
        return []
    out: list[dict[str, Any]] = []
    for it in arr:
        if not isinstance(it, dict):
            continue
        canon = str(it.get("canonical") or it.get("name") or "").strip()
        if not canon or len(canon) < 2:
            continue
        aliases_raw = it.get("aliases") or it.get("alias") or []
        if isinstance(aliases_raw, str):
            aliases = [a.strip() for a in re.split(r"[,，;；]+", aliases_raw) if a.strip()]
        else:
            aliases = [str(a).strip() for a in aliases_raw if str(a).strip()]
        out.append({"canonical": canon, "aliases": aliases[:16]})
    return out


def extract_entities_via_ollama(text: str) -> tuple[list[dict[str, Any]], float] | None:
    if not text.strip():
        return None
    base, model = _ollama_config()
    tags_url = f"{base}/api/tags"
    try:
        with urllib.request.urlopen(tags_url, timeout=2) as resp:
            if resp.status != 200:
                return None
    except Exception:
        return None

    prompt = (
        "从下面语音转写抽样文本中提取专名（人名、书名、地名、术语等）。\n"
        "只输出 JSON 数组，每项：{\"canonical\":\"标准写法\",\"aliases\":[\"常见误听1\"]}\。"
        "不要 markdown，不要解释。若无明显专名返回 []。\n\n"
        f"{text[:6000]}"
    )
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0.1},
    }
    req = urllib.request.Request(
        f"{base}/api/chat",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    content = str((data.get("message") or {}).get("content") or "").strip()
    if not content:
        return None
    try:
        entities = _parse_entities_json(content)
    except json.JSONDecodeError:
        return None
    return entities, 0.0


def extract_entities_via_dashscope(api_key: str, text: str) -> tuple[list[dict[str, Any]], float]:
    if not api_key.strip() or not text.strip():
        return [], 0.0
    prompt = (
        "从下面语音转写抽样文本中提取专名（人名、书名、地名、术语等）。\n"
        "只输出 JSON 数组，每项字段 canonical（标准写法）、aliases（字符串数组，常见 ASR 误听）。\n"
        "不要 markdown。\n\n"
        f"{text[:6000]}"
    )
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {
        "model": GLOSSARY_CHAT_MODEL,
        "messages": [
            {"role": "system", "content": "只返回合法 JSON 数组。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
    }
    data = request_json(CHAT_URL, "POST", headers, body)
    content = (
        ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    ).strip()
    cost = estimate_chat_cost_cny(data, prompt, content)
    try:
        entities = _parse_entities_json(content)
    except json.JSONDecodeError:
        entities = []
    return entities, cost


def merge_glossary_entities(base: dict[str, Any], extra: list[dict[str, Any]]) -> dict[str, Any]:
    entities = list(base.get("entities") or [])
    seen = {str(e.get("canonical", "")).strip() for e in entities}
    for ent in extra:
        canon = str(ent.get("canonical", "")).strip()
        if not canon or canon in seen:
            continue
        seen.add(canon)
        entities.append(
            {
                "canonical": canon,
                "aliases": expand_aliases(canon) + list(ent.get("aliases") or []),
            }
        )
    out = dict(base)
    out["entities"] = entities
    return out


def enrich_glossary(
    title: str,
    user_hints: str,
    sentences: list[dict[str, Any]],
    api_key: str,
) -> tuple[dict[str, Any], float]:
    glossary = build_glossary(title, user_hints)
    if not _env_flag("TRANSCRIPT_GLOSSARY_LLM", "1"):
        return glossary, 0.0

    sample = sample_sentences_for_glossary(sentences)
    if not sample.strip():
        return glossary, 0.0

    before = len(glossary.get("entities") or [])
    cost = 0.0
    extra: list[dict[str, Any]] = []
    source = ""

    ollama_result = extract_entities_via_ollama(sample)
    if ollama_result is not None:
        extra, _ = ollama_result
        source = "Ollama"
    elif not user_hints.strip() and api_key.strip():
        extra, cost = extract_entities_via_dashscope(api_key, sample)
        source = "云端"
    elif user_hints.strip():
        print("纠错：抽专名 Ollama 不可用，已有关键词则跳过云端抽专名。", flush=True)
        return glossary, 0.0
    else:
        print("纠错：抽专名跳过（无 Ollama 且无 API Key）。", flush=True)
        return glossary, 0.0

    glossary = merge_glossary_entities(glossary, extra)
    added = len(glossary.get("entities") or []) - before
    if source:
        print(f"纠错：抽专名 使用 {source}，新增 {added} 个实体", flush=True)
    return glossary, cost


def build_glossary(title: str, user_hints: str = "") -> dict[str, Any]:
    terms: list[str] = []
    seen: set[str] = set()
    for t in extract_terms_from_title(title) + split_user_hints(user_hints):
        if t in seen:
            continue
        seen.add(t)
        terms.append(t)

    entities: list[dict[str, Any]] = []
    for term in terms:
        entities.append(
            {
                "canonical": term,
                "aliases": expand_aliases(term),
            }
        )
    return {
        "source": {"title": title, "user_hints": user_hints},
        "entities": entities,
    }


def glossary_to_hotwords(glossary: dict[str, Any], max_count: int = 120) -> dict[str, int]:
    hot: dict[str, int] = {}
    for ent in glossary.get("entities") or []:
        canon = str(ent.get("canonical", "")).strip()
        if canon and canon not in hot:
            hot[canon] = 5
        for alias in ent.get("aliases") or []:
            a = str(alias).strip()
            if a and len(a) <= 15 and a not in hot:
                hot[a] = 4
        if len(hot) >= max_count:
            break
    return dict(list(hot.items())[:max_count])


def create_asr_vocabulary_id(api_key: str, hotwords: dict[str, int]) -> str | None:
    """Layer 1: create phrase list; return vocabulary_id for transcription input."""
    if not hotwords:
        return None
    if not ensure_dashscope():
        return None

    import dashscope
    from dashscope.audio.asr import AsrPhraseManager

    dashscope.api_key = api_key
    # Recorded-file API documents vocabulary_id; phrase manager lists v1 models — try v1 compile.
    models_to_try = ("paraformer-v1", "paraformer-realtime-v1")
    for model in models_to_try:
        try:
            result = AsrPhraseManager.create_phrases(model=model, phrases=hotwords)
            output = getattr(result, "output", None) or {}
            if isinstance(output, dict):
                vid = output.get("finetuned_output") or output.get("vocabulary_id")
            else:
                vid = getattr(output, "finetuned_output", None)
            if vid:
                print(f"热词：已创建 vocabulary_id={vid}（model={model}，{len(hotwords)} 条）", flush=True)
                return str(vid)
        except Exception as exc:
            print(f"热词：model={model} 创建失败：{exc}", flush=True)
    return None


def build_replacement_pairs(glossary: dict[str, Any]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for ent in glossary.get("entities") or []:
        canon = str(ent.get("canonical", "")).strip()
        if not canon:
            continue
        for alias in ent.get("aliases") or []:
            a = str(alias).strip()
            if a and a != canon:
                pairs.append((a, canon))
    pairs.sort(key=lambda x: len(x[0]), reverse=True)
    return pairs


def apply_glossary(sentences: list[dict[str, Any]], glossary: dict[str, Any]) -> list[dict[str, Any]]:
    pairs = build_replacement_pairs(glossary)
    if not pairs:
        return [dict(s) for s in sentences]
    out: list[dict[str, Any]] = []
    for s in sentences:
        text = str(s.get("text", ""))
        for alias, canon in pairs:
            if alias in text:
                text = text.replace(alias, canon)
        item = dict(s)
        item["text"] = text
        out.append(item)
    return out


def estimate_chat_cost_cny(data: dict[str, Any], prompt_text: str, completion_text: str) -> float:
    usage = data.get("usage") or {}
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    total_tokens = usage.get("total_tokens")
    if prompt_tokens is None or completion_tokens is None:
        if total_tokens is not None:
            pt = int(float(total_tokens) * 0.75)
            ct = max(0, int(float(total_tokens)) - pt)
        else:
            pt = max(1, int(len(prompt_text) / 1.6))
            ct = max(1, int(len(completion_text) / 1.6))
    else:
        pt = int(float(prompt_tokens))
        ct = int(float(completion_tokens))
    return (pt / 1000.0) * DEFAULT_INPUT_CNY_PER_1K + (ct / 1000.0) * DEFAULT_OUTPUT_CNY_PER_1K


def _glossary_hint_block(glossary: dict[str, Any]) -> str:
    lines: list[str] = []
    for ent in glossary.get("entities") or []:
        canon = str(ent.get("canonical", "")).strip()
        aliases = [str(a).strip() for a in (ent.get("aliases") or []) if str(a).strip()]
        if canon:
            if aliases:
                lines.append(f"- {canon}（常见误听：{', '.join(aliases[:12])}）")
            else:
                lines.append(f"- {canon}")
    return "\n".join(lines) if lines else "（无）"


def llm_correct_batch(
    api_key: str,
    sentences: list[dict[str, Any]],
    glossary: dict[str, Any],
    title: str,
) -> tuple[list[dict[str, Any]], float]:
    if not sentences:
        return [], 0.0

    lines = []
    for s in sentences:
        idx = s.get("index", 0)
        lines.append(f"{idx}|{s.get('text', '')}")
    block = "\n".join(lines)
    glossary_hint = _glossary_hint_block(glossary)

    prompt = (
        "你是语音转写纠错助手。下面每行格式为：句子序号|原文。\n"
        "请只修正明显的 ASR 误听（品牌、车型、人名、数字单位等），不要改写语义，不要合并或拆分句子。\n"
        f"视频标题：{title or '（未知）'}\n"
        f"本期实体参考：\n{glossary_hint}\n\n"
        "输出必须是 JSON 数组，不要 markdown。每项字段：index（整数，与输入序号一致）, text（纠错后文本）。\n"
        "只返回 JSON。\n\n"
        f"输入：\n{block}"
    )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": CHAT_MODEL,
        "messages": [
            {"role": "system", "content": "你严格按要求返回可解析 JSON。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
    }
    data = request_json(CHAT_URL, "POST", headers, body)
    content = (
        ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    ).strip()
    cost = estimate_chat_cost_cny(data, prompt, content)

    match = re.search(r"\[.*\]", content, flags=re.S)
    json_text = match.group(0) if match else content
    arr = json.loads(json_text)
    if not isinstance(arr, list):
        raise RuntimeError("LLM 纠错输出不是数组。")

    by_index: dict[int, str] = {}
    for it in arr:
        if not isinstance(it, dict):
            continue
        try:
            idx = int(it.get("index"))
        except Exception:
            continue
        text = str(it.get("text", "")).strip()
        if text:
            by_index[idx] = text

    out: list[dict[str, Any]] = []
    for s in sentences:
        item = dict(s)
        idx = int(item.get("index") or 0)
        if idx in by_index:
            item["text"] = by_index[idx]
        out.append(item)
    return out, cost


def _iter_llm_batches(
    sentences: list[dict[str, Any]], max_chars: int = LLM_CORRECT_MAX_CHARS_PER_BATCH
) -> list[list[dict[str, Any]]]:
    batches: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    chars = 0
    for s in sentences:
        text = str(s.get("text") or "")
        line_chars = len(text) + 16
        if current and chars + line_chars > max_chars:
            batches.append(current)
            current = []
            chars = 0
        current.append(s)
        chars += line_chars
    if current:
        batches.append(current)
    return batches


def llm_correct_sentences(
    api_key: str,
    sentences: list[dict[str, Any]],
    glossary: dict[str, Any],
    title: str,
    batch_size: int = 35,
) -> tuple[list[dict[str, Any]], float]:
    del batch_size  # 兼容旧调用；按字符预算分批
    if not api_key.strip():
        return sentences, 0.0
    batches = _iter_llm_batches(sentences)
    if not batches:
        return sentences, 0.0
    total_batches = len(batches)
    total_cost = 0.0
    merged: list[dict[str, Any]] = []
    for bi, batch in enumerate(batches, start=1):
        print(f"纠错 LLM：第 {bi}/{total_batches} 批（本批 {len(batch)} 句）…", flush=True)
        corrected, cost = llm_correct_batch(api_key, batch, glossary, title)
        total_cost += cost
        expected = {int(s.get("index") or 0) for s in batch}
        returned = {int(s.get("index") or 0) for s in corrected}
        missing = expected - returned
        if missing:
            print(
                f"纠错 LLM：第 {bi} 批有 {len(missing)} 句未返回，保留原文。",
                flush=True,
            )
        merged.extend(corrected)
    return merged, total_cost


def resolve_transcript_json(path_or_dir: Path) -> Path:
    p = path_or_dir
    if p.is_dir():
        return p / "result.json"
    return p


def run_post_asr_correction(
    api_key: str,
    output_dir: Path,
    sentences: list[dict[str, Any]],
    task_title: str,
    user_keywords: str = "",
    enable_llm: bool = True,
    glossary: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], float]:
    """Layer 2 + 4 after raw ASR. Returns (corrected sentences, llm cost cny)."""
    output_dir = output_dir.resolve()
    llm_cost = 0.0
    if glossary is None:
        glossary, extract_cost = enrich_glossary(
            task_title, user_keywords, sentences, api_key
        )
        llm_cost += extract_cost
    else:
        glossary = build_glossary(task_title, user_keywords)

    n_entities = len(glossary.get("entities") or [])
    print(f"纠错：词表共 {n_entities} 个实体（不落盘）", flush=True)

    corrected = apply_glossary(sentences, glossary)
    changed = sum(1 for a, b in zip(sentences, corrected) if a.get("text") != b.get("text"))
    print(f"纠错：规则替换修正 {changed}/{len(sentences)} 句", flush=True)

    if enable_llm and api_key.strip():
        try:
            corrected, correct_cost = llm_correct_sentences(
                api_key, corrected, glossary, task_title
            )
            llm_cost += correct_cost
            print(f"纠错：LLM 润色完成，估算费用约 ¥{correct_cost:.6f}", flush=True)
        except Exception as exc:
            print(f"纠错：LLM 失败（保留规则结果）：{exc}", flush=True)
    elif enable_llm:
        print("纠错：未提供 API Key，跳过 LLM。", flush=True)

    from video_to_text_paraformer import write_outputs

    write_outputs(corrected, output_dir)
    return corrected, llm_cost


def prepare_asr_vocabulary(
    api_key: str,
    output_dir: Path,
    task_title: str,
    user_keywords: str = "",
) -> str | None:
    """Layer 1: build glossary file and optional vocabulary_id before ASR."""
    glossary = build_glossary(task_title, user_keywords)
    hotwords = glossary_to_hotwords(glossary)
    if not hotwords:
        return None
    return create_asr_vocabulary_id(api_key, hotwords)


def correct_existing_task_dir(
    api_key: str,
    task_dir: Path,
    user_keywords: str = "",
    enable_llm: bool = True,
) -> None:
    """Re-run layer 2+4 on an existing result.json (no re-ASR)."""
    task_dir = task_dir.resolve()
    raw_path = task_dir / "result.json"
    if not raw_path.is_file():
        raise RuntimeError(f"找不到 {raw_path}")
    sentences = json.loads(raw_path.read_text(encoding="utf-8"))
    if not isinstance(sentences, list):
        raise RuntimeError("result.json 格式错误")
    title = task_dir.name
    manifest_path = task_dir / "task_manifest.json"
    if manifest_path.is_file():
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            title = str(data.get("task_name") or title)
        except Exception:
            pass
    run_post_asr_correction(
        api_key=api_key,
        output_dir=task_dir,
        sentences=sentences,
        task_title=title,
        user_keywords=user_keywords,
        enable_llm=enable_llm,
        glossary=None,
    )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="对已有转写目录执行纠错（规则 + 可选 LLM）")
    parser.add_argument("--api-key", required=True, help="百炼 API Key")
    parser.add_argument("--task-dir", type=Path, required=True, help="含 result.json 的任务目录")
    parser.add_argument("--keywords", default="", help="额外关键词，逗号分隔")
    parser.add_argument("--no-llm", action="store_true", help="跳过 LLM，仅规则替换")
    args = parser.parse_args()
    correct_existing_task_dir(
        api_key=args.api_key.strip(),
        task_dir=args.task_dir,
        user_keywords=args.keywords,
        enable_llm=not args.no_llm,
    )


if __name__ == "__main__":
    main()
