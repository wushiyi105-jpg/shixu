import json
import os
import tempfile
import unittest

from shixu import store

CSV = "日期,日活\n2026-09-01,3200\n2026-09-02,3210\n"


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = store.connect(os.path.join(self.tmp.name, "t.db"))

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_add_and_list(self):
        did = store.add_dataset(self.conn, "日活", CSV, 2, ["日活"])
        items = store.list_datasets(self.conn)
        self.assertEqual(items[0]["id"], did)
        self.assertEqual(items[0]["columns"], ["日活"])
        self.assertEqual(items[0]["findings"], 0)

    def test_same_content_deduped(self):
        first = store.add_dataset(self.conn, "A", CSV, 2, ["日活"])
        second = store.add_dataset(self.conn, "B", CSV, 2, ["日活"])
        self.assertEqual(first, second)
        self.assertEqual(len(store.list_datasets(self.conn)), 1)

    def test_rename_on_duplicate(self):
        did = store.add_dataset(self.conn, "旧名字", CSV, 2, ["日活"])
        store.add_dataset(self.conn, "新名字", CSV, 2, ["日活"], note="补充")
        row = store.get_dataset(self.conn, did)
        self.assertEqual(row["name"], "新名字")
        self.assertEqual(row["note"], "补充")

    def test_get_missing(self):
        self.assertIsNone(store.get_dataset(self.conn, 999))

    def test_delete_removes_findings(self):
        did = store.add_dataset(self.conn, "A", CSV, 2, ["日活"])
        store.save_finding(self.conn, did, "日活", [], {}, [], "", [], {})
        store.delete_dataset(self.conn, did)
        self.assertEqual(store.stats(self.conn)["findings"], 0)
        self.assertEqual(store.stats(self.conn)["datasets"], 0)

    def test_save_and_get_finding(self):
        did = store.add_dataset(self.conn, "A", CSV, 2, ["日活"])
        issues = [{"kind": "spike", "index": 1, "time": "2026-09-02", "value": 3210.0,
                   "baseline": 3200.0, "deviation": 5.0, "note": "高 5 个 MAD"}]
        summary = {"n": 2, "min": 3200.0, "max": 3210.0, "mean": 3205.0, "median": 3205.0, "missing": 0}
        store.save_finding(self.conn, did, "日活", issues, summary,
                           [{"n": 1, "cause": "大促", "check": "看排期", "level": "high",
                              "unverified": [], "issue": issues[0]}],
                           "一句话", ["30"], {"window": 14})
        f = store.get_finding(self.conn, did, "日活")
        self.assertEqual(f["issues"][0]["kind"], "spike")
        self.assertEqual(f["summary"]["max"], 3210.0)
        self.assertEqual(f["explain"][0]["cause"], "大促")
        self.assertEqual(f["unverified"], ["30"])
        self.assertEqual(f["params"]["window"], 14)

    def test_rerun_overwrites_same_column(self):
        did = store.add_dataset(self.conn, "A", CSV, 2, ["日活"])
        store.save_finding(self.conn, did, "日活", [], {}, [], "", [], {})
        store.save_finding(self.conn, did, "日活", [{"kind": "gap"}], {}, [1], "", [], {})
        self.assertEqual(store.stats(self.conn)["findings"], 1)

    def test_two_columns_two_findings(self):
        did = store.add_dataset(self.conn, "A", CSV, 2, ["日活", "订单"])
        store.save_finding(self.conn, did, "日活", [], {}, [], "", [], {})
        store.save_finding(self.conn, did, "订单", [], {}, [], "", [], {})
        self.assertEqual(store.stats(self.conn)["findings"], 2)

    def test_stats_counts_issues(self):
        did = store.add_dataset(self.conn, "A", CSV, 2, ["日活"])
        store.save_finding(self.conn, did, "日活", [{"kind": "gap"}, {"kind": "spike"}], {}, [], "", [], {})
        self.assertEqual(store.stats(self.conn)["issues"], 2)

    def test_get_finding_missing(self):
        self.assertIsNone(store.get_finding(self.conn, 1, "日活"))

    def test_creates_parent_dir(self):
        path = os.path.join(self.tmp.name, "deep", "nested", "x.db")
        conn = store.connect(path)
        conn.close()
        self.assertTrue(os.path.isfile(path))

    def test_sha_is_stable(self):
        self.assertEqual(store.sha(CSV), store.sha(CSV))
        self.assertNotEqual(store.sha(CSV), store.sha(CSV + " "))


if __name__ == "__main__":
    unittest.main()
