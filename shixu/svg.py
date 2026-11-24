"""零依赖的 SVG 折线图。

不引 matplotlib，也不想让你为了看一眼曲线去装东西。整张图就是一段字符串：
折线、异常点、起止时间标签。放到网页里直接能显示，存成 .svg 双击也能开。
"""

from __future__ import annotations

PAD_L, PAD_R, PAD_T, PAD_B = 56, 20, 28, 40
COLORS = {"spike": "#ff7b72", "drop": "#e3b341", "shift": "#79c0ff", "gap": "#8b949e", "missing": "#8b949e"}


def _fmt(v: float) -> str:
    """坐标保留两位，避免出现 1e-16 这种。"""
    return f"{v:.2f}".rstrip("0").rstrip(".")


def line_chart(times: list[str], values: list[float | None], issues: list[dict] | None = None,
               width: int = 860, height: int = 300, title: str = "") -> str:
    issues = issues or []
    plot_w = width - PAD_L - PAD_R
    plot_h = height - PAD_T - PAD_B
    nums = [v for v in values if v is not None]

    if not nums:
        return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"></svg>'

    lo, hi = min(nums), max(nums)
    if hi == lo:
        hi, lo = hi + 1, lo - 1
    span = hi - lo
    n = max(len(values) - 1, 1)

    def x_of(i: int) -> float:
        return PAD_L + plot_w * (i / n)

    def y_of(v: float) -> float:
        return PAD_T + plot_h * (1 - (v - lo) / span)

    # 折线分段：缺失处断开，不要连出一条假的直线
    segments, current = [], []
    for i, v in enumerate(values):
        if v is None:
            if current:
                segments.append(current)
                current = []
            continue
        current.append((x_of(i), y_of(v)))
    if current:
        segments.append(current)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="-apple-system,Segoe UI,Microsoft YaHei,sans-serif">',
        f'<rect width="{width}" height="{height}" fill="#0b0f14"/>',
    ]
    if title:
        parts.append(f'<text x="{PAD_L}" y="18" fill="#c9d1d9" font-size="13">{_esc(title)}</text>')

    # 三条水平参考线
    for frac in (0, 0.5, 1):
        y = PAD_T + plot_h * frac
        val = hi - span * frac
        parts.append(f'<line x1="{PAD_L}" y1="{_fmt(y)}" x2="{width - PAD_R}" y2="{_fmt(y)}" '
                     f'stroke="#21262d" stroke-dasharray="3 4"/>')
        parts.append(f'<text x="{PAD_L - 8}" y="{_fmt(y + 4)}" fill="#8b949e" font-size="10" '
                     f'text-anchor="end">{_fmt(val)}</text>')

    for seg in segments:
        pts = " ".join(f"{_fmt(x)},{_fmt(y)}" for x, y in seg)
        parts.append(f'<polyline points="{pts}" fill="none" stroke="#7ee787" stroke-width="1.6"/>')
        for x, y in seg:
            parts.append(f'<circle cx="{_fmt(x)}" cy="{_fmt(y)}" r="2" fill="#7ee787"/>')

    for issue in issues:
        i = issue.get("index")
        if i is None or i >= len(values):
            continue
        color = COLORS.get(issue.get("kind"), "#8b949e")
        x = x_of(i)
        if issue.get("value") is not None:
            y = y_of(float(issue["value"]))
            parts.append(f'<circle cx="{_fmt(x)}" cy="{_fmt(y)}" r="6" fill="none" stroke="{color}" stroke-width="2"/>')
            parts.append(f'<line x1="{_fmt(x)}" y1="{_fmt(y - 9)}" x2="{_fmt(x)}" y2="{_fmt(y - 16)}" stroke="{color}" stroke-width="1"/>')
        else:
            # 缺失 / 断档：在底部画一根竖线
            parts.append(f'<line x1="{_fmt(x)}" y1="{PAD_T}" x2="{_fmt(x)}" y2="{PAD_T + plot_h}" '
                         f'stroke="{color}" stroke-width="1" stroke-dasharray="4 3"/>')

    if times:
        parts.append(f'<text x="{PAD_L}" y="{height - 14}" fill="#8b949e" font-size="10">{_esc(times[0])}</text>')
        parts.append(f'<text x="{width - PAD_R}" y="{height - 14}" fill="#8b949e" font-size="10" '
                     f'text-anchor="end">{_esc(times[-1])}</text>')

    parts.append("</svg>")
    return "".join(parts)


def _esc(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
