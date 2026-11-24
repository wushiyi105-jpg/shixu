import unittest

from shixu import explain

ISSUES = [
    {"kind": "spike", "index": 20, "time": "2026-09-21", "value": 6200.0,
     "baseline": 3277.5, "deviation": 28.6, "note": "比前 14 个点的中位数高 28.6 个 MAD"},
    {"kind": "gap", "index": 23, "time": "2026-10-24", "value": None,
     "baseline": None, "deviation": 4.0, "note": "距上一个点隔了 4.0 个正常周期（正常约 24.0 小时）"},
]
SUMMARY = {"n": 56, "missing": 1, "min": 900.0, "max": 6200.0, "mean": 3300.0, "median": 3287.5}


class AllowedNumbersTest(unittest.TestCase):
    def test_includes_values(self):
        allowed = explain.allowed_numbers(ISSUES, SUMMARY)
        self.assertIn(6200.0, allowed)
        self.assertIn(3277.5, allowed)

    def test_includes_summary(self):
        allowed = explain.allowed_numbers(ISSUES, SUMMARY)
        self.assertIn(900.0, allowed)

    def test_includes_note_numbers(self):
        allowed = explain.allowed_numbers(ISSUES, SUMMARY)
        self.assertIn(24.0, allowed)
        self.assertIn(4.0, allowed)

    def test_includes_count_and_ordinals(self):
        allowed = explain.allowed_numbers(ISSUES, SUMMARY)
        self.assertIn(2.0, allowed)

    def test_does_not_leak_random(self):
        allowed = explain.allowed_numbers(ISSUES, SUMMARY)
        self.assertNotIn(37.0, allowed)


class VerifyNumbersTest(unittest.TestCase):
    def setUp(self):
        self.allowed = explain.allowed_numbers(ISSUES, SUMMARY)

    def test_good_number_passes(self):
        self.assertEqual(explain.verify_numbers("当天冲到 6200", self.allowed), [])

    def test_fabricated_percent_caught(self):
        self.assertIn("30", explain.verify_numbers("大概涨了 30%", self.allowed))

    def test_fabricated_amount_caught(self):
        self.assertIn("5000", explain.verify_numbers("估计影响 5000 单", self.allowed))

    def test_date_is_not_data(self):
        # 复述日期不该被当成编造数值，否则每条解释都要挂一串假警告
        for text in ("9 月 21 日冲高", "2026-09-21 那天", "9/21 冲高", "9-21 冲高", "10月3日掉下来"):
            self.assertEqual(explain.verify_numbers(text, self.allowed), [], text)

    def test_small_integer_is_ordinal(self):
        self.assertEqual(explain.verify_numbers("第 2 点：看投放", self.allowed), [])

    def test_tolerance_for_rounding(self):
        # 6200 写成 6204 算四舍五入，不算编造
        self.assertEqual(explain.verify_numbers("约 6204", self.allowed), [])

    def test_empty_text(self):
        self.assertEqual(explain.verify_numbers("", self.allowed), [])
        self.assertEqual(explain.verify_numbers(None, self.allowed), [])


class ExplainTest(unittest.TestCase):
    def _fake(self, payload):
        def fake_chat(messages, config=None, **kwargs):
            self.seen = messages
            return payload
        return fake_chat

    def test_parses_items(self):
        payload = ('{"items":[{"n":1,"cause":"大促","check":"看投放排期","level":"high"}],'
                   '"summary":"一件事"}')
        original = explain.llm.chat
        explain.llm.chat = self._fake(payload)
        try:
            out = explain.explain("日活", "做过大促", SUMMARY, ISSUES)
        finally:
            explain.llm.chat = original
        self.assertEqual(out["error"], "")
        self.assertEqual(out["summary"], "一件事")
        self.assertEqual(out["items"][0]["cause"], "大促")
        self.assertEqual(out["items"][0]["level"], "high")
        self.assertEqual(out["items"][0]["issue"]["index"], 20)

    def test_prompt_carries_business_note(self):
        payload = '{"items":[],"summary":""}'
        original = explain.llm.chat
        explain.llm.chat = self._fake(payload)
        try:
            explain.explain("日活", "月底上了新版首页", SUMMARY, ISSUES)
        finally:
            explain.llm.chat = original
        joined = " ".join(m["content"] for m in self.seen)
        self.assertIn("月底上了新版首页", joined)
        self.assertIn("日活", joined)
        self.assertNotIn("不要重新计算", " ".join(m["content"] for m in self.seen if m["role"] == "user"))

    def test_marks_unverified_numbers(self):
        payload = '{"items":[{"n":1,"cause":"涨了 30% 才这样","check":"看投放","level":"high"}],"summary":""}'
        original = explain.llm.chat
        explain.llm.chat = self._fake(payload)
        try:
            out = explain.explain("日活", "", SUMMARY, ISSUES)
        finally:
            explain.llm.chat = original
        self.assertIn("30", out["items"][0]["unverified"])
        self.assertIn("30", out["unverified"])

    def test_bad_n_skipped(self):
        payload = '{"items":[{"n":9,"cause":"x","check":"y","level":"high"}],"summary":""}'
        original = explain.llm.chat
        explain.llm.chat = self._fake(payload)
        try:
            out = explain.explain("日活", "", SUMMARY, ISSUES)
        finally:
            explain.llm.chat = original
        self.assertEqual(out["items"], [])

    def test_llm_failure_returns_error(self):
        def boom(*a, **k):
            raise explain.llm.LLMError("接口 429")
        original = explain.llm.chat
        explain.llm.chat = boom
        try:
            out = explain.explain("日活", "", SUMMARY, ISSUES)
        finally:
            explain.llm.chat = original
        self.assertIn("429", out["error"])
        self.assertEqual(out["items"], [])

    def test_limit_caps_items(self):
        many = [dict(ISSUES[0], index=i) for i in range(12)]
        payload = '{"items":[],"summary":""}'
        original = explain.llm.chat
        explain.llm.chat = self._fake(payload)
        try:
            explain.explain("日活", "", SUMMARY, many, limit=3)
        finally:
            explain.llm.chat = original
        user_text = [m["content"] for m in self.seen if m["role"] == "user"][0]
        self.assertIn("共 12 条", user_text)
        self.assertIn("前 3 条", user_text)

    def test_bad_level_defaults_medium(self):
        payload = '{"items":[{"n":1,"cause":"x","check":"y","level":"确定"}],"summary":""}'
        original = explain.llm.chat
        explain.llm.chat = self._fake(payload)
        try:
            out = explain.explain("日活", "", SUMMARY, ISSUES)
        finally:
            explain.llm.chat = original
        self.assertEqual(out["items"][0]["level"], "medium")


if __name__ == "__main__":
    unittest.main()
