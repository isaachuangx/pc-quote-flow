"""pricing 报价计算测试（task-3-brief Step 1）：附录A虚构夹具 + 附录B期望值。

数学口径以设计文档附录B为唯一权威（AGENTS.md 红线6）。
brief 原文 reverse_rate(4543,4130)==D(370)/D(4130) 与附录B不符：
4543−4130=413，B.4 r*=T/B−1=413/4130=0.1（10%加成报价反解应恰回 10%），
本文件按附录B核算修正为 D(413)/D(4130)，依据见 task-3-report.md。
"""
from decimal import Decimal as D

from pc_quote_flow import model, money, pricing, tax


def lines(dicts: list[dict]) -> list[model.QuoteLine]:
    """夹具 dict → QuoteLine（保留原始票种，归一化在 tax 内部完成）。"""
    return [
        model.QuoteLine(
            name=l["name"],
            model=l["model"],
            qty=l["qty"],
            unit_price=D(l["price"]),
            invoice=l["invoice"],
        )
        for l in dicts
    ]


def test_appendix_b_markup10(cfg_b_lines):
    dp = pricing.price_doc(lines(cfg_b_lines), "markup", D("0.10"), tax.TaxProfile())
    assert dp.floor == D("4130.00") and dp.quote == D("4543.00")
    assert dp.profit_excl == D("365.49") and money.pct2(dp.margin) == D("9.09")


def test_appendix_b_margin10(cfg_b_lines):
    # quote 4588.89 / profit 406.10 / pct2(margin) 10.00（B.6 例3 / B.7 行6）
    dp = pricing.price_doc(lines(cfg_b_lines), "margin", D("0.10"), tax.TaxProfile())
    assert dp.floor == D("4130.00") and dp.quote == D("4588.89")
    assert dp.profit_excl == D("406.10") and money.pct2(dp.margin) == D("10.00")


def test_appendix_a_both_modes(cfg_a_lines):
    # markup10: 6380.00 / 513.27 / 9.09；margin10: 6444.44 / 570.30 / 10.00（B.6 例8 / B.7 行2/3）
    ls = lines(cfg_a_lines)
    dp = pricing.price_doc(ls, "markup", D("0.10"), tax.TaxProfile())
    assert dp.floor == D("5800.00") and dp.quote == D("6380.00")
    assert dp.profit_excl == D("513.27") and money.pct2(dp.margin) == D("9.09")
    assert money.pct2(dp.markup) == D("10.00")
    dp = pricing.price_doc(ls, "margin", D("0.10"), tax.TaxProfile())
    assert dp.quote == D("6444.44") and dp.profit_excl == D("570.30")
    assert money.pct2(dp.margin) == D("10.00")


def test_item_override(cfg_b_lines):
    ls = lines(cfg_b_lines)
    ls[0].item_rate = D("0")
    dp = pricing.price_doc(ls, "markup", D("0.12"), tax.TaxProfile())
    assert dp.line_quotes == [D(x) for x in ["1130.00", "1120.00", "448.00", "672.00", "560.00", "336.00", "112.00", "89.60", "22.40"]]
    assert dp.quote == D("4490.00") and dp.profit_excl == D("318.58") and money.pct2(dp.markup) == D("8.72")


def test_rounding_99_99_qty3():
    ln = model.QuoteLine(name="测试件", qty=3, unit_price=D("99.99"), invoice="普票")
    dp = pricing.price_doc([ln], "markup", D("0.10"), tax.TaxProfile())
    assert dp.line_floors == [D("338.97")] and dp.line_quotes == [D("372.86")]  # Review Focus 1：全精度 338.9661×1.1=372.86271→372.86


def test_apply_reverse_absorbs_drift(cfg_b_lines):
    doc = model.QuoteDoc(config_name="B", lines=lines(cfg_b_lines), mode="markup", unified_rate=D("0.10"))
    doc.lines[0].item_rate = D("0")
    summary = pricing.apply_reverse(doc, D("4555.55"), "markup", tax.TaxProfile())
    dp = pricing.price_doc(doc.lines, doc.mode, doc.unified_rate, tax.TaxProfile())
    assert dp.quote == D("4555.55") and dp.line_quotes[0] == D("1246.44")
    assert all(l.item_rate is None for l in doc.lines)
    assert "反算写回" in summary and "尾差" in summary  # Review Focus 5


def test_actuals_erosion(cfg_b_lines):
    doc = model.QuoteDoc(config_name="B", lines=lines(cfg_b_lines), mode="markup", unified_rate=D("0.10"))
    doc.lines[0].actual_price = D("1050")
    doc.lines[0].actual_invoice = "普票"
    a = pricing.actuals(doc, tax.TaxProfile())
    assert a.cost_excl == D("3704.87") and a.floor == D("4186.50")
    assert a.real_profit == D("315.49") and a.expected_profit == D("365.49")
    assert a.eroded and not a.negative


def test_actuals_negative(cfg_b_lines):
    # actual_price 2000 普票 → real_profit −634.51，negative True（B.6 例6极端 / B.7 行11）
    doc = model.QuoteDoc(config_name="B", lines=lines(cfg_b_lines), mode="markup", unified_rate=D("0.10"))
    doc.lines[0].actual_price = D("2000")
    doc.lines[0].actual_invoice = "普票"
    a = pricing.actuals(doc, tax.TaxProfile())
    assert a.real_profit == D("-634.51") and a.negative
    assert a.eroded and a.expected_profit == D("365.49")


def test_reverse_rate_full_precision():
    # B.4：r*=T/B−1、m*=1−B/T（全精度）。4543 是 B=4130 加成10% 的报价，反解恰回 0.1。
    assert pricing.reverse_rate(D("4543"), D("4130"), "markup") == D(413) / D(4130) == D("0.1")
    # 非平凡除法须逐位全精度相等（不得先舍入）
    assert pricing.reverse_rate(D("4555.55"), D("4130"), "markup") == D("425.55") / D("4130")
    assert pricing.reverse_rate(D("4588.89"), D("4130"), "margin") == D("458.89") / D("4588.89")
    assert money.pct2(pricing.reverse_rate(D("4588.89"), D("4130"), "margin")) == D("10.00")  # B.7 行9