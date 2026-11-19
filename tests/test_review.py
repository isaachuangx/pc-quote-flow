"""review 审批摘要与结论写回测试（task-7-brief Step 1）：附录A虚构夹具 + 附录B期望值。

数学口径以设计文档附录B为唯一权威（AGENTS.md 红线6）；
程序仅记录管理层结论与意见，不做审批决策/拦截/权限（红线2）。
brief 五测试名与断言逐字照抄；另加裁定 R18 钉死测试（不双重 append/
全精度件底价算率/普票口径/零底价防除零/非法日期），不放宽 brief 断言。
"""
from datetime import date, datetime
from decimal import Decimal as D

import pytest

from pc_quote_flow import identity, model, review, store, tax


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


def make_doc(name: str, line_dicts: list[dict], **kw) -> model.QuoteDoc:
    """参照 test_store.make_doc：虚构配置B + markup10 默认口径。"""
    defaults = dict(
        customer="示例客户",
        quote_date="2026-11-18",
        valid_until="2026-12-31",
        creator="虚构操作员",
        mode="markup",
        unified_rate=D("0.10"),
    )
    defaults.update(kw)
    return model.QuoteDoc(config_name=name, lines=lines(line_dicts), **defaults)


def boss_stamp(action: str, summary: str, version: int, when: datetime) -> model.LogEntry:
    """管理层盖章（identity.make_stamp，九字段齐全；now 固定便于断言时间）。"""
    prof = identity.Profile(name="虚构管理层", role="管理层", machine="XU-PC", win_account="xuni")
    return identity.make_stamp(prof, view="审阅视图", action=action, summary=summary, version=version, now=when)


# ---- brief 五测试（名与断言逐字 task-7-brief:13）----


def test_summary_b_values(cfg_b_lines):
    # markup10：floor 4130.00 / quote 4543.00 / profit 365.49 / ordinary_count 1 / impact 130.00 / below_floor False
    doc = make_doc("虚构配置B", cfg_b_lines)
    doc.version = 3
    s = review.summary(doc, tax.TaxProfile(), today=date(2026, 11, 18))
    assert s.floor == D("4130.00") and s.quote == D("4543.00")
    assert s.profit_excl == D("365.49")
    assert s.ordinary_count == 1 and s.ordinary_tax_impact == D("130.00")
    assert s.below_floor is False
    # 率全精度（红线3：显示层再 pct2，Summary 不舍入）
    assert s.markup == D("0.1") and s.margin == D(413) / D(4543)
    # 统一率下各件率并列 0.1，极值取首件（R18⑤）
    assert s.max_rate_line == ("CPU（散片）", D("0.1"))
    assert s.min_rate_line == ("CPU（散片）", D("0.1"))
    # 有效期透传与版本号（R18⑧）
    assert s.valid_until == "2026-12-31" and s.version == 3
    assert s.expired is False


def test_summary_extremes_with_override(cfg_b_lines):
    # CPU item_rate=0、其余 0.12 → min_rate_line==("CPU（散片）",0 全精度)，max 为首个 0.12 件"主板"
    doc = make_doc("虚构配置B", cfg_b_lines, unified_rate=D("0.12"))
    doc.lines[0].item_rate = D("0")
    s = review.summary(doc, tax.TaxProfile())
    assert s.min_rate_line == ("CPU（散片）", D("0"))
    assert s.max_rate_line == ("主板", D("0.12"))
    # 与 pricing 口径交叉核对（test_pricing.test_item_override 同夹具）
    assert s.quote == D("4490.00") and s.floor == D("4130.00")


def test_expired(cfg_b_lines):
    # valid_until="2026-11-17"，today=date(2026,11,18) → expired True
    doc = make_doc("虚构配置B", cfg_b_lines, valid_until="2026-11-17")
    s = review.summary(doc, tax.TaxProfile(), today=date(2026, 11, 18))
    assert s.expired is True and s.valid_until == "2026-11-17"
    # 空有效期 → False；当天未过期（严格大于才过期，R18⑧）
    doc.valid_until = ""
    assert review.summary(doc, tax.TaxProfile(), today=date(2026, 11, 18)).expired is False
    doc.valid_until = "2026-11-18"
    assert review.summary(doc, tax.TaxProfile(), today=date(2026, 11, 18)).expired is False


def test_approval_agree_then_reject(cfg_b_lines, tmp_path):
    # 初始"待审批"：同意→采购中（常规）；再驳回 采购中→已报价（非常规仍生效，红线2不拦截）
    doc = make_doc("虚构配置B", cfg_b_lines, status="待审批")
    p = tax.TaxProfile()
    s1 = boss_stamp("审批记录", "虚构：同意", doc.version, datetime(2026, 11, 18, 14, 5, 0))
    review.record_approval(doc, "同意", "虚构意见：利润率合理", s1, p)
    assert doc.status == "采购中" and doc.approvals[0].round == 1
    assert doc.approval_status == "已同意"
    assert doc.approver == "虚构管理层" and doc.approval_time == "2026-11-18T14:05:00"
    assert doc.approval_opinion == "虚构意见：利润率合理"
    # ApprovalRecord 八字段映射自 stamp（R18②）
    assert doc.approvals[0] == model.ApprovalRecord(
        round=1, time="2026-11-18T14:05:00", approver="虚构管理层", role="管理层",
        machine="XU-PC", win_account="xuni", conclusion="同意", opinion="虚构意见：利润率合理",
    )
    # transition 只 append 一次，不双重 append（R18①）；常规流转 action 无前缀
    assert len(doc.logs) == 1 and doc.logs[-1] is s1 and s1.action == "审批记录"
    s2 = boss_stamp("审批记录", "虚构：驳回", doc.version, datetime(2026, 11, 18, 15, 0, 0))
    review.record_approval(doc, "驳回", "虚构意见：请重新报价", s2, p)
    assert doc.status == "已报价" and doc.approvals[1].round == 2
    assert doc.approval_status == "已驳回" and doc.approval_opinion == "虚构意见：请重新报价"
    assert len(doc.logs) == 2 and doc.logs[-1] is s2
    assert s2.action == "非常规流转：审批记录"  # 采购中→已报价非常规，仅前缀留痕不拦截
    assert len(doc.approvals) == 2  # 多轮只 append（红线4）
    # 经 store.save/load 往返后 approvals 仍在
    path = tmp_path / "b.xlsx"
    store.save(doc, path, boss_stamp("保存", "虚构：保存", doc.version, datetime(2026, 11, 18, 15, 5, 0)))
    loaded, warnings = store.load(path)
    assert warnings == []
    assert loaded.approvals == doc.approvals and len(loaded.approvals) == 2
    assert loaded.status == "已报价" and loaded.approval_status == "已驳回"
    assert loaded.approver == "虚构管理层" and loaded.approval_opinion == "虚构意见：请重新报价"


def test_invalid_conclusion(cfg_b_lines):
    # "随便" → ValueError（中文消息）；非法结论不得改动 doc 任何字段
    doc = make_doc("虚构配置B", cfg_b_lines, status="待审批")
    stamp = boss_stamp("审批记录", "虚构：非法结论", doc.version, datetime(2026, 11, 18, 14, 5, 0))
    with pytest.raises(ValueError, match="结论"):
        review.record_approval(doc, "随便", "虚构意见", stamp, tax.TaxProfile())
    assert doc.approvals == [] and doc.logs == []
    assert doc.status == "待审批" and doc.approval_status == "未提交"


# ---- 裁定 R18 钉死测试（不放宽 brief 断言）----


def test_record_approval_needs_adjust(cfg_b_lines):
    # 需调整→已报价（待审批→已报价常规），总览审批状态"需调整"（R18③）
    doc = make_doc("虚构配置B", cfg_b_lines, status="待审批")
    stamp = boss_stamp("审批记录", "虚构：需调整", doc.version, datetime(2026, 11, 18, 14, 5, 0))
    review.record_approval(doc, "需调整", "虚构意见：内存换 32G", stamp, tax.TaxProfile())
    assert doc.status == "已报价" and doc.approval_status == "需调整"
    assert doc.approvals[0].conclusion == "需调整" and doc.approvals[0].round == 1
    assert len(doc.logs) == 1 and stamp.action == "审批记录"


def test_summary_below_floor_only_marks():
    # 整机报价低于底价：below_floor True，只标记不拦截（红线2），summary 正常返回
    ln = model.QuoteLine(name="虚构测试件", unit_price=D("100"), invoice="专票")
    doc = model.QuoteDoc(config_name="虚构", lines=[ln], unified_rate=D("-0.5"))
    s = review.summary(doc, tax.TaxProfile())
    assert s.floor == D("100.00") and s.quote == D("50.00")
    assert s.below_floor is True
    assert s.ordinary_count == 0 and s.ordinary_tax_impact == D("0.00")


def test_summary_rate_uses_full_precision_floor():
    # 件率 = 件报价/全精度件底价−1（R18⑤，红线3）：99.99×3 普票全精度底价 338.9661，
    # 件报价 372.86（test_pricing.test_rounding_99_99_qty3 同口径）；不得用显示舍入值 338.97
    ln = model.QuoteLine(name="虚构测试件", qty=3, unit_price=D("99.99"), invoice="普票")
    doc = model.QuoteDoc(config_name="虚构", lines=[ln], unified_rate=D("0.10"))
    s = review.summary(doc, tax.TaxProfile())
    assert s.max_rate_line == ("虚构测试件", D("372.86") / D("338.9661") - 1)
    assert s.min_rate_line == s.max_rate_line
    assert s.ordinary_count == 1 and s.ordinary_tax_impact == D("39.00")  # fen(299.97×0.13)


def test_summary_zero_floor_line_rate():
    # 件底价==0 的件率记 Decimal(0) 防除零（R18⑤）；整机底价非零时 summary 可算
    ln0 = model.QuoteLine(name="虚构零价件", unit_price=D("0"), invoice="专票")
    ln1 = model.QuoteLine(name="主板", unit_price=D("1000"), invoice="专票")
    doc = model.QuoteDoc(config_name="虚构", lines=[ln0, ln1], unified_rate=D("0.10"))
    s = review.summary(doc, tax.TaxProfile())
    assert s.min_rate_line == ("虚构零价件", D("0"))
    assert s.max_rate_line == ("主板", D("0.1"))


def test_summary_ordinary_alias_count():
    # 普票口径按 normalize_invoice 归一化计数（"普通发票"→普票，R18⑥）
    ln1 = model.QuoteLine(name="虚构件一", unit_price=D("100"), invoice="普票")
    ln2 = model.QuoteLine(name="虚构件二", unit_price=D("200"), invoice="普通发票")
    doc = model.QuoteDoc(config_name="虚构", lines=[ln1, ln2], unified_rate=D("0.10"))
    s = review.summary(doc, tax.TaxProfile())
    assert s.ordinary_count == 2 and s.ordinary_tax_impact == D("39.00")  # fen(300×0.13)


def test_expired_invalid_format(cfg_b_lines):
    # 非法日期格式 → ValueError（数据损坏，R18⑧，T8 UI 捕获）
    doc = make_doc("虚构配置B", cfg_b_lines, valid_until="不是日期")
    with pytest.raises(ValueError):
        review.summary(doc, tax.TaxProfile(), today=date(2026, 11, 18))


# ---- R45：审批摘要采购侧汇总（消费 pricing.actuals，附录B.5，不新造公式）----


def test_procurement_summary_confirmed_price(cfg_b_lines):
    # CPU 确认价 2000 普票、实际价未填：有效价=确认价口径（B.5 回退链），审批阶段即此口径
    doc = make_doc("虚构配置B", cfg_b_lines)
    doc.lines[0].confirm_price = D("2000")
    doc.lines[0].confirm_invoice = "普票"
    ps = review.procurement_summary(doc, tax.TaxProfile())
    assert ps.confirmed_floor == D("5260.00")  # = 3000 + 2000×1.13
    assert ps.confirmed_cost_incl == D("5000.00")  # Σ(确认价??成本价)×数量 = 2000 + 3000
    assert ps.cost_excl == D("4654.87")  # C' = 3000/1.13 + 2000
    assert ps.real_profit == D("-634.51")  # 4543/1.13 − C'
    assert ps.expected_profit == D("365.49")
    assert ps.eroded is True and ps.negative is True
    assert ps.below_confirmed_floor is True  # 4543.00 < 5260.00，仅标记不拦截（红线2）


def test_procurement_summary_no_confirm_fallback(cfg_b_lines):
    # 无确认价 → 回退报价时成本价：与报价侧口径一致，无侵蚀无负利润
    doc = make_doc("虚构配置B", cfg_b_lines)
    ps = review.procurement_summary(doc, tax.TaxProfile())
    assert ps.confirmed_floor == D("4130.00")
    assert ps.confirmed_cost_incl == D("4000.00")
    assert ps.cost_excl == D("3654.87")
    assert ps.real_profit == D("365.49")
    assert ps.expected_profit == D("365.49")
    assert ps.eroded is False and ps.negative is False
    assert ps.below_confirmed_floor is False


def test_procurement_summary_actual_price_chain(cfg_b_lines):
    # CPU 确认价 2000＋实际价 1050 普票：有效价取实际价（B.5），confirmed_floor 钉死有效价口径
    doc = make_doc("虚构配置B", cfg_b_lines)
    doc.lines[0].confirm_price = D("2000")
    doc.lines[0].confirm_invoice = "普票"
    doc.lines[0].actual_price = D("1050")
    doc.lines[0].actual_invoice = "普票"
    ps = review.procurement_summary(doc, tax.TaxProfile())
    assert ps.confirmed_floor == D("4186.50")  # = 3000 + 1050×1.13（有效价口径，非确认价 5260.00）
    assert ps.confirmed_cost_incl == D("5000.00")  # 确认成本合计仍按 确认价??成本价（不含实际价层）
    assert ps.cost_excl == D("3704.87")  # C' = 3000/1.13 + 1050（B.6 例6）
    assert ps.real_profit == D("315.49")
    assert ps.expected_profit == D("365.49")
    assert ps.eroded is True and ps.negative is False  # 315.49 < 365.49 侵蚀，但非负
    assert ps.below_confirmed_floor is False  # 4543.00 > 4186.50
