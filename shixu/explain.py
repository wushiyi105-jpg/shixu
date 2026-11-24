"""让模型解释异常，并且不许它编数字。

模型的活：拿到「哪一天、什么指标、偏离多少」和一句业务背景，给可能出现的原因和
「先查什么」。它不许重新算数，也不许引用没出现过的数值。

所以解释里出现的每个数字都要过一遍核验：只允许异常清单和统计摘要里有的那几个数。
对不上就打标记，报告里明说「这句里的数字对不上数据」。宁可显得啰嗦，也不让它用
一个编造的百分比把结论撑圆。
"""

from __future__ import annotations

import re

from . import llm

SYSTEM = """你是做数据排查的。手上有一份时间序列，已经用算法找出了异常点，你的任务是解释。

规则：
- 只根据给出的异常点和统计摘要推断，不要重新计算，不要引用没出现过的数字
- 每条异常给：原因（可能是什么造成的）、先查什么（一条能落地的动作）、把握程度
- 原因要具体，别写"可能是数据波动"这种等于没说的话
- 如果是断档或缺失，原因往采集侧想（任务没跑、接口超时、上游改字段）

只输出 JSON：
{"items": [{"n": 1, "cause": "", "check": "", "level": "high|medium|low"}],
 "summary": "三句话以内，说这批异常最可能是同一件事还是几件事"}

没有把握就写 low，不要为了显得专业而编。"""

_NUM_RE = re.compile(r"[0-9]+(?:\.[0-9]+)?")

# 日期不是数据。模型复述"10月3日""9/21"是正常的，把这些先剔掉再抽数字，
# 否则每条解释都会挂五六个假警告，机制看起来像坏了一样。
_DATE_RES = [
    re.compile(r"\d{4}\s*[-/年]\s*\d{1,2}\s*[-/月]\s*\d{1,2}\s*[日号]?"),
    re.compile(r"\d{1,2}\s*月\s*\d{1,2}\s*[日号]"),
    re.compile(r"\d{1,2}\s*/\s*\d{1,2}"),
    re.compile(r"\d{1,2}\s*-\s*\d{1,2}"),
    re.compile(r"\d{1,2}\s*月"),
    re.compile(r"\d{4}\s*年"),
    re.compile(r"\d{1,2}\s*[点时]\s*\d{1,2}\s*分?"),
]


def _strip_dates(text: str) -> str:
    for pattern in _DATE_RES:
        text = pattern.sub(" ", text)
    return text


def allowed_numbers(issues: list[dict], summary: dict) -> set[float]:
    """本次解释里允许出现的数：异常值、基线、偏离度、统计摘要、条数，以及 note 里的数。"""
    allowed = {float(len(issues))}
    for i, issue in enumerate(issues, 1):
        allowed.add(float(i))
        allowed.add(float(issue.get("index") or 0))
        for key in ("value", "baseline", "deviation"):
            v = issue.get(key)
            if v is not None:
                allowed.add(float(v))
        # note 是程序自己写的（"隔了 4 个周期""正常约 24 小时"），模型引用它不算编造
        for raw in _NUM_RE.findall(_strip_dates(issue.get("note") or "")):
            try:
                allowed.add(float(raw))
            except ValueError:
                continue
    for key, v in (summary or {}).items():
        if isinstance(v, (int, float)):
            allowed.add(float(v))
    return allowed


def verify_numbers(text: str, allowed: set[float], tol: float = 0.05) -> list[str]:
    """返回对不上的数字（原样）。±0.05 的容差，允许模型自己四舍五入。"""
    bad = []
    for raw in _NUM_RE.findall(_strip_dates(text or "")):
        try:
            value = float(raw)
        except ValueError:
            continue
        if value <= 5 and value == int(value):
            # 1、2、3 这种多半是序号（"第 2 点""3 条异常"），不当成数据
            continue
        if not any(abs(value - a) <= max(tol, abs(a) * 0.01) for a in allowed):
            bad.append(raw)
    return bad


def explain(column: str, note: str, summary: dict, issues: list[dict], config=None,
            max_tokens: int = 8000, limit: int = 8) -> dict:
    """返回 {items, summary, error, unverified}。失败不抛。"""
    picked = issues[:limit]
    lines = []
    for i, issue in enumerate(picked, 1):
        bit = f"{i}. [{issue['kind']}] {issue['time']}"
        if issue["value"] is not None:
            bit += f"，值 {issue['value']:g}"
        if issue["baseline"] is not None:
            bit += f"，基线 {issue['baseline']:g}"
        if issue["deviation"] is not None:
            bit += f"，偏离 {issue['deviation']:g}"
        bit += f"（{issue['note']}）"
        lines.append(bit)

    stat_text = "、".join(f"{k}={v:g}" for k, v in summary.items()
                         if isinstance(v, (int, float)) and v is not None)
    user = (
        f"【指标】{column}\n业务背景：{note or '（没有提供背景）'}\n"
        f"【统计摘要】{stat_text or '（无）'}\n"
        f"【异常】共 {len(issues)} 条，这里列出前 {len(picked)} 条：\n" + "\n".join(lines) +
        "\n\n按要求输出 JSON。"
    )
    try:
        raw = llm.chat(
            [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
            config=config, temperature=0.2, max_tokens=max_tokens,
        )
        data = llm.extract_json(raw)
        if not isinstance(data, dict):
            raise llm.LLMError("返回不是对象")
    except llm.LLMError as e:
        return {"items": [], "summary": "", "error": str(e), "unverified": []}

    allowed = allowed_numbers(picked, summary)
    out = []
    unverified: list[str] = []
    for row in data.get("items") or []:
        try:
            n = int(row.get("n"))
        except (TypeError, ValueError):
            continue
        if not (1 <= n <= len(picked)):
            continue
        cause = str(row.get("cause") or "")[:300]
        check = str(row.get("check") or "")[:200]
        level = row.get("level") if row.get("level") in ("high", "medium", "low") else "medium"
        bad = verify_numbers(cause + " " + check, allowed)
        if bad:
            unverified.extend(bad)
        out.append({
            "n": n,
            "issue": picked[n - 1],
            "cause": cause,
            "check": check,
            "level": level,
            "unverified": bad,
        })

    summary_text = str(data.get("summary") or "")[:300]
    unverified.extend(verify_numbers(summary_text, allowed))
    return {"items": out, "summary": summary_text, "error": "", "unverified": unverified}
