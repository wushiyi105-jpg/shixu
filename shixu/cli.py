"""命令行入口。"""

from __future__ import annotations

import argparse
import json
import os

from . import detect, explain, llm, series as S, store, svg

KIND_LABEL = {"spike": "尖峰", "drop": "骤降", "shift": "台阶", "gap": "断档", "missing": "缺失"}
LEVEL_LABEL = {"high": "高", "medium": "中", "low": "低"}


_OPENED: list = []


def _open(args):
    conn = store.connect(args.db)
    _OPENED.append(conn)
    return conn


def _read(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def cmd_add(args) -> int:
    conn = _open(args)
    for path in args.files:
        if not os.path.isfile(path):
            print(f"✗ 找不到文件：{path}")
            continue
        text = _read(path)
        try:
            data = S.read_csv(text)
        except S.CsvError as e:
            print(f"✗ {os.path.basename(path)}：{e}")
            continue
        name = args.name or os.path.splitext(os.path.basename(path))[0]
        did = store.add_dataset(conn, name, text, data["rows"], list(data["columns"]), note=args.note or "")
        print(f"· 数据集 [{did}] {name} —— {data['rows']} 行，指标：{'、'.join(data['columns'])}")
        if data["skipped"]:
            print(f"  （这几列转不成数字，已跳过：{'、'.join(data['skipped'])}）")
        print(f"  跑检测：python -m shixu detect {did}")
    return 0


def cmd_list(args) -> int:
    conn = _open(args)
    rows = store.list_datasets(conn)
    if not rows:
        print("还没有数据集。先 python -m shixu add samples/xxx.csv")
        return 0
    print(f"{'ID':<4}{'行':<6}{'结果':<6}名字 / 指标")
    for r in rows:
        print(f"{r['id']:<4}{r['rows']:<6}{r['findings']:<6}{r['name']} —— {'、'.join(r['columns'])}")
    return 0


def cmd_detect(args) -> int:
    conn = _open(args)
    row = store.get_dataset(conn, args.id)
    if not row:
        print(f"✗ 没有 id={args.id} 的数据集")
        return 1
    try:
        data = S.read_csv(row["csv"])
    except S.CsvError as e:
        print(f"✗ 存储的 CSV 读不出来了：{e}")
        return 1

    targets = [args.column] if args.column else list(data["columns"])
    if args.column and args.column not in data["columns"]:
        print(f"✗ 没有这一列：{args.column}（有：{'、'.join(data['columns'])}）")
        return 1

    cfg = None if args.no_model else llm.config_from_args(args)
    params = {"window": args.window, "z": args.z, "shift_ratio": args.shift_ratio}
    report = []

    for column in targets:
        issues = detect.analyze(data, column, window=args.window, z=args.z, shift_ratio=args.shift_ratio)
        summary = S.summarize(data["columns"][column])
        explained, takeaway, unverified, error = [], "", [], ""
        if issues and cfg is not None:
            result = explain.explain(column, row["note"], summary, issues, config=cfg)
            explained, takeaway, unverified, error = (
                result["items"], result["summary"], result["unverified"], result["error"]
            )
        store.save_finding(conn, row["id"], column, issues, summary, explained, takeaway, unverified, params)
        report.append({
            "column": column, "issues": issues, "summary": summary,
            "explained": explained, "takeaway": takeaway, "unverified": unverified, "error": error,
        })

    if args.json:
        print(json.dumps({"dataset": row["name"], "columns": report}, ensure_ascii=False, indent=2))
        return 0

    for item in report:
        print(f"\n=== 数据集 [{row['id']}] {row['name']} · 指标「{item['column']}」 ===")
        s = item["summary"]
        if s["n"]:
            print(f"{s['n']} 个点（缺 {s['missing']}），范围 {s['min']:g}–{s['max']:g}，中位数 {s.get('median', 0):g}")
        if item["error"]:
            print(f"! 模型解释没跑成：{item['error']}（异常点照常列出）")
        if not item["issues"]:
            print("没发现异常。")
            continue
        by_kind: dict[str, int] = {}
        for issue in item["issues"]:
            by_kind[issue["kind"]] = by_kind.get(issue["kind"], 0) + 1
        print("异常：" + "、".join(f"{KIND_LABEL.get(k, k)} {v}" for k, v in by_kind.items()))
        if item["takeaway"]:
            print(f"一句话：{item['takeaway']}")
        for n, issue in enumerate(item["issues"], 1):
            head = f"{n}. [{KIND_LABEL.get(issue['kind'], issue['kind'])}] {issue['time']}"
            if issue["value"] is not None:
                head += f"，值 {issue['value']:g}"
            if issue["baseline"] is not None:
                head += f"（基线 {issue['baseline']:g}）"
            print(head)
            print(f"   {issue['note']}")
            exp = next((e for e in item["explained"] if e["n"] == n), None)
            if exp:
                print(f"   可能原因：{exp['cause']}")
                print(f"   先查什么：{exp['check']}（把握：{LEVEL_LABEL.get(exp['level'], exp['level'])}）")
                if exp["unverified"]:
                    print(f"   ! 这句里的数字对不上数据：{', '.join(exp['unverified'])}")
        if item["unverified"]:
            print(f"! 解释里有 {len(item['unverified'])} 个数字和数据对不上，已标在上面")

    if args.out:
        _write_markdown(args.out, row, report)
        print(f"\n报告已写到 {args.out}")
    return 0


def _write_markdown(path: str, row: dict, report: list[dict]) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    lines = [f"# {row['name']} 异常报告", ""]
    if row["note"]:
        lines += [f"> {row['note']}", ""]
    for item in report:
        lines += [f"## 指标「{item['column']}」", ""]
        s = item["summary"]
        if s["n"]:
            lines += [f"{s['n']} 个点（缺 {s['missing']}），范围 {s['min']:g}–{s['max']:g}", ""]
        if item["takeaway"]:
            lines += [f"**{item['takeaway']}**", ""]
        if not item["issues"]:
            lines += ["没发现异常。", ""]
            continue
        for n, issue in enumerate(item["issues"], 1):
            lines += [f"### {n}. {KIND_LABEL.get(issue['kind'], issue['kind'])} · {issue['time']}", "",
                      f"- 数值：{issue['value']}（基线 {issue['baseline']}）",
                      f"- 偏离：{issue['note']}"]
            exp = next((e for e in item["explained"] if e["n"] == n), None)
            if exp:
                lines.append(f"- 可能原因：{exp['cause']}")
                lines.append(f"- 先查什么：{exp['check']}（把握 {LEVEL_LABEL.get(exp['level'], exp['level'])}）")
                if exp["unverified"]:
                    lines.append(f"- ⚠ 数字对不上：{', '.join(exp['unverified'])}")
            lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def cmd_show(args) -> int:
    conn = _open(args)
    row = store.get_dataset(conn, args.id)
    if not row:
        print(f"✗ 没有 id={args.id} 的数据集")
        return 1
    data = S.read_csv(row["csv"])
    print(f"\n=== [{row['id']}] {row['name']} ===\n{row['rows']} 行 · 指标 {'、'.join(row['columns'])}")
    if row["note"]:
        print(f"背景：{row['note']}")
    print(f"时间范围：{data['times'][0]} → {data['times'][-1]}")
    for column in row["columns"]:
        f = store.get_finding(conn, row["id"], column)
        if f:
            print(f"  · {column}：{len(f['issues'])} 个异常，检测于 {f['created_at']}，阈值 {f['params']}")
        else:
            print(f"  · {column}：还没检测")
    return 0


def cmd_svg(args) -> int:
    conn = _open(args)
    row = store.get_dataset(conn, args.id)
    if not row:
        print(f"✗ 没有 id={args.id} 的数据集")
        return 1
    data = S.read_csv(row["csv"])
    branch = store.get_finding(conn, row["id"], args.column)
    issues = branch["issues"] if branch else detect.analyze(data, args.column)
    out = args.out or f"assets/{args.column}-{args.id}.svg"
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    chart = svg.line_chart(data["times"], data["columns"][args.column], issues,
                           title=f"{row['name']} · {args.column}")
    with open(out, "w", encoding="utf-8") as f:
        f.write(chart)
    print(f"· 图已写到 {out}（{len(issues)} 个异常标注）")
    return 0


def cmd_rm(args) -> int:
    conn = _open(args)
    if not store.get_dataset(conn, args.id):
        print(f"✗ 没有 id={args.id} 的数据集")
        return 1
    store.delete_dataset(conn, args.id)
    print(f"· 数据集 [{args.id}] 已删除（含检测结果）")
    return 0


def cmd_stats(args) -> int:
    conn = _open(args)
    print("统计：", store.stats(conn))
    return 0


def cmd_serve(args) -> int:
    from . import web

    conn = _open(args)
    web.serve(conn, host=args.host, port=args.port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="shixu", description="时序异常：算法找点，模型解释，数字要能对上。")
    p.add_argument("--db", default="data/shixu.db")
    p.add_argument("--version", action="version", version="%(prog)s 0.1.0")
    p.add_argument("--api-key")
    p.add_argument("--base-url")
    p.add_argument("--model")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="导入 CSV")
    a.add_argument("files", nargs="+")
    a.add_argument("--name")
    a.add_argument("--note", help="业务背景，会带进模型解释里")
    a.set_defaults(func=cmd_add)

    sub.add_parser("list", help="数据集列表").set_defaults(func=cmd_list)

    d = sub.add_parser("detect", help="跑检测")
    d.add_argument("id", type=int)
    d.add_argument("--column")
    d.add_argument("--window", type=int, default=14)
    d.add_argument("--z", type=float, default=3.5)
    d.add_argument("--shift-ratio", type=float, default=2.0)
    d.add_argument("--no-model", action="store_true")
    d.add_argument("--json", action="store_true")
    d.add_argument("--out")
    d.set_defaults(func=cmd_detect)

    s = sub.add_parser("show", help="看数据集和历次检测")
    s.add_argument("id", type=int)
    s.set_defaults(func=cmd_show)

    g = sub.add_parser("svg", help="导出一张 SVG 曲线图")
    g.add_argument("id", type=int)
    g.add_argument("--column", required=True)
    g.add_argument("--out")
    g.set_defaults(func=cmd_svg)

    r = sub.add_parser("rm", help="删数据集")
    r.add_argument("id", type=int)
    r.set_defaults(func=cmd_rm)

    sub.add_parser("stats", help="统计").set_defaults(func=cmd_stats)

    sv = sub.add_parser("serve", help="起 Web")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8770)
    sv.set_defaults(func=cmd_serve)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    finally:
        # 子命令跑完就把连接还回去。不还的话 Windows 上删库会报"文件被占用"，
        # Python 3.13 也会在退出时刷一串 ResourceWarning。
        while _OPENED:
            try:
                _OPENED.pop().close()
            except Exception:  # noqa: BLE001
                pass
