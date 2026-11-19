# -*- coding: utf-8 -*-
"""R46 客户确认测试（TDD：先 RED 后 GREEN）。

数据层：customer_confirmed 字段往返 / 旧文件平滑迁移（缺「客户确认」列默认 False
不报错、不误报外部改动）/ 缺其他列仍 StoreError / 导出隔离（红线5）。
UI 层（聚合/自动撤销/编辑权/图标按钮）在后续阶段追加于本文件。
全虚构数据（附录A 配置B，conftest 夹具 cfg_b_lines 9 件）——红线1。
"""
from decimal import Decimal as D

import openpyxl
import pytest

from pc_quote_flow import exports, identity, model, store

CREATOR = identity.Profile("虚构操作员", "销售客服", "XU-PC", "xuni")


def _lines(cfg_b_lines):
    return [model.QuoteLine(name=d["name"], model=d["model"], qty=d["qty"],
                            unit_price=D(d["price"]), invoice=d["invoice"])
            for d in cfg_b_lines]


def _doc(cfg_b_lines):
    return model.QuoteDoc(config_name="虚构配置B", customer="示例客户",
                          quote_date="2026-11-18", valid_until="2026-12-31",
                          creator="虚构操作员", mode="markup", unified_rate=D("0.10"),
                          lines=_lines(cfg_b_lines))


def _stamp(action="创建文件", version=0):
    return identity.make_stamp(CREATOR, view="销售视图", action=action,
                               summary="虚构：创建", version=version)


# ---- 数据层：字段/列/迁移 ----------------------------------------------------


def test_hash_line_fields_include_customer_confirm():
    """HASH_LINE_FIELDS 由 LINE_COLS 派生，自动含「客户确认」（排除派生列）。"""
    assert "客户确认" in store.LINE_COLS
    assert "客户确认" in store.HASH_LINE_FIELDS
    # 位置：单项利润率后、件底价前（简报 §2.2）
    assert store.LINE_COLS.index("客户确认") == store.LINE_COLS.index("单项利润率") + 1


def test_customer_confirmed_field_roundtrip(cfg_b_lines, tmp_path):
    """新字段 save→load 往返保真：True/False 混合逐件保留。"""
    doc = _doc(cfg_b_lines)
    doc.lines[0].customer_confirmed = True
    doc.lines[2].customer_confirmed = True
    path = tmp_path / "虚构配置B.xlsx"
    store.save(doc, path, _stamp())
    loaded, warnings = store.load(path)
    assert not warnings
    assert [ln.customer_confirmed for ln in loaded.lines] == \
        [True, False, True, False, False, False, False, False, False]
    # 与采购侧遗留标志 confirmed 相互独立（不动「价格已确认」）
    assert all(ln.confirmed is False for ln in loaded.lines)


def test_load_legacy_file_missing_customer_confirm_column(cfg_b_lines, tmp_path):
    """旧文件迁移：缺「客户确认」列 → 全件默认 False、无 StoreError、
    哈希按旧字段集计算不误报「程序外被修改」；再保存即补全新格式。"""
    doc = _doc(cfg_b_lines)
    path = tmp_path / "虚构配置B旧格式.xlsx"
    store.save(doc, path, _stamp())
    # 手工构造旧格式：删「客户确认」列（若存在），按旧字段集重算内容哈希
    wb = openpyxl.load_workbook(path)
    ws = wb["部件明细"]
    hdr = {c.value: i + 1 for i, c in enumerate(ws[1])}
    if "客户确认" in hdr:
        ws.delete_cols(hdr["客户确认"])
    legacy_fields = [c for c in store.HASH_LINE_FIELDS if c != "客户确认"]
    ov = wb["报价总览"]
    oh = {c.value: i + 1 for i, c in enumerate(ov[1])}
    ov.cell(row=2, column=oh["内容哈希"]).value = store.content_hash(
        doc, line_fields=legacy_fields)
    wb.save(path)
    wb.close()
    loaded, warnings = store.load(path)
    assert not warnings  # 迁移不算外部改动
    assert len(loaded.lines) == 9
    assert all(ln.customer_confirmed is False for ln in loaded.lines)
    # 迁移后再保存 → 新列补齐，往返保真
    store.save(loaded, path, _stamp("保存", version=loaded.version))
    again, w2 = store.load(path)
    assert not w2
    assert all(ln.customer_confirmed is False for ln in again.lines)
    wb2 = openpyxl.load_workbook(path)
    assert "客户确认" in [c.value for c in wb2["部件明细"][1]]
    wb2.close()


def test_load_missing_other_column_still_error(cfg_b_lines, tmp_path):
    """迁移仅限「客户确认」：缺其他列仍 StoreError（保留 R23 安全）。"""
    doc = _doc(cfg_b_lines)
    path = tmp_path / "虚构配置B缺列.xlsx"
    store.save(doc, path, _stamp())
    wb = openpyxl.load_workbook(path)
    ws = wb["部件明细"]
    hdr = {c.value: i + 1 for i, c in enumerate(ws[1])}
    ws.delete_cols(hdr["数量"])
    wb.save(path)
    wb.close()
    with pytest.raises(store.StoreError, match="数量"):
        store.load(path)


# ---- 导出隔离（红线5）--------------------------------------------------------


def test_approval_export_contains_customer_confirm_column(cfg_b_lines, tmp_path):
    """审批文件经 store._build_workbook 自动带「客户确认」列（部件明细，是/否）。"""
    doc = _doc(cfg_b_lines)
    doc.lines[0].customer_confirmed = True
    path = tmp_path / "虚构配置B_审批.xlsx"
    exports.export_approval(doc, path, _stamp("导出审批文件"))
    wb = openpyxl.load_workbook(path)
    hdr = [c.value for c in wb["部件明细"][1]]
    assert "客户确认" in hdr
    col = hdr.index("客户确认") + 1
    assert wb["部件明细"].cell(row=2, column=col).value == "是"
    assert wb["部件明细"].cell(row=3, column=col).value == "否"
    wb.close()


def test_customer_purchase_export_isolation(cfg_b_lines, tmp_path):
    """客户单/采购单显式字段集不动：任何 sheet 任何单元格都不出现「客户确认」。"""
    doc = _doc(cfg_b_lines)
    pc = tmp_path / "虚构配置B_客户.xlsx"
    exports.export_customer(doc, pc, _stamp("导出客户报价单"))
    pp = tmp_path / "虚构配置B_采购.xlsx"
    exports.export_purchase(doc, pp, _stamp("导出采购单"))
    for p in (pc, pp):
        wb = openpyxl.load_workbook(p)
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                assert "客户确认" not in row, f"{p.name} 泄漏客户确认列"
        wb.close()