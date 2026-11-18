"""独立数学交叉核对（AGENTS.md §2 门禁③ / spec §14 / 附录B.7 期望值总表）。

独立侧**不导入 pc_quote_flow.pricing/tax/money**：按附录B公式用 Decimal 从头重算，
再与程序输出逐项比对（pricing 仅作为被测程序调用，model 为纯数据类）。
覆盖 B.7 全 12 行：底价/四数/单项覆盖/反算写回/实际利润/数量舍入。
任一比对 FAIL → 退出码 1。全部数字为附录A虚构样例（红线1）。

注：行1/4 的 C 与应缴增值税程序本任务未直接输出，按 B.2 恒等式从程序底价导出比对：
C = B/(1+t)（精确成立）；应缴增值税 = B − 采购合计（B = S+P+P×t）。
"""
import sys
from decimal import Decimal as D, ROUND_HALF_UP
from pathlib import Path

from pc_quote_flow import model, pricing  # pricing=被测程序；独立重算全部在下方本地函数

T = D("0.13")  # v1 一般纳税人税率（B.1）


# ---------- 独立重算（附录B公式，纯 Decimal，不调用程序任何计算函数） ----------

def r2(x: D) -> D:
    """B.1：ROUND_HALF_UP 到分。"""
    return x.quantize(D("0.01"), rounding=ROUND_HALF_UP)


def p2(x: D) -> D:
    """B.1：百分比显示保留 2 位小数。"""
    return r2(x * 100)


ALIASES = {"专票": "专票", "京东专票": "专票", "普票": "普票", "普通发票": "普票"}


def fi(price: D, qty: int, invoice: str) -> D:
    """B.2 件底价贡献（全精度）：专票=p×n；普票=p×n×(1+t)。"""
    total = price * qty
    return total if ALIASES[invoice] == "专票" else total * (1 + T)


def ci(price: D, qty: int, invoice: str) -> D:
    """B.2/B.5 件不含税成本（全精度）：专票=p×n/(1+t)；普票=p×n。"""
    total = price * qty
    return total / (1 + T) if ALIASES[invoice] == "专票" else total


def qi(f: D, rate: D, mode: str) -> D:
    """B.3 件报价：加成 round(f×(1+r))；毛利率 round(f÷(1−m))。"""
    return r2(f * (1 + rate)) if mode == "markup" else r2(f / (1 - rate))


def ind_price(lines: list[model.QuoteLine], mode: str, unified: D) -> dict:
    """B.1/B.3 整机定价独立重算（件率单项覆盖优先；Q=Σ舍入后件报价）。"""
    fs = [fi(ln.unit_price, ln.qty, ln.invoice) for ln in lines]
    qs = [
        qi(f, ln.item_rate if ln.item_rate is not None else unified, mode) + ln.quote_adjust
        for f, ln in zip(fs, lines)
    ]
    b = r2(sum(fs, D("0")))
    q = sum(qs, D("0"))
    return {
        "line_floors": [r2(f) for f in fs],
        "line_quotes": qs,
        "floor": b,
        "quote": q,
        "profit": r2((q - b) / (1 + T)),
        "markup": (q - b) / b,
        "margin": (q - b) / q,
    }


def ind_reverse(target: D, floor: D, mode: str) -> D:
    """B.4 反解（全精度）：r*=T/B−1=(T−B)/B；m*=1−B/T=(T−B)/T。"""
    return (target - floor) / floor if mode == "markup" else (target - floor) / target


def ind_reverse_lines(lines: list[model.QuoteLine], target: D, mode: str) -> tuple[D, list[D], D, int]:
    """B.4 写回独立重算：反解率→重算件报价→尾差 δ=T−Σq 加到底价最大件。"""
    fs = [fi(ln.unit_price, ln.qty, ln.invoice) for ln in lines]
    rate = ind_reverse(target, r2(sum(fs, D("0"))), mode)
    qs = [qi(f, rate, mode) for f in fs]
    drift = target - sum(qs, D("0"))
    idx = max(range(len(fs)), key=fs.__getitem__)
    qs[idx] += drift
    return rate, qs, drift, idx


def ind_effective(ln: model.QuoteLine) -> tuple[D, str]:
    """B.5 有效价回退链：实际→确认→报价时；发票同链回退。"""
    chain = (
        (ln.actual_price, ln.actual_invoice),
        (ln.confirm_price, ln.confirm_invoice),
        (ln.unit_price, ln.invoice),
    )
    for i, (price, _) in enumerate(chain):
        if price is not None:
            return price, next(inv for _, inv in chain[i:] if inv is not None)
    raise AssertionError("unit_price 不应为 None")


def ind_actuals(lines: list[model.QuoteLine], q: D) -> tuple[D, D, D]:
    """B.5 独立重算：C'=Σci(有效价)、B'=Σfi(有效价)、真实利润=round(Q/(1+t)−C')。"""
    c_full = D("0")
    b_full = D("0")
    for ln in lines:
        price, inv = ind_effective(ln)
        c_full += ci(price, ln.qty, inv)
        b_full += fi(price, ln.qty, inv)
    return r2(c_full), r2(b_full), r2(q / (1 + T) - c_full)


# ---------- 附录A虚构夹具（逐字照抄设计文档附录A两张表） ----------

CFG_A = [
    ("CPU（盒装）", "2000", 1, "专票"),
    ("主板", "1000", 1, "专票"),
    ("内存 32G 套条", "800", 1, "京东专票"),
    ("固态 500G", "600", 1, "京东专票"),
    ("机械 2TB", "900", 1, "专票"),
    ("电源 650W", "300", 1, "专票"),
    ("散热双塔", "100", 1, "专票"),
    ("机箱", "80", 1, "专票"),
    ("风扇 120mm", "20", 1, "专票"),
]
CFG_B = [
    ("CPU（散片）", "1000", 1, "普票"),
    ("主板", "1000", 1, "专票"),
    ("内存 16G", "400", 1, "京东专票"),
    ("固态 500G", "600", 1, "专票"),
    ("机械 1TB", "500", 1, "京东专票"),
    ("电源 650W", "300", 1, "专票"),
    ("散热双塔", "100", 1, "专票"),
    ("机箱", "80", 1, "专票"),
    ("风扇 120mm", "20", 1, "专票"),
]


def mk_lines(cfg: list[tuple]) -> list[model.QuoteLine]:
    return [model.QuoteLine(name=n, qty=q, unit_price=D(p), invoice=inv) for n, p, q, inv in cfg]


def mk_doc(cfg: list[tuple], mode: str = "markup", rate: str = "0.10") -> model.QuoteDoc:
    return model.QuoteDoc(config_name="虚构", lines=mk_lines(cfg), mode=mode, unified_rate=D(rate))


# ---------- 逐项比对 ----------

_items: list[bool] = []
_cases: dict[str, bool] = {}
_records: list[dict] = []  # 供 --report 生成逐项对照表（确定性，无时间戳/随机值）


def check(case: str, item: str, got, ind, table=None) -> None:
    """程序输出 vs 独立重算（vs B.7 表期望值，若给出）。"""
    ok = got == ind and (table is None or got == table)
    _items.append(ok)
    _cases[case] = _cases.get(case, True) and ok
    _records.append({"case": case, "item": item, "got": got, "ind": ind, "table": table, "ok": ok})
    tab = "" if table is None else f" 表={table}"
    print(f"[{'PASS' if ok else 'FAIL'}] {case} · {item}: 程序={got} 独立={ind}{tab}")


def case_floor(row: str, cfg: list[tuple], b_tab: str, c_tab: str, vat_tab: str) -> None:
    """行1/4：底价 B、不含税成本 C、应缴增值税（C/VAT 按 B.2 恒等式从程序底价导出）。"""
    lines = mk_lines(cfg)
    dp = pricing.price_doc(lines, "markup", D("0.10"), pricing.TaxProfile())
    ip = ind_price(lines, "markup", D("0.10"))
    purchase = sum((D(p) * q for _, p, q, _ in cfg), D("0"))
    p_sum = sum((D(p) * q for _, p, q, inv in cfg if ALIASES[inv] == "普票"), D("0"))
    ind_c = r2(sum((ci(D(p), q, inv) for _, p, q, inv in cfg), D("0")))
    check(row, "整机底价B", dp.floor, ip["floor"], D(b_tab))
    check(row, "不含税成本C=B/(1+t)", r2(dp.floor / (1 + T)), ind_c, D(c_tab))
    check(row, "应缴增值税=B−采购合计", dp.floor - purchase, r2(p_sum * T), D(vat_tab))


def case_four(row: str, cfg: list[tuple], mode: str, q_tab: str, profit_tab: str,
              markup_tab: str | None, margin_tab: str) -> None:
    """行2/3/5/6：四数（Q/利润/加成率/毛利率）。"""
    lines = mk_lines(cfg)
    dp = pricing.price_doc(lines, mode, D("0.10"), pricing.TaxProfile())
    ip = ind_price(lines, mode, D("0.10"))
    check(row, "整机报价Q", dp.quote, ip["quote"], D(q_tab))
    check(row, "利润额(不含税)", dp.profit_excl, ip["profit"], D(profit_tab))
    if markup_tab is not None:
        check(row, "加成率%", p2(dp.markup), p2(ip["markup"]), D(markup_tab))
    check(row, "毛利率%", p2(dp.margin), p2(ip["margin"]), D(margin_tab))


# ---------- 数学验证报告（--report PATH；确定性输出，重跑字节一致） ----------

# 附录B.7 期望值总表（逐字照抄设计文档 v5，唯一数学权威）
B7_ROWS = [
    ("1", "A 底价", "附录A配置A", "B=5800.00，C=5132.74，增值税=0.00"),
    ("2", "A 加成10%", "r=10%", "Q=6380.00，利润513.27，加成10.00%，毛利9.09%"),
    ("3", "A 毛利率10%", "m=10%", "Q=6444.44，利润570.30，毛利10.00%"),
    ("4", "B 底价", "附录A配置B", "B=4130.00，C=3654.87，增值税=130.00"),
    ("5", "B 加成10%", "r=10%", "Q=4543.00，利润365.49，加成10.00%，毛利9.09%"),
    ("6", "B 毛利率10%", "m=10%", "Q=4588.89，利润406.10，毛利10.00%"),
    ("7", "B 单项覆盖", "CPU 0%，其余12%加成", "Q=4490.00，利润318.58，整机加成8.72%"),
    ("8", "B 反算写回", "T=4555.55 加成", "r*≈10.3039%，CPU件1246.44，合计=4555.55"),
    ("9", "B 反算毛利率", "T=4588.89", "m* 显示10.00%"),
    ("10", "B 采购回写", "CPU实际1050普票", "C'=3704.87，B'=4186.50，真实利润315.49（侵蚀提示）"),
    ("11", "B 回写极端", "CPU实际2000普票", "真实利润 −634.51（红色警告）"),
    ("12", "数量舍入", "99.99×3普票，加成10%", "件底价338.97，件报价372.86"),
]


def _fmt(v) -> str:
    """报告单元格格式化（Decimal/列表/布尔→稳定字符串）。"""
    if isinstance(v, bool):
        return "是" if v else "否"
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_fmt(x) for x in v) + "]"
    return str(v)


def _cfg_table(cfg: list[tuple]) -> str:
    rows = ["| 部件 | 含税单价 | 数量 | 发票类型 |", "|---|---|---|---|"]
    rows += [f"| {n} | {p} | {q} | {inv} |" for n, p, q, inv in cfg]
    return "\n".join(rows)


def write_report(path: Path) -> None:
    """生成 docs/math-verification-report.md：独立重算 vs 程序输出 vs B.7 表逐项对照。

    确定性：不含运行时间戳/随机值，全部取自本次比对记录与附录A/B常量，
    重跑生成相同字节（避免 git churn）。独立侧不导入程序计算函数的口径不变。
    """
    passed = sum(1 for ok in _cases.values() if ok)
    total = len(_cases)
    bad = sum(1 for ok in _items if not ok)
    by_case: dict[str, list[dict]] = {}
    for rec in _records:
        by_case.setdefault(rec["case"], []).append(rec)
    ordered = sorted(by_case, key=lambda c: int(c.split()[0][1:]))  # 按行号 1..12

    L: list[str] = []
    L.append("# 数学验证报告（pc-quote-flow）")
    L.append("")
    L.append("> 依据：设计文档 v5 **附录B（唯一数学口径）** 与附录A虚构配置。")
    L.append("> 生成命令：`.venv/Scripts/python.exe scripts/verify_math.py --report docs/math-verification-report.md`")
    L.append("> 本报告为确定性输出（不含时间戳/随机值），重跑生成相同内容。")
    L.append("> **全部数字为附录A虚构样例，非真实报价数据（红线1）。**")
    L.append("")
    L.append("## 1. 验证方法")
    L.append("")
    L.append("- **独立侧**：按附录B公式用 Decimal 从头重算（ROUND_HALF_UP 舍入到分、中间量全精度），")
    L.append("  **不导入程序的 pricing/tax/money 计算函数**；pricing 仅作为被测程序调用，model 为纯数据类。")
    L.append("- **逐项比对**：程序输出 vs 独立重算 vs 附录B.7 期望值总表（给出表期望时三者须一致）。")
    L.append("- 行1/4 的不含税成本 C 与应缴增值税按 B.2 恒等式从程序底价导出比对：")
    L.append("  C = B/(1+t)；应缴增值税 = B − 采购合计（B = S+P+P×t）。")
    L.append("- 关键口径（附录B.1–B.5）：件底价贡献 专票=p×n、普票=p×n×(1+t)（全精度）；")
    L.append("  件报价 加成=round(f×(1+r))、毛利率=round(f÷(1−m))；整机报价 Q=Σ舍入后件报价；")
    L.append("  利润(不含税)=round((Q−B)/(1+t))；反解 r*=(T−B)/B、m*=(T−B)/T（全精度），")
    L.append("  写回尾差 δ=T−Σq 仅由底价最大件吸收；采购回写有效价回退链 实际→确认→报价时。")
    L.append("")
    L.append("## 2. 虚构夹具（附录A逐字）")
    L.append("")
    L.append("### 配置A（全专票）")
    L.append("")
    L.append(_cfg_table(CFG_A))
    L.append("")
    L.append("### 配置B（CPU 普票，其余专票）")
    L.append("")
    L.append(_cfg_table(CFG_B))
    L.append("")
    L.append("## 3. 附录B.7 期望值总表（逐字，人工核算对照基准）")
    L.append("")
    L.append("| # | 用例 | 输入 | 期望输出 |")
    L.append("|---|---|---|---|")
    for num, name, inp, out in B7_ROWS:
        L.append(f"| {num} | {name} | {inp} | {out} |")
    L.append("")
    L.append(f"## 4. 逐项对照（{total} 用例，{len(_items)} 项比对）")
    L.append("")
    b7_by_num = {num: (name, inp, out) for num, name, inp, out in B7_ROWS}
    for case in ordered:
        num = case.split()[0][1:]
        name, inp, out = b7_by_num[num]
        L.append(f"### 行{num} {name}")
        L.append("")
        L.append(f"输入：{inp}；B.7 期望：{out}")
        L.append("")
        L.append("| 比对项 | 程序输出 | 独立重算 | B.7表期望 | 结果 |")
        L.append("|---|---|---|---|---|")
        for rec in by_case[case]:
            tab = "—" if rec["table"] is None else _fmt(rec["table"])
            L.append(f"| {rec['item']} | {_fmt(rec['got'])} | {_fmt(rec['ind'])} | {tab} | "
                     f"{'PASS' if rec['ok'] else 'FAIL'} |")
        L.append("")
    L.append("## 5. 结论")
    L.append("")
    L.append(f"汇总：数学核对 **{passed}/{total} 用例 PASS**（{len(_items)} 项比对，失败 {bad} 项）。")
    L.append("")
    if passed == total and bad == 0:
        L.append("全部用例通过：程序输出与独立 Decimal 重算、附录B.7 期望值总表**三者一致**，")
        L.append("数学口径验证通过。可交用户/财务按 B.7 人工核算（建议手算抽查：")
        L.append("一件普票 1000×1.13=1130；一笔利润 (4543−4130)/1.13=365.49）。")
    else:
        L.append("**存在 FAIL 项（见上表），数学口径验证未通过**，须排障修复后重跑全部门禁。")
    L.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L), encoding="utf-8", newline="\n")


def main() -> int:
    print("独立数学交叉核对（附录B.7 期望值总表 12 行；独立侧不导入 pricing/tax/money 计算函数）")
    print("=" * 78)

    # 行1/4：底价
    case_floor("行1 A底价", CFG_A, "5800.00", "5132.74", "0.00")
    case_floor("行4 B底价", CFG_B, "4130.00", "3654.87", "130.00")

    # 行2/3/5/6：四数
    case_four("行2 A加成10%", CFG_A, "markup", "6380.00", "513.27", "10.00", "9.09")
    case_four("行3 A毛利率10%", CFG_A, "margin", "6444.44", "570.30", None, "10.00")
    case_four("行5 B加成10%", CFG_B, "markup", "4543.00", "365.49", "10.00", "9.09")
    case_four("行6 B毛利率10%", CFG_B, "margin", "4588.89", "406.10", None, "10.00")

    # 行7：单项覆盖（CPU 0%，其余 12% 加成）
    row = "行7 B单项覆盖"
    doc = mk_doc(CFG_B, rate="0.12")
    doc.lines[0].item_rate = D("0")
    dp = pricing.price_doc(doc.lines, "markup", doc.unified_rate, pricing.TaxProfile())
    ip = ind_price(doc.lines, "markup", doc.unified_rate)
    check(row, "件报价明细", dp.line_quotes, ip["line_quotes"])
    check(row, "整机报价Q", dp.quote, ip["quote"], D("4490.00"))
    check(row, "利润额(不含税)", dp.profit_excl, ip["profit"], D("318.58"))
    check(row, "整机加成率%", p2(dp.markup), p2(ip["markup"]), D("8.72"))

    # 行8：反算写回 T=4555.55（加成；先置单项覆盖/调整验证清除）
    row = "行8 B反算写回"
    doc = mk_doc(CFG_B)
    doc.lines[0].item_rate = D("0")
    doc.lines[1].quote_adjust = D("5")
    target = D("4555.55")
    summary = pricing.apply_reverse(doc, target, "markup", pricing.TaxProfile())
    dp = pricing.price_doc(doc.lines, doc.mode, doc.unified_rate, pricing.TaxProfile())
    rate, qs, drift, idx = ind_reverse_lines(mk_lines(CFG_B), target, "markup")
    check(row, "反解率(全精度)", doc.unified_rate, rate)
    check(row, "反解率显示%≈10.3039", p2(doc.unified_rate), p2(rate), D("10.30"))
    check(row, "件报价明细(含尾差吸收)", dp.line_quotes, qs)
    check(row, "CPU件报价", dp.line_quotes[0], qs[0], D("1246.44"))
    check(row, "合计=目标", dp.quote, target, target)
    check(row, "单项覆盖已清除", all(ln.item_rate is None for ln in doc.lines), True)
    check(row, "尾差仅最大底价件吸收", [ln.quote_adjust for ln in doc.lines],
          [drift if i == idx else D("0") for i in range(len(doc.lines))])
    check(row, "日志摘要含反算写回/尾差", ("反算写回" in summary and "尾差" in summary), True)

    # 行9：反算毛利率 T=4588.89（m* 显示 10.00%）
    row = "行9 B反算毛利率"
    doc = mk_doc(CFG_B)
    target = D("4588.89")
    pricing.apply_reverse(doc, target, "margin", pricing.TaxProfile())
    dp = pricing.price_doc(doc.lines, doc.mode, doc.unified_rate, pricing.TaxProfile())
    rate, qs, drift, idx = ind_reverse_lines(mk_lines(CFG_B), target, "margin")
    check(row, "反解率(全精度)", doc.unified_rate, rate)
    check(row, "m*显示%", p2(doc.unified_rate), p2(rate), D("10.00"))
    check(row, "合计=目标", dp.quote, target, target)
    check(row, "件报价明细(含尾差吸收)", dp.line_quotes, qs)

    # 行10/11：采购回写（CPU 实际 1050 / 2000，普票）
    for row, actual, real_tab, eroded_tab, negative_tab in (
        ("行10 B采购回写", "1050", "315.49", True, False),
        ("行11 B回写极端", "2000", "-634.51", True, True),
    ):
        doc = mk_doc(CFG_B)
        doc.lines[0].actual_price = D(actual)
        doc.lines[0].actual_invoice = "普票"
        a = pricing.actuals(doc, pricing.TaxProfile())
        lines = mk_lines(CFG_B)
        ip0 = ind_price(lines, "markup", D("0.10"))  # Q/预期利润固定=报价时口径（行5 已核对）
        c_tab, b_tab, real = ind_actuals(doc.lines, ip0["quote"])
        if row.startswith("行10"):
            check(row, "C'(不含税成本)", a.cost_excl, c_tab, D("3704.87"))
            check(row, "B'(确认后底价)", a.floor, b_tab, D("4186.50"))
        check(row, "真实利润", a.real_profit, real, D(real_tab))
        check(row, "预期利润(报价时口径)", a.expected_profit, ip0["profit"], D("365.49"))
        check(row, "侵蚀提示", a.eroded, real < ip0["profit"], eroded_tab)
        check(row, "红色警告", a.negative, real < 0, negative_tab)

    # 行12：数量舍入（99.99×3 普票，加成10%；全精度中间量）
    row = "行12 数量舍入"
    ln = model.QuoteLine(name="测试件", qty=3, unit_price=D("99.99"), invoice="普票")
    dp = pricing.price_doc([ln], "markup", D("0.10"), pricing.TaxProfile())
    f = D("99.99") * 3 * (1 + T)  # 338.9661 全精度
    check(row, "件底价(显示)", dp.line_floors, [r2(f)], [D("338.97")])
    check(row, "件报价(全精度算后舍入)", dp.line_quotes, [r2(f * D("1.1"))], [D("372.86")])

    print("=" * 78)
    passed = sum(1 for ok in _cases.values() if ok)
    total = len(_cases)
    bad = sum(1 for ok in _items if not ok)
    print(f"汇总: 数学核对 {passed}/{total} 用例 PASS（{len(_items)} 项比对，失败 {bad} 项）")
    return 0 if passed == total and bad == 0 else 1


if __name__ == "__main__":
    # 默认无参：门禁③行为不变（print 逐项结果＋退出码）。
    # --report PATH：额外生成确定性数学验证报告（docs/math-verification-report.md）。
    args = sys.argv[1:]
    report_path = None
    if args:
        if len(args) == 2 and args[0] == "--report":
            report_path = Path(args[1])
        else:
            print("用法: verify_math.py [--report PATH]")
            sys.exit(2)
    code = main()
    if report_path is not None:
        write_report(report_path)
        print(f"已生成数学验证报告: {report_path}")
    sys.exit(code)