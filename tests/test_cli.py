import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout

from shixu import cli

CSV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples", "daily-active.csv")


def run(argv, db):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(["--db", db] + argv)
    return code, buf.getvalue()


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "cli.db")

    def tearDown(self):
        self.tmp.cleanup()

    @unittest.skipUnless(os.path.isfile(CSV_PATH), "缺少样例 CSV")
    def test_add_then_list(self):
        code, out = run(["add", CSV_PATH, "--name", "日活"], self.db)
        self.assertEqual(code, 0)
        self.assertIn("电商日活" if "电商" in out else "日活", out)
        code, out = run(["list"], self.db)
        self.assertIn("日活", out)

    def test_list_empty(self):
        code, out = run(["list"], self.db)
        self.assertEqual(code, 0)
        self.assertIn("还没有数据集", out)

    def test_add_missing_file(self):
        code, out = run(["add", "不存在.csv"], self.db)
        self.assertEqual(code, 0)  # 单个文件失败不中断整批
        self.assertIn("找不到文件", out)

    def test_detect_no_model(self):
        csv = "日期,日活\n" + "".join(
            f"2026-09-{i + 1:02d},3200\n" for i in range(20)
        ) + "2026-09-21,6200\n" + "".join(f"2026-09-{i + 22:02d},3200\n" for i in range(10))
        path = os.path.join(self.tmp.name, "x.csv")
        with open(path, "w", encoding="utf-8") as f:
            f.write(csv)
        run(["add", path, "--name", "x"], self.db)
        code, out = run(["detect", "1", "--no-model"], self.db)
        self.assertEqual(code, 0)
        self.assertIn("尖峰", out)

    def test_detect_json(self):
        path = os.path.join(self.tmp.name, "y.csv")
        with open(path, "w", encoding="utf-8") as f:
            f.write("日期,日活\n2026-09-01,100\n2026-09-02,100\n2026-09-03,900\n"
                    "2026-09-04,100\n2026-09-05,100\n2026-09-06,100\n")
        run(["add", path], self.db)
        code, out = run(["detect", "1", "--no-model", "--json"], self.db)
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["columns"][0]["issues"], [])

    def test_detect_bad_id(self):
        code, out = run(["detect", "99", "--no-model"], self.db)
        self.assertEqual(code, 1)
        self.assertIn("没有 id=99", out)

    def test_detect_bad_column(self):
        path = os.path.join(self.tmp.name, "z.csv")
        with open(path, "w", encoding="utf-8") as f:
            f.write("日期,日活\n2026-09-01,100\n2026-09-02,200\n")
        run(["add", path], self.db)
        code, out = run(["detect", "1", "--column", "订单"], self.db)
        self.assertEqual(code, 1)
        self.assertIn("没有这一列", out)

    def test_show(self):
        path = os.path.join(self.tmp.name, "s.csv")
        with open(path, "w", encoding="utf-8") as f:
            f.write("日期,日活\n2026-09-01,100\n2026-09-02,200\n")
        run(["add", path, "--name", "小样本"], self.db)
        code, out = run(["show", "1"], self.db)
        self.assertEqual(code, 0)
        self.assertIn("小样本", out)
        self.assertIn("还没检测", out)

    def test_svg_written(self):
        path = os.path.join(self.tmp.name, "g.csv")
        with open(path, "w", encoding="utf-8") as f:
            f.write("日期,日活\n" + "".join(f"2026-09-{i + 1:02d},{3000 + i}\n" for i in range(12)))
        run(["add", path], self.db)
        out_svg = os.path.join(self.tmp.name, "out.svg")
        code, out = run(["svg", "1", "--column", "日活", "--out", out_svg], self.db)
        self.assertEqual(code, 0)
        self.assertTrue(os.path.isfile(out_svg))
        with open(out_svg, encoding="utf-8") as f:
            self.assertIn("<svg", f.read())

    def test_rm_missing(self):
        code, out = run(["rm", "42"], self.db)
        self.assertEqual(code, 1)
        self.assertIn("没有 id=42", out)

    def test_rm_existing(self):
        path = os.path.join(self.tmp.name, "r.csv")
        with open(path, "w", encoding="utf-8") as f:
            f.write("日期,日活\n2026-09-01,100\n2026-09-02,200\n")
        run(["add", path], self.db)
        code, out = run(["rm", "1"], self.db)
        self.assertEqual(code, 0)
        self.assertIn("已删除", out)

    def test_stats(self):
        code, out = run(["stats"], self.db)
        self.assertEqual(code, 0)
        self.assertIn("datasets", out)

    def test_markdown_report(self):
        path = os.path.join(self.tmp.name, "m.csv")
        with open(path, "w", encoding="utf-8") as f:
            f.write("日期,日活\n" + "".join(f"2026-09-{i + 1:02d},3200\n" for i in range(20))
                    + "2026-09-21,6200\n")
        run(["add", path, "--name", "报告样本", "--note", "测试背景"], self.db)
        out_md = os.path.join(self.tmp.name, "deep", "r.md")
        code, out = run(["detect", "1", "--no-model", "--out", out_md], self.db)
        self.assertEqual(code, 0)
        with open(out_md, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("报告样本", text)
        self.assertIn("测试背景", text)


if __name__ == "__main__":
    unittest.main()
