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


def check(case: str, item: str, got, ind, table=None) -> None:
    """程序输出 vs 独立重算（vs B.7 表期望值，若给出）。"""
    ok = got == ind and (table is None or got == table)
    _items.append(ok)
    _cases[case] = _cases.get(case, True) and ok
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
    sys.exit(main())