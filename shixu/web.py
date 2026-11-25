"""Web：http.server 页面，曲线用内联 SVG 画（不引图表库）。

左边数据集和指标，右边一张曲线图 + 异常清单。图上每个异常都有圈：红的是尖峰，
黄的是骤降，蓝的是台阶，灰虚线是断档或缺失。
"""

from __future__ import annotations

import json
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import detect, explain, llm, store, svg
from . import series as S

PAGE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>时序 · 异常排查</title>
<style>
*{box-sizing:border-box}
body{margin:0;background:#0b0f14;color:#c9d1d9;font:15px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
header{padding:16px 24px;border-bottom:1px solid #21262d;display:flex;align-items:baseline;gap:12px}
h1{margin:0;font-size:18px;color:#7ee787;font-weight:600}
.sub{color:#8b949e;font-size:13px}
main{display:grid;grid-template-columns:300px 1fr;min-height:calc(100vh - 60px)}
aside{border-right:1px solid #21262d;padding:16px;overflow:auto}
section{padding:20px 24px}
textarea{width:100%;height:110px;background:#161b22;color:#c9d1d9;border:1px solid #30363d;border-radius:8px;padding:8px;font:13px ui-monospace,Consolas,monospace}
input{width:100%;background:#161b22;color:#c9d1d9;border:1px solid #30363d;border-radius:8px;padding:7px 10px;font:14px inherit;margin-bottom:8px}
input.small{width:90px}
button{background:#238636;color:#fff;border:0;border-radius:6px;padding:7px 12px;font:14px inherit;cursor:pointer}
button.ghost{background:#21262d;color:#c9d1d9}
.item{padding:10px;border:1px solid #21262d;border-radius:8px;margin-bottom:8px;background:#0d1117}
.item .t{font-weight:600}
.item .m{color:#8b949e;font-size:12px;margin:4px 0 8px}
.col{display:inline-block;background:#1c2f3d;color:#79c0ff;border-radius:10px;padding:1px 9px;font-size:12px;margin:0 6px 6px 0;cursor:pointer}
.issue{border-left:3px solid #30363d;padding:6px 0 6px 12px;margin:12px 0}
.spike{border-color:#ff7b72}.drop{border-color:#e3b341}.shift{border-color:#79c0ff}.gap,.missing{border-color:#8b949e}
.k{color:#8b949e;font-size:13px}
.warn{color:#e3b341;font-size:13px}
.empty{color:#8b949e}
</style></head><body>
<header><h1>时序</h1><span class="sub">算法找异常点，模型解释原因，数字必须对得上数据</span></header>
<main>
<aside>
  <input id="name" placeholder="数据集名字，比如：日活">
  <input id="note" placeholder="业务背景（会带进解释里）">
  <textarea id="csv" placeholder="把 CSV 粘进来，第一列时间，其余列指标"></textarea>
  <div style="margin-top:8px;display:flex;gap:8px">
    <button id="add">导入</button>
  </div>
  <div id="list" style="margin-top:18px"></div>
</aside>
<section id="detail"><p class="empty">左边选一个数据集。</p></section>
</main>
<script>
const $ = s => document.querySelector(s);
const esc = s => (s||'').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const LV = {high:'高', medium:'中', low:'低'};
const KD = {spike:'尖峰', drop:'骤降', shift:'台阶', gap:'断档', missing:'缺失'};
let current = null;

async function loadList(){
  const r = await fetch('/api/datasets');
  const items = (await r.json()).items;
  $('#list').innerHTML = items.length ? items.map(d =>
    `<div class="item">
       <div class="t">${esc(d.name)}</div>
       <div class="m">${d.rows} 行 · ${d.findings} 次检测</div>
       <div>${d.columns.map(c => `<span class="col" data-id="${d.id}" data-col="${esc(c)}">${esc(c)}</span>`).join('')}</div>
     </div>`).join('') : '<p class="empty">还没有数据集。</p>';
  document.querySelectorAll('.col').forEach(el => el.onclick = () => show(+el.dataset.id, el.dataset.col));
}

async function show(id, column){
  current = {id, column};
  const r = await fetch(`/api/dataset?id=${id}&column=${encodeURIComponent(column)}`);
  const d = await r.json();
  if(d.error){ $('#detail').innerHTML = `<p class="empty">${esc(d.error)}</p>`; return; }
  let html = `<div style="display:flex;gap:8px;align-items:center;margin-bottom:12px">
      <b style="font-size:16px">${esc(d.name)} · ${esc(column)}</b>
      <button id="run">重新检测</button>
      <button id="noModel" class="ghost">只跑算法</button>
      <span class="k" id="status">${d.finding ? '检测于 ' + esc(d.finding.created_at) : '还没检测过'}</span>
    </div>`;
  html += `<div id="chart" style="margin-bottom:16px">${d.chart || ''}</div>`;
  if(d.finding){
    if(d.finding.takeaway) html += `<p style="color:#79c0ff">${esc(d.finding.takeaway)}</p>`;
    html += d.finding.issues.map((i, n) => {
      const e = (d.finding.explain || []).find(x => x.n === n + 1);
      return `<div class="issue ${i.kind}">
        <b>${KD[i.kind] || i.kind} · ${esc(i.time)}</b>
        <span class="k">${i.value !== null ? '值 ' + i.value : ''}${i.baseline !== null ? '（基线 ' + i.baseline + '）' : ''}</span>
        <div class="k">${esc(i.note)}</div>
        ${e ? `<div>可能原因：${esc(e.cause)}</div><div>先查什么：${esc(e.check)} <span class="k">（把握 ${LV[e.level]||e.level}）</span></div>` : ''}
        ${e && e.unverified && e.unverified.length ? `<div class="warn">⚠ 这句里的数字对不上数据：${esc(e.unverified.join(', '))}</div>` : ''}
      </div>`;
    }).join('') || '<p class="empty">没发现异常。</p>';
  } else {
    html += `<p class="empty">这个指标还没跑过检测。</p>`;
  }
  $('#detail').innerHTML = html;
  $('#run').onclick = () => run(false);
  $('#noModel').onclick = () => run(true);
}

async function run(noModel){
  $('#run').disabled = true; $('#noModel').disabled = true;
  $('#status').textContent = noModel ? '跑着（不调模型）…' : '跑着…（要调模型，慢一点）';
  const r = await fetch('/api/detect', {method:'POST', body: JSON.stringify({
    id: current.id, column: current.column, no_model: noModel
  })});
  const d = await r.json();
  if(d.error) alert(d.error);
  loadList(); show(current.id, current.column);
}

$('#add').onclick = async () => {
  const csv = $('#csv').value.trim();
  if(!csv) return alert('先粘一段 CSV');
  const r = await fetch('/api/add', {method:'POST', body: JSON.stringify({
    name: $('#name').value, note: $('#note').value, csv
  })});
  const d = await r.json();
  if(d.error) return alert(d.error);
  $('#csv').value = '';
  await loadList();
  if(d.columns && d.columns[0]) show(d.id, d.columns[0]);
};
loadList();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    conn = None

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return {}

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        if parsed.path == "/":
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            return
        if parsed.path == "/api/datasets":
            self._json({"items": store.list_datasets(self.conn)})
            return
        if parsed.path == "/api/dataset":
            try:
                did = int(qs.get("id", ["0"])[0])
            except ValueError:
                self._json({"error": "id 不合法"}, 400)
                return
            row = store.get_dataset(self.conn, did)
            if not row:
                self._json({"error": "没有这个数据集"}, 404)
                return
            column = qs.get("column", [row["columns"][0] if row["columns"] else ""])[0]
            try:
                data = S.read_csv(row["csv"])
            except S.CsvError as e:
                self._json({"error": str(e)}, 500)
                return
            if column not in data["columns"]:
                self._json({"error": f"没有这一列：{column}"}, 400)
                return
            finding = store.get_finding(self.conn, did, column)
            issues = finding["issues"] if finding else detect.analyze(data, column)
            self._json({
                "id": did, "name": row["name"], "column": column,
                "rows": row["rows"], "note": row["note"],
                "finding": finding,
                "chart": svg.line_chart(data["times"], data["columns"][column], issues,
                                        title=f"{row['name']} · {column}", height=300),
            })
            return
        if parsed.path == "/api/chart":
            try:
                did = int(qs.get("id", ["0"])[0])
            except ValueError:
                self._json({"error": "id 不合法"}, 400)
                return
            row = store.get_dataset(self.conn, did)
            column = qs.get("column", [""])[0]
            if not row or column not in row["columns"]:
                self._json({"error": "参数不对"}, 400)
                return
            data = S.read_csv(row["csv"])
            finding = store.get_finding(self.conn, did, column)
            issues = finding["issues"] if finding else detect.analyze(data, column)
            self._send(200, svg.line_chart(data["times"], data["columns"][column], issues).encode("utf-8"),
                       "image/svg+xml; charset=utf-8")
            return
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        body = self._body()

        if parsed.path == "/api/add":
            csv_text = (body.get("csv") or "").strip()
            if not csv_text:
                self._json({"error": "CSV 是空的"}, 400)
                return
            try:
                data = S.read_csv(csv_text)
            except S.CsvError as e:
                self._json({"error": str(e)}, 400)
                return
            name = (body.get("name") or "").strip() or "未命名数据集"
            did = store.add_dataset(self.conn, name, csv_text, data["rows"], list(data["columns"]),
                                    note=(body.get("note") or "").strip())
            self._json({"id": did, "columns": list(data["columns"])})
            return

        if parsed.path == "/api/detect":
            try:
                did = int(body.get("id"))
            except (TypeError, ValueError):
                self._json({"error": "id 不合法"}, 400)
                return
            row = store.get_dataset(self.conn, did)
            if not row:
                self._json({"error": "没有这个数据集"}, 404)
                return
            column = body.get("column") or (row["columns"][0] if row["columns"] else "")
            if column not in row["columns"]:
                self._json({"error": f"没有这一列：{column}"}, 400)
                return
            data = S.read_csv(row["csv"])
            issues = detect.analyze(data, column)
            summary = S.summarize(data["columns"][column])
            explained, takeaway, unverified, error = [], "", [], ""
            if issues and not body.get("no_model"):
                try:
                    result = explain.explain(column, row["note"], summary, issues, config=llm.default_config())
                    explained, takeaway, unverified, error = (
                        result["items"], result["summary"], result["unverified"], result["error"]
                    )
                except Exception as e:  # noqa: BLE001
                    error = repr(e)
            store.save_finding(self.conn, did, column, issues, summary, explained, takeaway, unverified,
                               {"window": 14, "z": 3.5, "shift_ratio": 2.0})
            self._json({"ok": True, "issues": len(issues), "error": error})
            return

        if parsed.path == "/api/rm":
            try:
                did = int(body.get("id"))
            except (TypeError, ValueError):
                self._json({"error": "id 不合法"}, 400)
                return
            store.delete_dataset(self.conn, did)
            self._json({"ok": True})
            return

        self._json({"error": "not found"}, 404)


def make_server(conn, host: str = "127.0.0.1", port: int = 8770) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"conn": conn})
    return ThreadingHTTPServer((host, port), handler)


def serve(conn, host: str = "127.0.0.1", port: int = 8770):
    httpd = make_server(conn, host, port)
    print(f"时序已起：http://{host}:{port}  （Ctrl+C 退出）")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n再见。")
    finally:
        httpd.server_close()
