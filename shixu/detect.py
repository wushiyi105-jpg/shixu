"""异常检测：三个算法，都不依赖第三方库。

1. 稳健 Z 分数（滚动中位数 + MAD）：抓单点突变。用中位数和 MAD 而不是均值和标准差，
   是因为异常点自己会把均值和标准差拽偏——三个大促日能把一个月的标准差翻倍。
2. 水平漂移：前窗均值 vs 后窗均值，差超过阈值就报。这条抓的是「台阶」，不是尖刺。
3. 断档与缺失：时间间隔超过典型间隔的 N 倍，或者值缺失，单独报。

阈值都在函数参数里，改起来不用翻文档。
"""

from __future__ import annotations

from . import series as S

# 稳健 Z 分数用这个常数把 MAD 折算成标准差
MAD_SCALE = 0.6745


def _median(nums: list[float]) -> float:
    s = sorted(nums)
    n = len(s)
    if not n:
        return 0.0
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def _mad(nums: list[float], center: float) -> float:
    return _median([abs(x - center) for x in nums])


def _issue(kind, index, time, value, baseline, deviation, note):
    return {
        "kind": kind,
        "index": index,
        "time": time,
        "value": value,
        "baseline": round(baseline, 2) if baseline is not None else None,
        "deviation": round(deviation, 2) if deviation is not None else None,
        "note": note,
    }


def find_spikes(times, values, window: int = 14, z: float = 3.5, min_abs: float | None = None) -> list[dict]:
    """单点突变。窗口取该点之前的 window 个点，避免用到未来数据。"""
    out = []
    for i, v in enumerate(values):
        if v is None:
            continue
        start = max(i - window, 0)
        history = [x for x in values[start:i] if x is not None]
        if len(history) < max(window // 2, 7):
            # 起步那几天没有历史基线，MAD 小得离谱，硬判就会报假尖峰
            continue
        center = _median(history)
        spread = _mad(history, center)
        if spread == 0:
            spread = max(abs(center) * 0.01, 1e-9)  # 全平的序列：任何偏差都算大
        score = MAD_SCALE * (v - center) / spread
        if abs(score) < z:
            continue
        if min_abs is not None and abs(v - center) < min_abs:
            continue
        kind = "spike" if score > 0 else "drop"
        out.append(_issue(
            kind, i, times[i], v, center, score,
            f"比前 {len(history)} 个点的中位数（{center:.2f}）{'高' if score > 0 else '低'} {abs(score):.1f} 个 MAD",
        ))
    return out


def find_shifts(times, values, window: int = 7, ratio: float = 2.0) -> list[dict]:
    """水平漂移：前后两窗的中心水平差得离谱，而且差完就没回来。

    三个约束，缺一个就得被误报淹没：
    - 用中位数不用均值。均值会被窗口里单个尖峰拽走：一个 980 落进 7 点里，
      均值能抬 100，中位数纹丝不动。
    - 只留局部最强。同一个台阶会让相邻七八个位置都超阈值，只保留得分最高的那个。
    - 要看它稳不稳。台阶之后再来一个窗，水平得跟台阶上一致；又弹回去说明是波动。
    """
    n = len(values)
    candidates = []
    for i in range(window, n - window + 1):
        before = [x for x in values[i - window:i] if x is not None]
        after = [x for x in values[i:i + window] if x is not None]
        if len(before) < window - 2 or len(after) < window - 2:
            continue
        m1 = _median(before)
        m2 = _median(after)
        spread = _mad(before, m1)
        if spread == 0:
            spread = max(abs(m1) * 0.01, 1e-9)
        score = abs(m2 - m1) / spread
        if score < ratio * 3:
            continue
        candidates.append((score, i, m1, m2))

    # 非极大值抑制：得分高的先占位，附近（一个窗内）的其余候选一律丢掉
    kept = []
    for score, i, m1, m2 in sorted(candidates, key=lambda x: -x[0]):
        if any(abs(i - k[1]) < window for k in kept):
            continue
        kept.append((score, i, m1, m2))

    out = []
    for score, i, m1, m2 in sorted(kept, key=lambda x: x[1]):
        # NMS 留下的是得分最高那个位置，未必是台阶第一天：得分打平时它可能落在
        # 台阶前一两天（那时窗口里的中位数已经翻过去了，分一样高）。先把起点推到
        # 真正站上新水平的那天，再往前回溯到第一个已经在新水平上的点。
        first = i
        while first < n - 1 and (values[first] is None
                                 or abs(values[first] - m2) > abs(m2 - m1) * 0.5):
            first += 1
        while first - 1 >= window:
            prev = values[first - 1]
            if prev is None or abs(prev - m2) > abs(m2 - m1) * 0.5:
                break
            first -= 1

        # 持续性：台阶后下一个窗还在这个水平上，才算"换了个台阶"
        tail = [x for x in values[first + window:first + 2 * window] if x is not None]
        if len(tail) >= window - 2:
            m3 = _median(tail)
            if abs(m3 - m2) > abs(m2 - m1) * 0.5:
                continue
            note = (f"从这里开始，{window} 点中位数从 {m1:.2f} 变成 {m2:.2f}，"
                    f"之后一个窗还稳在 {m3:.2f}，是换了个台阶而不是抖一下")
        else:
            note = f"从这里开始，{window} 点中位数从 {m1:.2f} 变成 {m2:.2f}（序列尾部，没看到之后）"
        out.append(_issue("shift", first, times[first], m2, m1, score, note))
    return out


def find_gaps(times, dates, values, factor: float = 2.0) -> list[dict]:
    """断档：时间间隔超过典型间隔的 factor 倍。"""
    typ = S.typical_interval(dates)
    if not typ:
        return []
    out = []
    for i in range(1, len(dates)):
        if not (dates[i] and dates[i - 1]):
            continue
        gap = (dates[i] - dates[i - 1]).total_seconds()
        if gap > typ * factor:
            out.append(_issue(
                "gap", i, times[i], None, None, gap / typ,
                f"距上一个点隔了 {gap / typ:.1f} 个正常周期（正常约 {typ / 3600:.1f} 小时）",
            ))
    return out


def find_missing(times, values) -> list[dict]:
    out = []
    for i, v in enumerate(values):
        if v is None:
            out.append(_issue("missing", i, times[i], None, None, None, "这一行没有数值，可能是采集失败"))
    return out


def analyze(data: dict, column: str, window: int = 14, z: float = 3.5, shift_ratio: float = 2.0,
            gap_factor: float = 2.0) -> list[dict]:
    """对一个指标跑全部检测，把相邻重复的合并掉，按严重程度排序。"""
    if column not in data["columns"]:
        raise KeyError(f"没有这一列：{column}")
    values = data["columns"][column]
    issues = []
    issues += find_missing(data["times"], values)
    issues += find_gaps(data["times"], data["dates"], values, factor=gap_factor)

    shift_win = max(3, window // 2)
    shifts = find_shifts(data["times"], values, window=shift_win, ratio=shift_ratio)

    # 台阶一旦被认出，台阶后那一窗里的「骤降/尖峰」多半只是它自己的回响：
    # 中位数还停在旧水平，新值当然看着像掉下去了。落在新台阶 ±15% 的一律压掉。
    spikes = []
    for s in find_spikes(data["times"], values, window=window, z=z):
        near_shift = next(
            (sh for sh in shifts if abs(s["index"] - sh["index"]) < shift_win), None
        )
        if near_shift and s["value"] is not None and near_shift["value"]:
            if abs(s["value"] - near_shift["value"]) <= abs(near_shift["value"]) * 0.15:
                continue
        spikes.append(s)
    issues += spikes
    issues += shifts

    # 同一个位置既有尖刺又有漂移，只留尖刺（它更具体）
    seen = set()
    result = []
    for issue in sorted(issues, key=lambda x: (x["index"], 0 if x["kind"] in ("spike", "drop") else 1)):
        key = (issue["index"], issue["kind"])
        if key in seen:
            continue
        if issue["kind"] == "shift" and any(
            r["index"] == issue["index"] and r["kind"] in ("spike", "drop") for r in result
        ):
            continue
        seen.add(key)
        result.append(issue)

    def severity(x):
        if x["kind"] in ("spike", "drop"):
            return abs(x["deviation"] or 0)
        if x["kind"] == "shift":
            return (x["deviation"] or 0) / 3
        if x["kind"] == "gap":
            return (x["deviation"] or 0) * 0.8
        return 0.5

    result.sort(key=lambda x: (-severity(x), x["index"]))
    return result
