"""Slice logic modes: how to find segment boundaries (not content style templates)."""

from __future__ import annotations

# Built-in defaults (no GUI controls).
DEFAULT_MIN_SEC = 20
DEFAULT_MAX_SEC = 0  # 0 = no upper duration cap
DEFAULT_CHUNK_MINUTES = 30
DEFAULT_CHUNK_RETRIES = 2
DEFAULT_RULE_FALLBACK = True
DEFAULT_SLICE_LOGIC = "按主题/关键词"

SLICE_LOGIC_MODES: dict[str, dict[str, str]] = {
    "按主题/关键词": {
        "summary": "适合：找出视频中关于某主题、品牌、产品或关键词的连续讲述，合并为完整段落。",
        "how": (
            "切片逻辑：按主题/关键词划分时间。"
            "在转写中找出与目标主题相关的句子，将连续相关内容合并为一个或多个时间段；"
            "同一主题尽量完整，避免为做短而无故切碎。"
        ),
        "default_text": "提取所有与「蔚来 / ES9」相关的连续内容，合并为完整段落，不要碎成很多短段。",
    },
    "按人物/嘉宾": {
        "summary": "适合：按主播、嘉宾、连麦对象、姓名/称呼划分段落（依赖文中出现的人名，无说话人标签时靠推断）。",
        "how": (
            "切片逻辑：按人物/嘉宾划分时间。"
            "根据转写中出现的姓名、称呼、角色指代，找出该人物连续发言或相关讨论的区间；"
            "人物切换处作为边界。"
        ),
        "default_text": "只保留「张三」相关连续段落，从首次提到到该话题结束。",
    },
    "按议题/问题": {
        "summary": "适合：按「一个问题 + 完整回答」切一段，适合访谈、答疑、圆桌。",
        "how": (
            "切片逻辑：按议题/问题划分时间。"
            "识别问题提出到回答结束的范围，每个议题尽量包含完整问答，避免只截回答的一半。"
        ),
        "default_text": "切出「关于续航」这一问一答的完整讨论。",
    },
    "按章节/段落": {
        "summary": "适合：视频有明确章节、环节、Part（教程、发布会分段、直播环节）。",
        "how": (
            "切片逻辑：按章节/段落划分时间。"
            "根据转写中的章节提示、环节转换、话题切换，划分结构化段落。"
        ),
        "default_text": "只要「产品介绍」章节，不要开场寒暄和结尾致谢。",
    },
    "按时间范围": {
        "summary": "适合：已知大概起止时间，直接裁出该区间（须在切片目标中写明时间）。",
        "how": (
            "切片逻辑：按用户给出的时间范围裁剪。"
            "以切片目标中的起止时间为准，可略向外扩展几秒以保证句意完整。"
        ),
        "default_text": "保留 00:45:00–01:10:00，前后可各多留约 5 秒。",
    },
    "高光混剪": {
        "summary": "适合：多条短、有冲击力的高光片段合集（笑点、冲突、金句），不是一整段完整主题。",
        "how": (
            "切片逻辑：高光混剪。"
            "挑选多个相对独立、节奏紧凑、信息或情绪密度高的片段；"
            "段数与每段时长由内容决定，可多条、可较短，但每段应能独立看懂。"
        ),
        "default_text": "找反应大、能独立看懂的精彩片段，段数按内容实际需要决定。",
    },
}


def get_logic_how(logic_key: str) -> str:
    mode = SLICE_LOGIC_MODES.get(logic_key) or SLICE_LOGIC_MODES[DEFAULT_SLICE_LOGIC]
    return mode["how"]


def get_logic_summary(logic_key: str) -> str:
    mode = SLICE_LOGIC_MODES.get(logic_key) or SLICE_LOGIC_MODES[DEFAULT_SLICE_LOGIC]
    return mode["summary"]


def get_logic_default_text(logic_key: str) -> str:
    mode = SLICE_LOGIC_MODES.get(logic_key) or SLICE_LOGIC_MODES[DEFAULT_SLICE_LOGIC]
    return mode["default_text"]
