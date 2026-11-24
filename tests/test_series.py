import unittest

from shixu import series as S


class ParseTimeTest(unittest.TestCase):
    def test_iso_date(self):
        self.assertEqual(S.parse_time("2026-09-21").strftime("%Y-%m-%d"), "2026-09-21")

    def test_iso_with_time(self):
        dt = S.parse_time("2026-09-21 08:30:00")
        self.assertEqual((dt.hour, dt.minute), (8, 30))

    def test_slash_format(self):
        self.assertEqual(S.parse_time("2026/09/21").year, 2026)

    def test_compact(self):
        self.assertEqual(S.parse_time("20260921").day, 21)

    def test_us_style(self):
        self.assertEqual(S.parse_time("09/21/2026").month, 9)

    def test_timezone_suffix(self):
        dt = S.parse_time("2026-09-21T00:30:00Z")
        self.assertEqual(dt.hour, 0)

    def test_garbage(self):
        self.assertIsNone(S.parse_time("上周三"))

    def test_empty(self):
        self.assertIsNone(S.parse_time(""))
        self.assertIsNone(S.parse_time(None))


class ParseNumberTest(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(S.parse_number("1234"), 1234.0)

    def test_thousand_separator(self):
        self.assertEqual(S.parse_number("3,168.5"), 3168.5)

    def test_currency_and_percent(self):
        self.assertEqual(S.parse_number("￥12.5"), 12.5)
        self.assertEqual(S.parse_number("12.5%"), 12.5)

    def test_negative(self):
        self.assertEqual(S.parse_number("-40"), -40.0)

    def test_missing_tokens(self):
        for token in ("", "-", "NA", "N/A", "nan", "NULL", "—"):
            self.assertIsNone(S.parse_number(token), token)

    def test_not_a_number(self):
        self.assertIsNone(S.parse_number("总计"))

    def test_none_input(self):
        self.assertIsNone(S.parse_number(None))


CSV_BASIC = """日期,日活,备注
2026-09-03,3200,正常
2026-09-01,3100,正常
2026-09-02,,缺
"""


class ReadCsvTest(unittest.TestCase):
    def test_rows_and_columns(self):
        data = S.read_csv(CSV_BASIC)
        self.assertEqual(data["rows"], 3)
        self.assertEqual(list(data["columns"]), ["日活"])

    def test_sorts_by_time(self):
        data = S.read_csv(CSV_BASIC)
        self.assertEqual(data["times"], ["2026-09-01", "2026-09-02", "2026-09-03"])
        self.assertEqual(data["columns"]["日活"], [3100.0, None, 3200.0])

    def test_skips_text_column(self):
        data = S.read_csv(CSV_BASIC)
        self.assertEqual(data["skipped"], ["备注"])

    def test_bom_stripped(self):
        data = S.read_csv("\ufeff时间,值\n2026-09-01,1\n2026-09-02,2\n")
        self.assertEqual(data["times"][0], "2026-09-01")

    def test_column_with_half_numeric_kept(self):
        text = "t,a\n2026-09-01,10\n2026-09-02,x\n2026-09-03,30\n2026-09-04,y\n"
        data = S.read_csv(text)
        self.assertIn("a", data["columns"])

    def test_no_metric_raises(self):
        with self.assertRaises(S.CsvError):
            S.read_csv("t,label\n2026-09-01,甲\n2026-09-02,乙\n")

    def test_single_row_raises(self):
        with self.assertRaises(S.CsvError):
            S.read_csv("日期,日活\n")

    def test_single_column_raises(self):
        with self.assertRaises(S.CsvError):
            S.read_csv("日期\n2026-09-01\n2026-09-02\n")

    def test_blank_lines_ignored(self):
        data = S.read_csv("t,v\n2026-09-01,1\n\n2026-09-02,2\n\n")
        self.assertEqual(data["rows"], 2)


class IntervalTest(unittest.TestCase):
    def test_daily(self):
        data = S.read_csv("t,v\n2026-09-01,1\n2026-09-02,2\n2026-09-04,3\n")
        self.assertEqual(S.typical_interval(data["dates"]), 86400)

    def test_median_ignores_one_gap(self):
        data = S.read_csv("t,v\n2026-09-01,1\n2026-09-02,2\n2026-09-03,3\n2026-09-08,4\n")
        self.assertEqual(S.typical_interval(data["dates"]), 86400)

    def test_too_few_points(self):
        data = S.read_csv("t,v\n2026-09-01,1\n")
        self.assertIsNone(S.typical_interval(data["dates"]))

    def test_unparseable_times(self):
        self.assertIsNone(S.typical_interval([None, None]))


class SummarizeTest(unittest.TestCase):
    def test_basic(self):
        s = S.summarize([1, 2, 3, 4])
        self.assertEqual((s["n"], s["min"], s["max"]), (4, 1, 4))
        self.assertEqual(s["median"], 2.5)

    def test_counts_missing(self):
        s = S.summarize([1, None, 3, None])
        self.assertEqual((s["n"], s["missing"]), (2, 2))

    def test_all_missing(self):
        s = S.summarize([None, None])
        self.assertEqual(s["n"], 0)
        self.assertIsNone(s["min"])

    def test_odd_median(self):
        self.assertEqual(S.summarize([5, 1, 9])["median"], 5)


if __name__ == "__main__":
    unittest.main()
