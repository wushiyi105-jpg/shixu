"""SQLite：导入的数据集、检测结果、模型解释。

数据集按内容哈希去重，指标名存成 JSON。检测结果每次覆盖（同一数据集只留最新一次），
因为阈值改了重跑一遍是常事，留一堆旧结果反而不知道该看哪份。
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from datetime import datetime

_LOCK = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS datasets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    sha TEXT NOT NULL,
    rows INTEGER NOT NULL,
    columns TEXT NOT NULL,
    csv TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_ds_sha ON datasets(sha);
CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER NOT NULL,
    column_name TEXT NOT NULL,
    issues TEXT NOT NULL,
    summary TEXT NOT NULL,
    explain TEXT NOT NULL DEFAULT '[]',
    takeaway TEXT NOT NULL DEFAULT '',
    unverified TEXT NOT NULL DEFAULT '[]',
    params TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_finding_ds ON findings(dataset_id);
"""


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def connect(path: str = "data/shixu.db") -> sqlite3.Connection:
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def add_dataset(conn, name: str, csv_text: str, rows: int, columns: list[str], note: str = "") -> int:
    h = sha(csv_text)
    with _LOCK:
        row = conn.execute("SELECT id FROM datasets WHERE sha=?", (h,)).fetchone()
        if row:
            conn.execute("UPDATE datasets SET name=?, note=? WHERE id=?", (name, note, row["id"]))
            conn.commit()
            return row["id"]
        cur = conn.execute(
            "INSERT INTO datasets(name, sha, rows, columns, csv, note, created_at) VALUES (?,?,?,?,?,?,?)",
            (name, h, rows, json.dumps(columns, ensure_ascii=False), csv_text, note, now()),
        )
        conn.commit()
        return cur.lastrowid


def list_datasets(conn) -> list[dict]:
    rows = conn.execute(
        """SELECT d.id, d.name, d.rows, d.columns, d.note, d.created_at,
                  (SELECT COUNT(*) FROM findings f WHERE f.dataset_id=d.id) findings
           FROM datasets d ORDER BY d.id DESC"""
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["columns"] = json.loads(d["columns"] or "[]")
        out.append(d)
    return out


def get_dataset(conn, dataset_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM datasets WHERE id=?", (dataset_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["columns"] = json.loads(d["columns"] or "[]")
    return d


def delete_dataset(conn, dataset_id: int) -> None:
    with _LOCK:
        conn.execute("DELETE FROM findings WHERE dataset_id=?", (dataset_id,))
        conn.execute("DELETE FROM datasets WHERE id=?", (dataset_id,))
        conn.commit()


def save_finding(conn, dataset_id: int, column_name: str, issues: list[dict], summary: dict,
                 explained: list[dict], takeaway: str, unverified: list[str], params: dict) -> int:
    with _LOCK:
        conn.execute(
            "DELETE FROM findings WHERE dataset_id=? AND column_name=?", (dataset_id, column_name)
        )
        cur = conn.execute(
            """INSERT INTO findings(dataset_id, column_name, issues, summary, explain, takeaway,
                                    unverified, params, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                dataset_id, column_name,
                json.dumps(issues, ensure_ascii=False),
                json.dumps(summary, ensure_ascii=False),
                json.dumps(explained, ensure_ascii=False),
                takeaway,
                json.dumps(unverified, ensure_ascii=False),
                json.dumps(params, ensure_ascii=False),
                now(),
            ),
        )
        conn.commit()
        return cur.lastrowid


def get_finding(conn, dataset_id: int, column_name: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM findings WHERE dataset_id=? AND column_name=? ORDER BY id DESC LIMIT 1",
        (dataset_id, column_name),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["summary"] = json.loads(d["summary"] or "{}")
    for key in ("issues", "explain", "unverified", "params"):
        d[key] = json.loads(d[key] or "[]")
    return d


def stats(conn) -> dict:
    ds = conn.execute("SELECT COUNT(*) n FROM datasets").fetchone()["n"]
    f = conn.execute("SELECT COUNT(*) n FROM findings").fetchone()["n"]
    # 不用 SQL 的 json_array_length：老版本 SQLite 没编 JSON1，跑起来直接报函数不存在
    total_issues = 0
    for row in conn.execute("SELECT issues FROM findings").fetchall():
        try:
            total_issues += len(json.loads(row["issues"] or "[]"))
        except json.JSONDecodeError:
            continue
    return {"datasets": ds, "findings": f, "issues": total_issues}
