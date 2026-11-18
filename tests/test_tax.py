"""money/tax 计算核心测试：附录A虚构算例（数学口径见设计文档附录B）。"""
from decimal import Decimal as D

import pytest

from pc_quote_flow import tax, money


def test_appendix_a_totals(cfg_a_lines):
    p = tax.TaxProfile()
    floors = [tax.floor_contrib(D(l["price"]), l["qty"], tax.normalize_invoice(l["invoice"]), p) for l in cfg_a_lines]
    assert money.fen(sum(floors)) == D("5800.00")
    assert money.fen(sum(tax.cost_excl(D(l["price"]), l["qty"], tax.normalize_invoice(l["invoice"]), p) for l in cfg_a_lines)) == D("5132.74")


def test_appendix_b_totals(cfg_b_lines):
    p = tax.TaxProfile()
    floors = [tax.floor_contrib(D(l["price"]), l["qty"], tax.normalize_invoice(l["invoice"]), p) for l in cfg_b_lines]
    assert money.fen(sum(floors)) == D("4130.00")
    assert money.fen(sum(tax.cost_excl(D(l["price"]), l["qty"], tax.normalize_invoice(l["invoice"]), p) for l in cfg_b_lines)) == D("3654.87")
    # 普票件含税合计 P × 0.13 = 底价口径应缴增值税
    P = sum(D(l["price"]) * l["qty"] for l in cfg_b_lines if tax.normalize_invoice(l["invoice"]) == "普票")
    assert money.fen(P * D("0.13")) == D("130.00")


def test_normalize_jd_special():
    assert tax.normalize_invoice("京东专票") == "专票"


def test_fen_rounding():
    assert money.fen(D("338.9661")) == D("338.97")


def test_normalize_aliases():
    assert tax.normalize_invoice("专票") == "专票"
    assert tax.normalize_invoice("普票") == "普票"
    assert tax.normalize_invoice("普通发票") == "普票"


def test_normalize_unknown_raises():
    for s in ("", "电子发票", "增值税普通发票", "收据"):
        with pytest.raises(ValueError):
            tax.normalize_invoice(s)


def test_pct2():
    assert money.pct2(D("0.1")) == D("10.00")
    assert money.pct2(D("0.0909090909")) == D("9.09")


def test_tax_profile_defaults():
    """默认值钉死：rate=0.13（一般纳税人，v1 固定）；small_scale_rate=0.01
    （小规模征收率预留参数，spec §5/§8，v1 公式不使用）。"""
    p = tax.TaxProfile()
    assert p.rate == D("0.13")
    assert p.small_scale_rate == D("0.01")
