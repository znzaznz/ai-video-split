#!/usr/bin/env python3
"""Adaptive slice pipeline: tier selection, optional planning AI, retrieval, coarse/fine."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from slice_logic import (
    DEFAULT_CHUNK_MINUTES,
    DEFAULT_CHUNK_TARGET_TOKENS,
    DEFAULT_MAX_SEC,
    DEFAULT_MIN_SEC,
    DEFAULT_SLICE_LOGIC,
    SLICE_LOGIC_MODES,
    get_logic_coarse_how,
    get_logic_how,
    mode_prefers_merge,
    mode_uses_retrieval,
)

# Transcript size tiers (sentence count + formatted line chars).
TIER_S_MAX_SENTENCES = 400
TIER_S_MAX_CHARS = 120_000
TIER_M_MAX_SENTENCES = 1200
TIER_M_MAX_CHARS = 350_000

CHAT_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
MODEL_PLAN = "qwen-turbo"
MODEL_COARSE = "qwen-turbo"
MODEL_FINE = "qwen-plus"

RETRIEVAL_CONTEXT_SENTENCES = 5
CHUNK_OVERLAP_SEC = 60
PLANNING_SAMPLE_LINES = 80
CHUNK_TARGET_TOKENS = DEFAULT_CHUNK_TARGET_TOKENS


class PipelineCancelled(RuntimeError):
    pass


def check_cancel(cancel_event: Any | None) -> None:
    if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
        raise PipelineCancelled("切片已取消。")


@dataclass
class SliceRules:
    pipeline: str = "single_pass"  # single_pass | chunked_fine | retrieve_coarse_fine
    tier: str = "S"
    base_mode: str = DEFAULT_SLICE_LOGIC
    search_terms: list[str] = field(default_factory=list)
    exclude_hints: str = ""
    coarse_instruction: str = ""
    fine_instruction: str = ""
    slice_logic_how: str = ""
    chunk_minutes: int = DEFAULT_CHUNK_MINUTES
    overlap_sec: int = CHUNK_OVERLAP_SEC
    min_sec: int = DEFAULT_MIN_SEC
    max_sec: int = DEFAULT_MAX_SEC
    use_retrieval: bool = False
    use_coarse_ai: bool = False
    use_planning_ai: bool = False
    use_reduce_pass: bool = False
    chunk_target_tokens: int = CHUNK_TARGET_TOKENS
    coarse_model: str = MODEL_COARSE
    fine_model: str = MODEL_FINE

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def estimate_transcript_stats(sentences: list[dict[str, Any]]) -> dict[str, Any]:
    char_count = sum(len(str(s.get("text", ""))) for s in sentences)
    line_overhead = len(sentences) * 32
    est_tokens = max(1, int((char_count + line_overhead) / 1.6))
    duration_ms = 0
    if sentences:
        duration_ms = max(int(s["end_ms"]) for s in sentences)
    return {
        "sentence_count": len(sentences),
        "char_count": char_count,
        "est_tokens": est_tokens,
        "duration_ms": duration_ms,
        "duration_min": round(duration_ms / 60_000.0, 1),
    }


def pick_tier(stats: dict[str, Any]) -> str:
    n = int(stats["sentence_count"])
    c = int(stats["char_count"])
    if n <= TIER_S_MAX_SENTENCES and c <= TIER_S_MAX_CHARS:
        return "S"
    if n <= TIER_M_MAX_SENTENCES and c <= TIER_M_MAX_CHARS:
        return "M"
    return "L"


def _extract_terms_from_goal(slice_goal: str) -> list[str]:
    goal = (slice_goal or "").strip()
    if not goal:
        return []
    parts = re.split(r"[,，、/|；;\s]+", goal)
    terms: list[str] = []
    for p in parts:
        t = p.strip().strip("「」\"'[]【】()（）")
        if len(t) >= 2:
            terms.append(t)
    quoted = re.findall(r"[「『\"']([^」』\"']{2,40})[」』\"']", goal)
    for q in quoted:
        q = q.strip()
        if q and q not in terms:
            terms.append(q)
    return terms[:24]


def _goal_complexity(slice_goal: str, logic_key: str) -> bool:
    goal = (slice_goal or "").strip()
    if len(goal) > 48:
        return True
    markers = ("不要", "排除", "只要", "仅", "除了", "主播", "嘉宾", "看法", "观点", "合并", "完整")
    if any(m in goal for m in markers):
        return True
    if logic_key in ("按人物/嘉宾", "按议题/问题", "高光混剪"):
        return True
    return False


def build_default_rules(
    logic_key: str,
    slice_goal: str | None,
    stats: dict[str, Any],
    tier: str,
    user_keywords: str = "",
    transcript_json: Any | None = None,
) -> SliceRules:
    key = logic_key if logic_key in SLICE_LOGIC_MODES else DEFAULT_SLICE_LOGIC
    goal = (slice_goal or "").strip()
    terms = collect_search_terms(goal, user_keywords, transcript_json)
    how = get_logic_how(key)
    coarse_inst = get_logic_coarse_how(key)
    use_reduce = False

    if tier == "S":
        pipeline = "single_pass"
        chunk_minutes = max(15, int(stats.get("duration_min", 0)) + 1)
        use_coarse = False
        use_retrieval = bool(terms) and mode_uses_retrieval(key)
    elif tier == "M":
        pipeline = "chunked_fine"
        chunk_minutes = 20
        use_coarse = False
        use_retrieval = mode_uses_retrieval(key)
    else:
        pipeline = "retrieve_coarse_fine"
        chunk_minutes = 20
        use_coarse = True
        use_retrieval = mode_uses_retrieval(key)
        use_reduce = True

    if key == "按时间范围":
        pipeline = "single_pass" if tier == "S" else "chunked_fine"
        use_coarse = False
        use_retrieval = False
        use_reduce = False

    if key == "高光混剪":
        use_retrieval = False
        use_reduce = True

    fine_extra = goal if goal else ""
    if mode_prefers_merge(key):
        fine_extra = (fine_extra + " 同一主题尽量合并为完整段落，避免无故切碎。").strip()

    return SliceRules(
        pipeline=pipeline,
        tier=tier,
        base_mode=key,
        search_terms=terms,
        exclude_hints="",
        coarse_instruction=coarse_inst,
        fine_instruction=fine_extra,
        slice_logic_how=how,
        chunk_minutes=chunk_minutes,
        overlap_sec=CHUNK_OVERLAP_SEC,
        use_retrieval=use_retrieval and bool(terms or key != "按时间范围"),
        use_coarse_ai=use_coarse,
        use_planning_ai=False,
        use_reduce_pass=bool(use_reduce),
    )


def collect_search_terms(
    slice_goal: str,
    user_keywords: str = "",
    transcript_json: Any | None = None,
) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()

    def add(t: str) -> None:
        t = t.strip()
        if len(t) < 2:
            return
        k = t.lower()
        if k in seen:
            return
        seen.add(k)
        terms.append(t)

    for t in _extract_terms_from_goal(slice_goal):
        add(t)
    for part in re.split(r"[,，、/|；;\s]+", user_keywords or ""):
        add(part.strip())
    if transcript_json is not None:
        try:
            from transcript_correct import build_glossary

            p = Path(transcript_json) if not isinstance(transcript_json, Path) else transcript_json
            title = p.parent.name
            manifest = p.parent / "task_manifest.json"
            uk = user_keywords
            if manifest.is_file():
                data = json.loads(manifest.read_text(encoding="utf-8"))
                title = str(data.get("task_name") or title)
                uk = str(data.get("user_keywords") or uk)
            glossary = build_glossary(title, uk)
            for ent in glossary.get("entities") or []:
                if not isinstance(ent, dict):
                    continue
                add(str(ent.get("canonical") or ""))
                for a in ent.get("aliases") or []:
                    add(str(a))
        except Exception:
            pass
    return terms[:40]


def build_transcript_sample(sentences: list[dict[str, Any]], max_lines: int = PLANNING_SAMPLE_LINES) -> str:
    lines: list[str] = []
    for i, s in enumerate(sentences[:max_lines], start=1):
        lines.append(f"{i}|{s['start_ms']}|{s['end_ms']}|{s.get('text', '')}")
    if len(sentences) > max_lines:
        lines.append(f"…（全文共 {len(sentences)} 句，此处仅节选前 {max_lines} 句供规划参考）")
    return "\n".join(lines)


def preview_execution_plan(
    logic_key: str,
    slice_goal: str | None,
    sentences: list[dict[str, Any]],
    user_keywords: str = "",
    transcript_json: Any | None = None,
    force_tier: str | None = None,
    skip_planning: bool = False,
) -> tuple[str, SliceRules, dict[str, Any], bool]:
    stats = estimate_transcript_stats(sentences)
    tier = resolve_tier(stats, force_tier)
    rules = build_default_rules(
        logic_key, slice_goal, stats, tier, user_keywords, transcript_json
    )
    will_plan = should_run_planning_ai(slice_goal, logic_key, tier, rules, skip_planning)
    return describe_execution_plan(rules, stats, will_plan), rules, stats, will_plan


def describe_execution_plan(
    rules: SliceRules,
    stats: dict[str, Any],
    will_plan: bool,
) -> str:
    steps: list[str] = []
    if will_plan:
        steps.append("规划AI定规则")
    if rules.base_mode == "按时间范围":
        steps.append("解析时间范围")
    if rules.use_retrieval and rules.search_terms:
        steps.append(f"关键词检索({len(rules.search_terms)}词)")
    if rules.pipeline == "single_pass":
        steps.append("强AI全文精切")
    elif rules.pipeline == "chunked_fine":
        steps.append(f"分块精切(~{rules.chunk_target_tokens}tokens/块)")
    else:
        if rules.use_coarse_ai:
            steps.append("弱AI粗分")
        steps.append("强AI分块精切")
    if rules.use_reduce_pass:
        steps.append("精炼合并候选")
    steps.append("ffmpeg出片")
    return (
        f"档位 {rules.tier} | 流水线 {rules.pipeline} | "
        f"{stats['sentence_count']}句/~{stats['est_tokens']}tokens → "
        + " → ".join(steps)
    )


def resolve_tier(stats: dict[str, Any], force_tier: str | None) -> str:
    ft = (force_tier or "").strip().upper()
    if ft in ("S", "M", "L"):
        return ft
    return pick_tier(stats)


def should_run_planning_ai(
    slice_goal: str | None,
    logic_key: str,
    tier: str,
    rules: SliceRules,
    skip_planning: bool = False,
) -> bool:
    if skip_planning:
        return False
    if logic_key == "按时间范围" and _parse_time_range_ms(slice_goal or ""):
        return False
    if tier == "S" and not _goal_complexity(slice_goal or "", logic_key):
        return False
    if tier == "L":
        return True
    return _goal_complexity(slice_goal or "", logic_key)


def _parse_time_range_ms(goal: str) -> tuple[int, int] | None:
    """Parse HH:MM:SS–HH:MM:SS or similar from goal text."""
    pat = re.compile(
        r"(\d{1,2}:\d{2}:\d{2}(?:[.,]\d{1,3})?|\d{1,2}:\d{2}(?:[.,]\d{1,3})?)"
        r"\s*[-–—~至到]\s*"
        r"(\d{1,2}:\d{2}:\d{2}(?:[.,]\d{1,3})?|\d{1,2}:\d{2}(?:[.,]\d{1,3})?)"
    )
    m = pat.search(goal)
    if not m:
        return None

    def to_ms(ts: str) -> int:
        ts = ts.replace(",", ".")
        parts = ts.split(":")
        if len(parts) == 2:
            h = 0
            mi, sec = parts
        else:
            h, mi, sec = parts
        sec_parts = sec.split(".")
        s = int(sec_parts[0])
        ms = int(float("0." + sec_parts[1]) * 1000) if len(sec_parts) > 1 else 0
        return (int(h) * 3600 + int(mi) * 60 + s) * 1000 + ms

    return to_ms(m.group(1)), to_ms(m.group(2))


def _parse_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```\s*$", "", text)
    start = text.find("{")
    if start < 0:
        raise ValueError("无 JSON 对象")
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])
    raise ValueError("JSON 不完整")


def plan_slice_strategy(
    api_key: str,
    logic_key: str,
    slice_goal: str | None,
    stats: dict[str, Any],
    default_rules: SliceRules,
    request_json_fn: Any,
    estimate_cost_fn: Any,
    sentences: list[dict[str, Any]] | None = None,
    cancel_event: Any | None = None,
) -> tuple[SliceRules, float]:
    """One planning LLM call to refine pipeline and instructions."""
    check_cancel(cancel_event)
    goal = (slice_goal or "").strip()
    modes_list = "\n".join(f"- {k}: {v['summary']}" for k, v in SLICE_LOGIC_MODES.items())
    sample = ""
    if sentences:
        sample = (
            "\n\n转写节选（供提取检索词与实体，勿当作全文）：\n"
            + build_transcript_sample(sentences)
        )
    prompt = (
        "你是视频切片流水线规划器。根据用户切片目标与模式，输出 JSON 执行规则（不要 markdown）。\n"
        f"用户选择的模式：{logic_key}\n"
        f"切片目标：{goal or '（未填写，按模式默认）'}\n"
        f"已有检索词建议：{default_rules.search_terms[:12]}\n"
        f"转写规模：约 {stats['sentence_count']} 句，{stats['char_count']} 字，"
        f"估算 {stats['est_tokens']} tokens，时长约 {stats['duration_min']} 分钟。\n"
        f"系统建议档位：{default_rules.tier}，建议流水线：{default_rules.pipeline}\n\n"
        f"可选模式说明：\n{modes_list}\n\n"
        "输出 JSON 字段（均可覆盖建议）：\n"
        "pipeline: single_pass | chunked_fine | retrieve_coarse_fine\n"
        "search_terms: 字符串数组，用于检索转写（从目标+转写节选提取实体/品牌/人名/议题）\n"
        "exclude_hints: 排除说明（如：不要嘉宾夸赞、不要寒暄）\n"
        "coarse_instruction: 弱模型粗分时的指令\n"
        "fine_instruction: 强模型精切时的补充指令\n"
        "chunk_minutes: 整数 10-30\n"
        "overlap_sec: 整数 30-120\n"
        "use_retrieval: bool\n"
        "use_coarse_ai: bool\n"
        "use_reduce_pass: bool\n"
        + sample
    )
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body: dict[str, Any] = {
        "model": MODEL_PLAN,
        "messages": [
            {
                "role": "system",
                "content": "只输出一个合法 JSON 对象，字段见用户说明。",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    try:
        data = request_json_fn(CHAT_URL, "POST", headers, body)
    except RuntimeError:
        body.pop("response_format", None)
        data = request_json_fn(CHAT_URL, "POST", headers, body)

    content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
    cost = estimate_cost_fn(data, prompt, content)
    if not content:
        return default_rules, cost

    try:
        parsed = _parse_json_object(content)
    except Exception:
        print("规划 AI 返回无法解析，使用默认规则。")
        return default_rules, cost

    rules = SliceRules(**default_rules.to_dict())
    for key, val in parsed.items():
        if not hasattr(rules, key):
            continue
        if key == "search_terms" and not isinstance(val, list):
            continue
        if key in ("chunk_minutes", "overlap_sec", "min_sec", "max_sec") and val is not None:
            try:
                setattr(rules, key, int(val))
            except (TypeError, ValueError):
                pass
            continue
        if key in ("use_retrieval", "use_coarse_ai") and isinstance(val, bool):
            setattr(rules, key, val)
            continue
        if isinstance(val, str) and val.strip():
            setattr(rules, key, val.strip())
    if isinstance(parsed.get("search_terms"), list):
        merged = list(
            dict.fromkeys(
                [str(x).strip() for x in rules.search_terms + parsed["search_terms"] if str(x).strip()]
            )
        )
        rules.search_terms = merged[:40]
    rules.use_planning_ai = True
    rules.slice_logic_how = get_logic_how(rules.base_mode) if rules.base_mode in SLICE_LOGIC_MODES else rules.slice_logic_how
    if not rules.slice_logic_how:
        rules.slice_logic_how = get_logic_how(logic_key)
    return rules, float(cost)


def retrieve_sentence_ranges(
    sentences: list[dict[str, Any]],
    search_terms: list[str],
    context_sentences: int = RETRIEVAL_CONTEXT_SENTENCES,
) -> list[tuple[int, int]]:
    if not search_terms:
        return [(0, len(sentences) - 1)] if sentences else []

    terms = [t.lower() for t in search_terms if t.strip()]
    hit: set[int] = set()
    for i, s in enumerate(sentences):
        text = str(s.get("text", "")).lower()
        for t in terms:
            if t in text or t.lower() in text:
                hit.add(i)
                break

    if not hit:
        return []

    ranges: list[tuple[int, int]] = []
    for idx in sorted(hit):
        lo = max(0, idx - context_sentences)
        hi = min(len(sentences) - 1, idx + context_sentences)
        if ranges and lo <= ranges[-1][1] + 1:
            ranges[-1] = (ranges[-1][0], max(ranges[-1][1], hi))
        else:
            ranges.append((lo, hi))
    return ranges


def sentences_from_ranges(
    sentences: list[dict[str, Any]], ranges: list[tuple[int, int]]
) -> list[dict[str, Any]]:
    if not ranges:
        return sentences
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for lo, hi in ranges:
        for i in range(lo, hi + 1):
            if i not in seen:
                seen.add(i)
                out.append(sentences[i])
    out.sort(key=lambda x: x["start_ms"])
    return out


def filter_sentences_by_segments(
    sentences: list[dict[str, Any]],
    segments: list[dict[str, Any]],
    pad_ms: int = 5000,
) -> list[dict[str, Any]]:
    if not segments:
        return sentences
    out: list[dict[str, Any]] = []
    for s in sentences:
        sm, em = int(s["start_ms"]), int(s["end_ms"])
        for seg in segments:
            lo = int(seg["start_ms"]) - pad_ms
            hi = int(seg["end_ms"]) + pad_ms
            if em > lo and sm < hi:
                out.append(s)
                break
    return out


def clips_from_time_range(
    sentences: list[dict[str, Any]],
    start_ms: int,
    end_ms: int,
    pad_ms: int = 5000,
    title: str = "时间范围",
) -> list[dict[str, Any]]:
    lo = max(0, start_ms - pad_ms)
    hi = end_ms + pad_ms
    if sentences:
        hi = min(hi, max(int(s["end_ms"]) for s in sentences))
    if hi <= lo:
        return []
    return [
        {
            "title": title,
            "start_ms": lo,
            "end_ms": hi,
            "reason": "按用户给定时间范围裁剪",
        }
    ]


def estimate_sentence_tokens(sentence: dict[str, Any]) -> int:
    return max(1, int((len(str(sentence.get("text", ""))) + 32) / 1.6))


def split_sentences_by_token_budget(
    sentences: list[dict[str, Any]],
    max_tokens: int,
    overlap_sentences: int = 4,
) -> list[list[dict[str, Any]]]:
    if not sentences:
        return []
    if max_tokens <= 0:
        return [sentences]
    chunks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_tokens = 0
    for s in sentences:
        t = estimate_sentence_tokens(s)
        if current and current_tokens + t > max_tokens:
            chunks.append(current)
            overlap = max(0, overlap_sentences)
            current = list(current[-overlap:]) if overlap else []
            current_tokens = sum(estimate_sentence_tokens(x) for x in current)
        current.append(s)
        current_tokens += t
    if current:
        chunks.append(current)
    return chunks if chunks else [sentences]


def get_sentence_chunks(
    sentences: list[dict[str, Any]], rules: SliceRules
) -> list[list[dict[str, Any]]]:
    """Prefer token-balanced chunks; fall back to time windows for sparse timelines."""
    target = max(8000, int(rules.chunk_target_tokens or CHUNK_TARGET_TOKENS))
    overlap_sents = max(2, int(rules.overlap_sec) // 6)
    token_chunks = split_sentences_by_token_budget(sentences, target, overlap_sents)
    if len(token_chunks) > 1:
        return token_chunks
    total_tok = sum(estimate_sentence_tokens(s) for s in sentences)
    if total_tok <= target * 1.15:
        return token_chunks
    window_ms = max(1, rules.chunk_minutes) * 60 * 1000
    overlap_ms = max(0, rules.overlap_sec) * 1000
    time_chunks = split_sentences_by_window_overlap(sentences, window_ms, overlap_ms)
    return time_chunks if len(time_chunks) > 1 else token_chunks


def format_exclude_block(exclude_hints: str) -> str:
    h = (exclude_hints or "").strip()
    if not h:
        return ""
    return "【排除条件】（必须遵守）\n" + h + "\n"


def split_sentences_by_window_overlap(
    sentences: list[dict[str, Any]], window_ms: int, overlap_ms: int
) -> list[list[dict[str, Any]]]:
    if not sentences or window_ms <= 0:
        return [sentences] if sentences else []
    overlap_ms = max(0, min(overlap_ms, window_ms // 2))
    max_end = max(int(s["end_ms"]) for s in sentences)
    chunks: list[list[dict[str, Any]]] = []
    start = 0
    while start <= max_end:
        end = start + window_ms
        block = [s for s in sentences if int(s["end_ms"]) > start and int(s["start_ms"]) < end]
        if block:
            chunks.append(block)
        if end > max_end:
            break
        start = end - overlap_ms
    return chunks if chunks else [sentences]
