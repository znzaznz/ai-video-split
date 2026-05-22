import unittest

from slice_strategy import (
    CHAT_URL,
    _parse_pad_ms,
    _parse_time_range_ms,
    _time_range_from_llm_payload,
    format_time_range_preview,
    parse_time_range_via_llm,
    parse_time_range_with_pad,
    resolve_time_range_with_pad,
)


class TestTimeRangeParse(unittest.TestCase):
    def test_colon_mm_ss(self) -> None:
        tr = _parse_time_range_ms("从 7:00-8:00 这段时间开始劫")
        self.assertIsNotNone(tr)
        self.assertEqual(tr[0], 7 * 60 * 1000)
        self.assertEqual(tr[1], 8 * 60 * 1000)

    def test_colon_hms(self) -> None:
        tr = _parse_time_range_ms("保留 00:07:00–00:08:00")
        self.assertIsNotNone(tr)
        self.assertEqual(tr[0], 7 * 60 * 1000)
        self.assertEqual(tr[1], 8 * 60 * 1000)

    def test_chinese_minutes(self) -> None:
        tr = _parse_time_range_ms("七分钟到八分20秒")
        self.assertIsNotNone(tr)
        self.assertEqual(tr[0], 7 * 60 * 1000)
        self.assertEqual(tr[1], 8 * 60 * 1000 + 20 * 1000)

    def test_digit_fen(self) -> None:
        tr = _parse_time_range_ms("7分-8分")
        self.assertIsNotNone(tr)
        self.assertEqual(tr[0], 7 * 60 * 1000)
        self.assertEqual(tr[1], 8 * 60 * 1000)

    def test_pad_from_text(self) -> None:
        goal = "从 7:00-8:00，前后可各多留约 5 秒"
        self.assertEqual(_parse_pad_ms(goal), 5000)
        parsed = parse_time_range_with_pad(goal)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed[2], 5000)

    def test_preview(self) -> None:
        prev, status = format_time_range_preview("7:00-8:00，前后各 5 秒", video_duration_ms=600_000)
        self.assertEqual(status, "ok")
        self.assertIn("06:55", prev)
        self.assertIn("08:05", prev)
        self.assertIn("约 70", prev)

    def test_llm_payload_hms(self) -> None:
        tr = _time_range_from_llm_payload(
            {"start_hms": "07:00", "end_hms": "08:00", "pad_seconds": 5}
        )
        self.assertIsNotNone(tr)
        self.assertEqual(tr[0], 7 * 60 * 1000)
        self.assertEqual(tr[1], 8 * 60 * 1000)

    def test_llm_payload_ms(self) -> None:
        tr = _time_range_from_llm_payload({"start_ms": 420000, "end_ms": 480000})
        self.assertEqual(tr, (420000, 480000))

    def test_resolve_regex_source(self) -> None:
        r = resolve_time_range_with_pad("7:00-8:00", api_key="")
        self.assertIsNotNone(r)
        self.assertEqual(r[3], "regex")
        self.assertEqual(r[2], 0)

    def test_no_pad_by_default(self) -> None:
        goal = "7:20-8:20"
        parsed = parse_time_range_with_pad(goal)
        self.assertIsNotNone(parsed)
        start_ms, end_ms, pad_ms = parsed
        self.assertEqual(pad_ms, 0)
        self.assertEqual(start_ms, 7 * 60 * 1000 + 20 * 1000)
        self.assertEqual(end_ms, 8 * 60 * 1000 + 20 * 1000)
        prev, status = format_time_range_preview(goal, video_duration_ms=600_000)
        self.assertEqual(status, "ok")
        self.assertIn("07:20", prev)
        self.assertIn("08:20", prev)
        self.assertNotIn("前后各", prev)

    def test_no_time_returns_none(self) -> None:
        self.assertIsNone(_parse_time_range_ms("只要杀哥质问老师那段"))
        self.assertIsNone(resolve_time_range_with_pad("前后各留5秒", api_key=""))

    def test_llm_uses_four_arg_request_json(self) -> None:
        calls: list[tuple] = []

        def fake_request(url: str, method: str, headers: dict, body: dict | None = None) -> dict:
            calls.append((url, method, headers, body))
            return {
                "choices": [
                    {
                        "message": {
                            "content": '{"start_ms": 440000, "end_ms": 500000}',
                        }
                    }
                ]
            }

        tr = parse_time_range_via_llm(
            "从七分20秒到八分20秒",
            "sk-test",
            request_json_fn=fake_request,
        )
        self.assertEqual(tr, (440000, 500000))
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], CHAT_URL)
        self.assertEqual(calls[0][1], "POST")


if __name__ == "__main__":
    unittest.main()
