import unittest
from datetime import datetime, timedelta

from shixu import detect


def daily(values, start="2026-09-01"):
    base = datetime.strptime(start, "%Y-%m-%d")
    times = [(base + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(len(values))]
    dates = [base + timedelta(days=i) for i in range(len(values))]
    return {"times": times, "dates": dates, "columns": {"v": values}}


class HelperTest(unittest.TestCase):
    def test_median_even(self):
        self.assertEqual(detect._median([1, 2, 3, 4]), 2.5)

    def test_median_odd(self):
        self.assertEqual(detect._median([3, 1, 2]), 2)

    def test_median_empty(self):
        self.assertEqual(detect._median([]), 0.0)

    def test_mad(self):
        self.assertEqual(detect._mad([1, 2, 3, 4, 5], 3), 1)


class SpikeTest(unittest.TestCase):
    def test_finds_single_peak(self):
        values = [100.0] * 20 + [400.0] + [100.0] * 6
        out = detect.find_spikes(["d"] * len(values), values)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["kind"], "spike")
        self.assertEqual(out[0]["index"], 20)
        self.assertEqual(out[0]["value"], 400.0)

    def test_finds_drop(self):
        values = [100.0] * 20 + [10.0] + [100.0] * 6
        out = detect.find_spikes(["d"] * len(values), values)
        self.assertEqual(out[0]["kind"], "drop")

    def test_needs_enough_history(self):
        values = [100.0, 100.0, 500.0, 100.0]
        self.assertEqual(detect.find_spikes(["d"] * 4, values), [])

    def test_warmup_window_skipped(self):
        # 前 7 个点不给判，起步阶段 MAD 太小，硬判就会报假尖峰
        values = [3200.0, 3300.0, 3250.0, 3210.0, 3400.0, 7500.0] + [3200.0] * 10
        out = detect.find_spikes(["d"] * len(values), values)
        self.assertEqual([x["index"] for x in out], [])

    def test_flat_series_flags_outlier(self):
        values = [50.0] * 20 + [60.0] + [50.0] * 5
        out = detect.find_spikes(["d"] * len(values), values)
        self.assertEqual(len(out), 1)

    def test_ignores_missing_values(self):
        values = [100.0] * 10 + [None] + [100.0] * 10
        self.assertEqual(detect.find_spikes(["d"] * 21, values), [])

    def test_min_abs_filters_small_jumps(self):
        values = [1000.0] * 20 + [1010.0] + [1000.0] * 5
        self.assertEqual(detect.find_spikes(["d"] * 26, values, min_abs=50), [])

    def test_note_mentions_score(self):
        values = [100.0] * 20 + [400.0] + [100.0] * 6
        issue = detect.find_spikes(["d"] * 27, values)[0]
        self.assertIn("MAD", issue["note"])
        self.assertGreater(issue["deviation"], 0)


class ShiftTest(unittest.TestCase):
    def test_finds_step(self):
        values = [1000.0] * 20 + [800.0] * 20
        out = detect.find_shifts(["d"] * 40, values, window=5)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["index"], 20)
        self.assertEqual(out[0]["kind"], "shift")

    def test_backtracks_to_first_step_day(self):
        # 台阶前 3 天有个缓坡，真正下移的那天应该被回溯到
        values = [1000.0] * 18 + [990.0, 980.0] + [800.0] * 20
        out = detect.find_shifts(["d"] * 40, values, window=5)
        self.assertEqual(out[0]["index"], 20)

    def test_rejects_bounce(self):
        # 掉下去两天又弹回来：不是台阶，是波动
        values = [1000.0] * 20 + [600.0, 600.0] + [1000.0] * 18
        out = detect.find_shifts(["d"] * 40, values, window=5)
        self.assertEqual(out, [])

    def test_single_spike_does_not_become_shift(self):
        # 用均值判断时，窗口里一个 900 能把台阶判出来；中位数不会
        values = [3300.0] * 20 + [900.0] + [3300.0] * 19
        out = detect.find_shifts(["d"] * 40, values, window=7)
        self.assertEqual(out, [])

    def test_nms_keeps_one_per_step(self):
        values = [1000.0] * 20 + [500.0] * 20
        out = detect.find_shifts(["d"] * 40, values, window=6)
        self.assertEqual(len(out), 1)

    def test_ratio_threshold(self):
        values = [1000.0, 1000.0, 1010.0, 1020.0, 1030.0, 1040.0, 1050.0,
                  1060.0, 1070.0, 1080.0, 1090.0, 1100.0]
        self.assertEqual(detect.find_shifts(["d"] * 12, values, window=4, ratio=2.0), [])

    def test_note_has_both_levels(self):
        values = [1000.0] * 20 + [800.0] * 20
        issue = detect.find_shifts(["d"] * 40, values, window=5)[0]
        self.assertIn("1000.00", issue["note"])
        self.assertIn("800.00", issue["note"])


class GapAndMissingTest(unittest.TestCase):
    def test_detects_gap(self):
        values = [1.0] * 10
        times = [f"2026-09-{i + 1:02d}" for i in range(7)] + ["2026-09-12", "2026-09-13", "2026-09-14"]
        dates = [datetime(2026, 9, i + 1) for i in range(7)]
        dates += [datetime(2026, 9, 12), datetime(2026, 9, 13), datetime(2026, 9, 14)]
        out = detect.find_gaps(times, dates, values)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["index"], 7)

    def test_no_gap_in_daily_data(self):
        d = daily([1.0] * 10)
        self.assertEqual(detect.find_gaps(d["times"], d["dates"], d["columns"]["v"]), [])

    def test_hourly_data_no_false_gap(self):
        base = datetime(2026, 9, 1)
        dates = [base + timedelta(hours=i) for i in range(24)]
        times = [x.strftime("%Y-%m-%d %H:%M") for x in dates]
        self.assertEqual(detect.find_gaps(times, dates, [1.0] * 24), [])

    def test_missing_row(self):
        out = detect.find_missing(["a", "b", "c"], [1.0, None, 2.0])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["index"], 1)

    def test_no_missing(self):
        self.assertEqual(detect.find_missing(["a"], [1.0]), [])


class AnalyzeTest(unittest.TestCase):
    def test_merges_kinds(self):
        values = [3200.0] * 20 + [6200.0] + [3200.0] * 15
        issues = detect.analyze(daily(values), "v")
        kinds = {x["kind"] for x in issues}
        self.assertIn("spike", kinds)
        self.assertEqual(len([x for x in issues if x["index"] == 20]), 1)

    def test_spike_wins_over_shift_at_same_index(self):
        values = [1000.0] * 20 + [5000.0] + [1000.0] * 20
        issues = detect.analyze(daily(values), "v", window=14, shift_ratio=2.0)
        same = [x for x in issues if x["index"] == 20]
        self.assertEqual(len(same), 1)
        self.assertEqual(same[0]["kind"], "spike")

    def test_step_swallows_following_drops(self):
        # 台阶下移之后，附近那几天会被判成"骤降"，其实是台阶自己的回响
        values = [3300.0] * 30 + [2400.0] * 4 + [2500.0] * 20
        issues = detect.analyze(daily(values), "v", window=14, shift_ratio=2.0)
        drops = [x for x in issues if x["kind"] in ("spike", "drop")]
        self.assertEqual(drops, [])

    def test_sorted_by_severity(self):
        values = [3200.0] * 20 + [6200.0] + [3200.0] * 5 + [900.0] + [3200.0] * 10
        issues = detect.analyze(daily(values), "v")
        self.assertEqual(issues[0]["index"], 20)  # +28 MAD 比 -15 MAD 更狠

    def test_unknown_column(self):
        with self.assertRaises(KeyError):
            detect.analyze(daily([1.0] * 5), "nope")

    def test_all_missing_column(self):
        issues = detect.analyze(daily([None] * 5), "v")
        self.assertEqual({x["kind"] for x in issues}, {"missing"})

    def test_issue_shape(self):
        values = [3200.0] * 20 + [6200.0] + [3200.0] * 5
        issue = detect.analyze(daily(values), "v")[0]
        for key in ("kind", "index", "time", "value", "baseline", "deviation", "note"):
            self.assertIn(key, issue)


if __name__ == "__main__":
    unittest.main()
