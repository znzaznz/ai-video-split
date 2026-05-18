#!/usr/bin/env python3
"""Tests for clip boundary expansion and nearby merge."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auto_clip_from_transcript import (  # noqa: E402
    expand_clips_to_sentences,
    merge_nearby_clips,
)


def _sentences() -> list[dict]:
    return [
        {"start_ms": 0, "end_ms": 2000, "text": "第一句。"},
        {"start_ms": 2000, "end_ms": 5000, "text": "第二句还没说完"},
        {"start_ms": 5000, "end_ms": 8000, "text": "第三句收尾。"},
    ]


class TestClipBoundaries(unittest.TestCase):
    def test_expand_to_sentence_end_and_tail_pad(self) -> None:
        clips = [{"title": "t", "start_ms": 500, "end_ms": 3500, "reason": "ai"}]
        out = expand_clips_to_sentences(
            clips,
            _sentences(),
            head_pad_ms=0,
            tail_pad_ms=1500,
            max_extra_sentences=1,
        )
        self.assertEqual(len(out), 1)
        # Covers sentence 1 (ends 5000) + tail 1500; sentence 2 has no punct -> include sentence 2 end 5000, maybe +1
        self.assertGreaterEqual(out[0]["end_ms"], 5000 + 1500)
        self.assertLessEqual(out[0]["start_ms"], 0)

    def test_expand_includes_next_sentence_without_punct(self) -> None:
        clips = [{"title": "t", "start_ms": 2100, "end_ms": 4000, "reason": ""}]
        out = expand_clips_to_sentences(
            clips,
            _sentences(),
            head_pad_ms=0,
            tail_pad_ms=500,
            max_extra_sentences=1,
        )
        self.assertEqual(len(out), 1)
        self.assertGreaterEqual(out[0]["end_ms"], 8000)

    def test_merge_nearby_clips(self) -> None:
        clips = [
            {"title": "a", "start_ms": 0, "end_ms": 5000, "reason": ""},
            {"title": "b", "start_ms": 5500, "end_ms": 10000, "reason": ""},
        ]
        merged = merge_nearby_clips(clips, gap_ms=2000)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["end_ms"], 10000)


if __name__ == "__main__":
    unittest.main()
