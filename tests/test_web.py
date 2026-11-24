import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from urllib.parse import quote

from shixu import store, web


class WebTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.conn = store.connect(os.path.join(cls.tmp.name, "web.db"))
        cls.csv = "日期,日活\n" + "".join(f"2026-09-{i + 1:02d},{3200 + i}\n" for i in range(20))
        cls.id = store.add_dataset(cls.conn, "网页样本", cls.csv, 20, ["日活"], note="测试")
        cls.httpd = web.make_server(cls.conn, port=0)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.conn.close()
        cls.tmp.cleanup()

    def _get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=5) as r:
            return r.status, r.read().decode("utf-8")

    def _post(self, path, payload):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode("utf-8"))

    def test_index_page(self):
        status, body = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn("时序", body)
        self.assertIn("/api/datasets", body)

    def test_list_api(self):
        status, body = self._get("/api/datasets")
        self.assertEqual(status, 200)
        items = json.loads(body)["items"]
        self.assertTrue(any(x["name"] == "网页样本" for x in items))

    def test_dataset_api_has_chart(self):
        status, body = self._get(f"/api/dataset?id={self.id}&column={quote('日活')}")
        data = json.loads(body)
        self.assertIn("<svg", data["chart"])
        self.assertEqual(data["column"], "日活")

    def test_dataset_bad_id(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/api/dataset?id=9999")
        self.assertEqual(ctx.exception.code, 404)

    def test_chart_endpoint_returns_svg(self):
        with urllib.request.urlopen(
            f"http://127.0.0.1:{self.port}/api/chart?id={self.id}&column={quote('日活')}", timeout=5
        ) as r:
            self.assertIn("svg", r.headers.get("Content-Type"))
            self.assertIn("<svg", r.read().decode("utf-8"))

    def test_add_endpoint(self):
        csv = "日期,日活\n2026-09-01,100\n2026-09-02,200\n"
        status, data = self._post("/api/add", {"name": "接口导入", "csv": csv})
        self.assertEqual(data["columns"], ["日活"])

    def test_add_empty_csv(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._post("/api/add", {"name": "空", "csv": ""})
        self.assertEqual(ctx.exception.code, 400)

    def test_detect_no_model(self):
        status, data = self._post("/api/detect", {"id": self.id, "column": "日活", "no_model": True})
        self.assertTrue(data["ok"])
        self.assertEqual(data["error"], "")
        f = store.get_finding(self.conn, self.id, "日活")
        self.assertIsNotNone(f)

    def test_rm_endpoint(self):
        csv = "日期,日活\n2026-09-01,100\n2026-09-02,200\n"
        _, data = self._post("/api/add", {"name": "待删", "csv": csv})
        _, out = self._post("/api/rm", {"id": data["id"]})
        self.assertTrue(out["ok"])

    def test_unknown_route(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/api/nope")
        self.assertEqual(ctx.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
