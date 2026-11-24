import unittest

from shixu import svg

TIMES = [f"2026-09-{i + 1:02d}" for i in range(20)]
VALUES = [3200.0 + i * 10 for i in range(20)]


class LineChartTest(unittest.TestCase):
    def test_has_polyline(self):
        chart = svg.line_chart(TIMES, VALUES)
        self.assertIn("<polyline", chart)
        self.assertIn("<svg", chart)
        self.assertTrue(chart.endswith("</svg>"))

    def test_marks_issue(self):
        issues = [{"kind": "spike", "index": 5, "value": 3400.0, "note": "x"}]
        chart = svg.line_chart(TIMES, VALUES, issues)
        self.assertIn("circle", chart)
        self.assertIn("#ff7b72", chart)

    def test_gap_drawn_as_line(self):
        issues = [{"kind": "gap", "index": 5, "value": None, "note": "x"}]
        chart = svg.line_chart(TIMES, VALUES, issues)
        self.assertIn("stroke-dasharray", chart)

    def test_missing_value_breaks_line(self):
        values = list(VALUES)
        values[10] = None
        chart = svg.line_chart(TIMES, values)
        self.assertEqual(chart.count("<polyline"), 2)

    def test_all_missing_returns_empty(self):
        chart = svg.line_chart(TIMES, [None] * len(TIMES))
        self.assertIn("<svg", chart)
        self.assertNotIn("polyline", chart)

    def test_flat_series_does_not_divide_by_zero(self):
        chart = svg.line_chart(TIMES, [100.0] * len(TIMES))
        self.assertIn("<polyline", chart)

    def test_title_escaped(self):
        chart = svg.line_chart(TIMES, VALUES, title="a < b & c")
        self.assertIn("a &lt; b &amp; c", chart)

    def test_time_labels(self):
        chart = svg.line_chart(TIMES, VALUES)
        self.assertIn("2026-09-01", chart)
        self.assertIn("2026-09-20", chart)

    def test_custom_size(self):
        chart = svg.line_chart(TIMES, VALUES, width=400, height=200)
        self.assertIn('width="400"', chart)
        self.assertIn('height="200"', chart)

    def test_no_scientific_notation(self):
        chart = svg.line_chart(TIMES, [1e-7 * i for i in range(20)])
        self.assertNotIn("1e-", chart)


if __name__ == "__main__":
    unittest.main()
