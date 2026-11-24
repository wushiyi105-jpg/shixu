"""生成 assets/demo.gif：960×600 的终端风演示动图。

只用 Pillow（开发期依赖，不进 requirements）。跑法：
    python scripts/make_demo_gif.py

画面里的数字都是真跑出来的：57 行样例、11 个异常、解释里 0 条编造数字。
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

W, H = 960, 600
BG = "#0b0f14"
BAR = "#161b22"
LINE = "#21262d"
GREEN = "#7ee787"
TEXT = "#c9d1d9"
DIM = "#8b949e"
BLUE = "#79c0ff"
YELLOW = "#e3b341"
RED = "#ff7b72"

FONT_PATH = r"C:\Windows\Fonts\msyh.ttc"

LINE_H = 25
MAX_W = W - 56

COLORS = {"cmd": GREEN, "out": TEXT, "dim": DIM, "cite": BLUE, "warn": YELLOW, "bad": RED}


def font(size: int):
    return ImageFont.truetype(FONT_PATH, size)


_MEASURE = ImageDraw.Draw(Image.new("RGB", (1, 1)))


def clip(text: str, size: int = 16) -> str:
    f = font(size)
    if _MEASURE.textlength(text, font=f) <= MAX_W:
        return text
    while text and _MEASURE.textlength(text + "…", font=f) > MAX_W:
        text = text[:-1]
    return text + "…"


def render(rows, cursor_row=None):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 36], fill=BAR)
    for i, color in enumerate(["#ff5f56", "#ffbd2e", "#27c93f"]):
        d.ellipse([16 + i * 22, 12, 28 + i * 22, 24], fill=color)
    d.text((92, 9), "shixu — 时序异常，模型解释，数字要能对上", font=font(15), fill=DIM)
    d.line([0, 36, W, 36], fill=LINE)

    y = 54
    for idx, (style, text) in enumerate(rows):
        shown = clip(text)
        d.text((26, y), shown, font=font(16), fill=COLORS[style])
        if cursor_row == idx:
            w = _MEASURE.textlength(shown, font=font(16))
            d.rectangle([26 + w + 4, y + 2, 26 + w + 12, y + 19], fill=GREEN)
        y += LINE_H
        if y > H - 16:
            break
    return img


SCRIPT = [
    ("cmd", "> python -m shixu add samples/daily-active.csv"),
    ("out", "· 数据集 [1] 电商日活 —— 57 行，指标：日活、新增用户、订单量"),
    ("cmd", "> python -m shixu detect 1 --no-model"),
    ("out", "=== 指标「日活」—— 56 个点（缺 1），900–6200，中位数 3287.5 ==="),
    ("out", "异常：尖峰 1、骤降 1、断档 1、台阶 1、缺失 1"),
    ("bad", "1. [尖峰] 2026-09-21，值 6200（基线 3277.5）"),
    ("dim", "     比前 14 个点的中位数高 28.6 个 MAD"),
    ("bad", "2. [骤降] 2026-10-03，值 900（基线 3351.5）—— 低 15.3 个 MAD"),
    ("warn", "3. [断档] 2026-10-24 —— 距上一个点隔了 4 个正常周期"),
    ("cite", "4. [台阶] 2026-10-16，值 2597（基线 3368）"),
    ("dim", "5. [缺失] 2026-10-29 —— 这一行没有数值"),
    ("cmd", "> python -m shixu detect 1        # 带上模型"),
    ("out", "一句话：9-21 像大促，10-3 像假期，10-16 更像改版后入口掉了"),
    ("out", "1. 可能原因：大促投放带来的集中回流访问"),
    ("dim", "   先查什么：核对营销日历与优惠券发放记录（把握 高）"),
    ("cite", "4. 可能原因：新版首页改版，核心入口曝光减少"),
    ("warn", "5. 可能原因：采集任务没跑，或上游字段变了（把握 高）"),
    ("dim", "解释里对不上数据的数字：0 个"),
]
TAIL = [
    ("warn", "第一版台阶报了 16 个 —— 全是噪音，周末波动也算台阶。"),
    ("dim", "换中位数、去重、回溯起点之后剩 1 个，日期正对 10-16。"),
]


def build():
    frames, shown = [], []
    for style, text in SCRIPT:
        if style == "cmd":
            for i in range(6, len(text) + 1, 6):
                frames.append(render(shown + [("cmd", text[:i])], cursor_row=len(shown)))
        shown = shown + [(style, text)]
        frames.append(render(shown))
    for _ in range(12):
        frames.append(render(shown + TAIL))

    frames = [f.quantize(colors=20, method=Image.MEDIANCUT) for f in frames]
    os.makedirs("assets", exist_ok=True)
    out = os.path.join("assets", "demo.gif")
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=140, loop=0, optimize=True)
    print(f"ok -> {out}  {len(frames)} 帧  {os.path.getsize(out) / 1024:.1f} KB")


if __name__ == "__main__":
    build()
