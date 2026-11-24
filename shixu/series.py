"""读 CSV，把一列时间 + 若干列数值整理成能算的序列。

不做复杂的类型推断：第一列当时间，其余列能转成数字的就是指标，转不了的整列跳过
并记一笔。宁可少读一列，也不要读错一列。
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime

_TIME_FORMATS = [
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d", "%Y/%m/%d %H:%M",
    "%Y%m%d", "%Y-%m", "%m/%d/%Y", "%d/%m/%Y",
]

_NUM_CLEAN = re.compile(r"[,\s￥$€£%]")


class CsvError(Exception):
    """CSV 读不了。"""


def parse_time(text: str) -> datetime | None:
    text = (text or "").strip()
    if not text:
        return None
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def parse_number(text: str) -> float | None:
    """宽容一点：去掉千分位、货币符号、百分号。空串和 '-' 当缺失。"""
    cleaned = _NUM_CLEAN.sub("", (text or "").strip())
    if cleaned in ("", "-", "—", "null", "NULL", "NA", "N/A", "nan"):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def read_csv(text: str, skip_days: int = 0) -> dict:
    """返回 {times, dates, columns, skipped, rows}。

    times 是原始时间字符串，dates 是解析出来的 datetime（解析失败的填 None），
    columns 只保留「至少一半能转成数字」的列。
    """
    try:
        rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
    except csv.Error as e:
        raise CsvError(f"CSV 解析失败：{e}") from e

    rows = [r for r in rows if any((c or "").strip() for c in r)]
    if len(rows) < 2:
        raise CsvError("至少要有表头和一行数据")

    header = [h.strip() for h in rows[0]]
    body = rows[1:]
    if len(header) < 2:
        raise CsvError("至少要有两列：时间和一个指标")

    times = [(r[0] or "").strip() if r else "" for r in body]
    dates = [parse_time(t) for t in times]

    columns: dict[str, list[float | None]] = {}
    skipped: list[str] = []
    for idx in range(1, len(header)):
        name = header[idx] or f"列{idx}"
        values = [parse_number(r[idx]) if idx < len(r) else None for r in body]
        readable = sum(1 for v in values if v is not None)
        if readable < max(1, len(body) // 2):
            skipped.append(name)
            continue
        columns[name] = values

    if not columns:
        raise CsvError("没有一列能当指标用（都转不成数字）")

    # 时间解析得出来就按时间排，避免有人手动导出时顺序乱了
    order = list(range(len(body)))
    if all(d is not None for d in dates) and dates != sorted(dates):
        order = sorted(range(len(body)), key=lambda i: dates[i])
        times = [times[i] for i in order]
        dates = [dates[i] for i in order]
        columns = {k: [v[i] for i in order] for k, v in columns.items()}

    return {
        "times": times,
        "dates": dates,
        "columns": columns,
        "skipped": skipped,
        "rows": len(body),
    }


def typical_interval(dates: list[datetime | None]) -> float | None:
    """典型时间间隔（秒）。取相邻差的中位数，抗住个别断档。"""
    gaps = [(dates[i] - dates[i - 1]).total_seconds() for i in range(1, len(dates))
            if dates[i] and dates[i - 1]]
    if not gaps:
        return None
    gaps.sort()
    # 取偏低的中位：间隔序列常见「一个正常、一个双倍」，往上取会整天变大
    return gaps[(len(gaps) - 1) // 2]


def summarize(values: list[float | None]) -> dict:
    nums = [v for v in values if v is not None]
    if not nums:
        return {"n": 0, "missing": len(values), "min": None, "max": None, "mean": None}
    nums_sorted = sorted(nums)
    mid = len(nums_sorted) // 2
    median = nums_sorted[mid] if len(nums_sorted) % 2 else (nums_sorted[mid - 1] + nums_sorted[mid]) / 2
    return {
        "n": len(nums),
        "missing": len(values) - len(nums),
        "min": nums_sorted[0],
        "max": nums_sorted[-1],
        "mean": sum(nums) / len(nums),
        "median": median,
    }
