"""造一份刻意埋了坑的样例数据：60 天日活，含大促尖峰、故障骤降、改版台阶、三天断档、一个空值。

随机数固定种子，重跑结果一致——不然每次生成的"异常"位置都不一样，README 里的截图就对不上了。
"""

from __future__ import annotations

import os
import random
from datetime import date, timedelta

random.seed(20261124)

START = date(2026, 9, 1)
DAYS = 60

# 埋点位置（0 基）
SPIKE_DAY = 20      # 大促，日活冲到 6200
DROP_DAY = 32       # 埋点接口挂了半天，跌到 900
SHIFT_DAY = 45      # 改版上了新首页，留存掉了，台阶持续
GAP_DAYS = (50, 51, 52)   # 采集任务没跑，三天没数据
MISSING_DAY = 58    # 那天上游只回了空字段


def build() -> str:
    lines = ["日期,日活,新增用户,订单量"]
    base = 3200
    for i in range(DAYS):
        day = START + timedelta(days=i)
        weekend = day.weekday() >= 5
        value = base + (260 if weekend else 0)

        # 缓慢增长 + 小波动
        value += i * 4
        value += random.randint(-90, 90)
        new_users = int(value / 12 + random.randint(-20, 20))
        orders = int(value * 0.06 + random.randint(-12, 12))

        if i >= SHIFT_DAY:  # 台阶：改版后基线整体下移，一直没回来
            value -= 800
        if i == SPIKE_DAY:
            value = 6200
            new_users = 980
            orders = 520

        if i in GAP_DAYS:
            continue  # 整行不写，制造断档

        if i == DROP_DAY:
            value = 900
            new_users = 40
            orders = 22

        value_text = "" if i == MISSING_DAY else str(value)
        lines.append(f"{day.isoformat()},{value_text},{new_users},{orders}")
    return "\n".join(lines) + "\n"


def main() -> None:
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "samples", "daily-active.csv")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(build())
    print(f"写好了：{out}")


if __name__ == "__main__":
    main()
