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
from PySide6.QtCore import Qt

from pc_quote_flow import exports, identity, model, states, store, tax
from pc_quote_flow.ui.app import MainWindow
from pc_quote_flow.ui.dialogs import ReverseDialog

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


# ---- UI 层：编辑权 / 聚合 / 自动撤销（R46 §3/§4）------------------------------


@pytest.fixture
def reg_profile(tmp_path, monkeypatch):
    """预登记操作人（APPDATA→tmp_path）：跳过首次运行登记对话框。"""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    p = identity.Profile("测试客服", "销售客服", "XU-PC", "xuni")
    identity.save_profile(p)
    return p


def _hdr(m):
    return {m.headerData(c, Qt.Horizontal): c for c in range(m.columnCount())}


def test_customer_confirm_column_edit_rights(qtbot, reg_profile, cfg_b_lines):
    """销售视图「客户确认」可编辑（文本是/否＋CheckStateRole 勾选）；采购/审阅只读拒写。"""
    win = MainWindow(doc=_doc(cfg_b_lines))
    qtbot.addWidget(win)
    sm = win.sales_view.model
    idx = sm.index(0, _hdr(sm)["客户确认"])
    assert sm.flags(idx) & Qt.ItemIsEditable
    assert sm.data(idx, Qt.CheckStateRole) == Qt.Unchecked
    n0 = len(win.doc.logs)
    assert sm.setData(idx, "是", Qt.EditRole)
    assert win.doc.lines[0].customer_confirmed is True
    assert sm.data(idx, Qt.CheckStateRole) == Qt.Checked
    assert len(win.doc.logs) == n0 + 1  # 单件确认未达整单聚合 → 仅编辑一条
    # CheckStateRole 取消勾选
    assert sm.setData(idx, Qt.Unchecked, Qt.CheckStateRole)
    assert win.doc.lines[0].customer_confirmed is False
    # 采购/审阅：列存在但只读（视图编辑权划分，红线2 不做身份门禁）
    for m in (win.purchase_view.model, win.review_view.model):
        h = _hdr(m)
        assert "客户确认" in h
        pidx = m.index(0, h["客户确认"])
        assert not (m.flags(pidx) & Qt.ItemIsEditable)
        n1 = len(win.doc.logs)
        assert not m.setData(pidx, "是", Qt.EditRole)
        assert not m.setData(pidx, Qt.Checked, Qt.CheckStateRole)
        assert win.doc.lines[0].customer_confirmed is False
        assert len(win.doc.logs) == n1


def test_line_confirm_aggregate_status(qtbot, reg_profile, cfg_b_lines):
    """逐件聚合：全件勾→客户已确认＋整单框勾选；取消任一件→已报价＋整单框取消。"""
    win = MainWindow(doc=_doc(cfg_b_lines))
    qtbot.addWidget(win)
    sm = win.sales_view.model
    h = _hdr(sm)
    chk = win.sales_view.chk_customer_confirm
    assert not chk.isChecked()
    n0 = len(win.doc.logs)
    for r in range(9):
        assert sm.setData(sm.index(r, h["客户确认"]), "是", Qt.EditRole)
    assert all(ln.customer_confirmed for ln in win.doc.lines)
    assert win.doc.status == "客户已确认"
    assert chk.isChecked()
    # 9 条编辑＋1 条聚合流转（询价→客户已确认 非常规，只留痕不拦截）
    assert len(win.doc.logs) == n0 + 10
    assert win.doc.logs[-1].action.endswith("状态流转")
    assert "客户已确认" in win.doc.logs[-1].summary
    # 取消第 4 件 → 聚合破坏 → 已报价
    assert sm.setData(sm.index(3, h["客户确认"]), "否", Qt.EditRole)
    assert win.doc.lines[3].customer_confirmed is False
    assert win.doc.status == "已报价"
    assert not chk.isChecked()
    assert len(win.doc.logs) == n0 + 12  # 编辑＋流转各一条
    # 补回第 4 件 → 重新聚合
    assert sm.setData(sm.index(3, h["客户确认"]), "是", Qt.EditRole)
    assert win.doc.status == "客户已确认"
    assert chk.isChecked()


def test_whole_order_checkbox_toggle(qtbot, reg_profile, cfg_b_lines):
    """整单勾选框：勾→全件 True＋客户已确认；取消→全件 False＋已报价；各恰两条日志。"""
    win = MainWindow(doc=_doc(cfg_b_lines))
    qtbot.addWidget(win)
    chk = win.sales_view.chk_customer_confirm
    assert chk.objectName() == "chk_customer_confirm"
    assert not chk.isChecked()
    n0 = len(win.doc.logs)
    chk.click()
    assert all(ln.customer_confirmed for ln in win.doc.lines)
    assert win.doc.status == "客户已确认"
    assert chk.isChecked()
    assert len(win.doc.logs) == n0 + 2  # 勾选盖章＋聚合流转，无回环多余日志
    assert any(g.action == "客户确认" for g in win.doc.logs[n0:])
    n1 = len(win.doc.logs)
    chk.click()
    assert not any(ln.customer_confirmed for ln in win.doc.lines)
    assert win.doc.status == "已报价"
    assert not chk.isChecked()
    assert len(win.doc.logs) == n1 + 2
    assert any(g.action == "取消客户确认" for g in win.doc.logs[n1:])


def test_auto_revoke_on_price_field_edit(qtbot, reg_profile, cfg_b_lines):
    """报价/成本字段变更→该件确认自动撤销＋状态回已报价；供应商/链接不触发。"""
    win = MainWindow(doc=_doc(cfg_b_lines))
    qtbot.addWidget(win)
    chk = win.sales_view.chk_customer_confirm
    sm, pm = win.sales_view.model, win.purchase_view.model
    sh, ph = _hdr(sm), _hdr(pm)
    chk.click()
    assert win.doc.status == "客户已确认"
    # 销售侧：数量 / 单项利润率
    for header, val, r in (("数量", "2", 0), ("单项利润率", "12", 2)):
        chk.click() if not chk.isChecked() else None
        assert win.doc.status == "客户已确认"
        n0 = len(win.doc.logs)
        assert sm.setData(sm.index(r, sh[header]), val, Qt.EditRole)
        assert win.doc.lines[r].customer_confirmed is False
        assert win.doc.status == "已报价"
        assert not chk.isChecked()
        assert "客户确认已撤销" in win.doc.logs[-2].summary  # 编辑条含撤销摘要
        assert len(win.doc.logs) == n0 + 2  # 编辑＋聚合流转
    # 采购侧：含税成本单价 / 确认价
    for header, val, r in (("含税成本单价", "1100", 1), ("确认价", "1200", 3)):
        chk.click() if not chk.isChecked() else None
        assert win.doc.status == "客户已确认"
        assert pm.setData(pm.index(r, ph[header]), val, Qt.EditRole)
        assert win.doc.lines[r].customer_confirmed is False
        assert win.doc.status == "已报价"
        assert "客户确认已撤销" in win.doc.logs[-2].summary
    # 非价格字段：供应商 / 商品链接 不撤销
    chk.click() if not chk.isChecked() else None
    assert win.doc.status == "客户已确认"
    n0 = len(win.doc.logs)
    assert pm.setData(pm.index(4, ph["供应商"]), "虚构供应商", Qt.EditRole)
    assert win.doc.lines[4].customer_confirmed is True
    assert win.doc.status == "客户已确认"
    assert chk.isChecked()
    assert len(win.doc.logs) == n0 + 1  # 仅编辑，无流转
    assert "客户确认已撤销" not in win.doc.logs[-1].summary
    assert pm.setData(pm.index(5, ph["商品链接"]), "https://example.com/item", Qt.EditRole)
    assert win.doc.lines[5].customer_confirmed is True
    assert win.doc.status == "客户已确认"


def test_rate_change_revokes_all(qtbot, reg_profile, cfg_b_lines):
    """统一利润率改变所有件报价 → 全件撤销＋已报价。"""
    win = MainWindow(doc=_doc(cfg_b_lines))
    qtbot.addWidget(win)
    win.sales_view.chk_customer_confirm.click()
    assert win.doc.status == "客户已确认"
    win.txt_rate.setText("8")
    win.txt_rate.editingFinished.emit()
    assert not any(ln.customer_confirmed for ln in win.doc.lines)
    assert win.doc.status == "已报价"
    assert not win.sales_view.chk_customer_confirm.isChecked()
    assert "客户确认已撤销" in win.doc.logs[-2].summary  # 修改利润率条


def test_mode_change_revokes_all(qtbot, reg_profile, cfg_b_lines):
    """算法模式切换改变所有件报价 → 全件撤销＋已报价。"""
    win = MainWindow(doc=_doc(cfg_b_lines))
    qtbot.addWidget(win)
    win.sales_view.chk_customer_confirm.click()
    assert win.doc.status == "客户已确认"
    win.combo_mode.setCurrentText("销售毛利率")
    assert not any(ln.customer_confirmed for ln in win.doc.lines)
    assert win.doc.status == "已报价"


def test_reverse_writeback_revokes_all(qtbot, reg_profile, cfg_b_lines):
    """反算写回改变所有件报价 → 全件撤销＋已报价。"""
    win = MainWindow(doc=_doc(cfg_b_lines))
    qtbot.addWidget(win)
    win.sales_view.chk_customer_confirm.click()
    assert win.doc.status == "客户已确认"
    win.btn_reverse.click()
    dlg = win.findChild(ReverseDialog)
    assert dlg is not None
    dlg.txt_target.setText("4555.55")
    dlg.btn_writeback.click()
    assert not any(ln.customer_confirmed for ln in win.doc.lines)
    assert win.doc.status == "已报价"
    assert win.lbl_quote.text() == "4555.55"  # 数学口径不变（附录B.6 例5）


def test_checkbox_sync_after_load(qtbot, reg_profile, cfg_b_lines, tmp_path):
    """打开文件后整单框按聚合刷新：部分确认→不勾；全件确认→勾选。"""
    doc = _doc(cfg_b_lines)
    doc.lines[0].customer_confirmed = True
    path = tmp_path / "虚构配置B部分确认.xlsx"
    store.save(doc, path, _stamp())
    win = MainWindow(path=path)
    qtbot.addWidget(win)
    assert not win.sales_view.chk_customer_confirm.isChecked()
    doc2 = _doc(cfg_b_lines)
    for ln in doc2.lines:
        ln.customer_confirmed = True
    doc2.status = "客户已确认"
    path2 = tmp_path / "虚构配置B全确认.xlsx"
    store.save(doc2, path2, _stamp())
    win.load_file(path2)
    assert win.sales_view.chk_customer_confirm.isChecked()
    assert win.doc.status == "客户已确认"


# ---- UI 层：图标状态动作按钮（R46 §5：icon-only＋单按钮废弃/恢复切换）----------


def test_complete_purchase_button(qtbot, reg_profile, cfg_b_lines):
    """采购视图 btn_complete 图标按钮（icon-only＋tooltip）：采购中→已完成，
    盖章 action「完成采购」，标题同步。"""
    win = MainWindow(doc=_doc(cfg_b_lines))
    qtbot.addWidget(win)
    btn = win.purchase_view.btn_complete
    assert btn.objectName() == "btn_complete"
    assert btn.text() == ""  # icon-only（简报 §5.1）
    assert btn.toolTip() == "完成采购（状态→已完成）"
    assert not btn.icon().isNull()
    assert btn.isEnabled()
    win.doc.status = "采购中"
    n0 = len(win.doc.logs)
    btn.click()
    assert win.doc.status == "已完成"
    assert len(win.doc.logs) == n0 + 1
    g = win.doc.logs[-1]
    assert g.action == "完成采购"  # 采购中→已完成 常规
    assert "已完成" in g.summary
    assert "已完成" in win.windowTitle()
    assert btn.isEnabled()  # 点后不 disable（红线2）


def test_complete_purchase_nonstandard_not_blocked(qtbot, reg_profile, cfg_b_lines):
    """非常规流转（询价→已完成）不拦截：仍生效，仅日志加「非常规流转」前缀。"""
    win = MainWindow(doc=_doc(cfg_b_lines))
    qtbot.addWidget(win)
    assert win.doc.status == "询价"
    win.purchase_view.btn_complete.click()
    assert win.doc.status == "已完成"
    assert win.doc.logs[-1].action == "非常规流转：完成采购"


def test_discard_restore_toggle_button(qtbot, reg_profile, cfg_b_lines):
    """工具栏 btn_discard 单按钮切换：未废弃→废弃（action 废弃报价单）；
    已废弃→恢复（action 恢复报价单，非常规只留痕）；icon/tooltip 随状态切换。"""
    win = MainWindow(doc=_doc(cfg_b_lines))
    qtbot.addWidget(win)
    bd = win.btn_discard
    assert bd.objectName() == "btn_discard"
    assert bd.text() == ""  # icon-only（简报 §5.2）
    assert not bd.icon().isNull()
    win.doc.status = "已报价"
    win.refresh_pricing()
    assert bd.toolTip() == "废弃此报价单（状态→已废弃）"
    icon_before = bd.icon().cacheKey()
    n0 = len(win.doc.logs)
    bd.click()
    assert win.doc.status == "已废弃"
    assert len(win.doc.logs) == n0 + 1
    assert win.doc.logs[-1].action == "废弃报价单"  # 已报价→已废弃 常规
    assert "已废弃" in win.windowTitle()
    # 已废弃态：icon/tooltip 切换为「恢复」
    assert bd.toolTip() == "恢复（状态→已报价）"
    assert bd.icon().cacheKey() != icon_before
    bd.click()
    assert win.doc.status == "已报价"
    assert len(win.doc.logs) == n0 + 2
    assert win.doc.logs[-1].action == "非常规流转：恢复报价单"  # 已废弃→已报价 非常规不拦截
    assert "已报价" in win.windowTitle()
    assert bd.toolTip() == "废弃此报价单（状态→已废弃）"
    # 已完成→已废弃 亦常规可达
    win.doc.status = "已完成"
    win.refresh_pricing()
    bd.click()
    assert win.doc.status == "已废弃"
    assert win.doc.logs[-1].action == "废弃报价单"


def test_status_buttons_never_disabled(qtbot, reg_profile, cfg_b_lines):
    """红线2：任何状态下状态按钮恒可用（状态是备忘不是门禁）。"""
    win = MainWindow(doc=_doc(cfg_b_lines))
    qtbot.addWidget(win)
    for st in states.STATES:
        win.doc.status = st
        win.refresh_pricing()
        assert win.purchase_view.btn_complete.isEnabled()
        assert win.btn_discard.isEnabled()


def test_auto_revoke_extended_fields(qtbot, reg_profile, cfg_b_lines):
    """简报 §3 全撤销字段集：部件名/型号/发票类型/确认发票类型/实际成交价/
    实际发票类型 变更亦撤销该件确认（数量/成本/利润率/确认价另测）。"""
    win = MainWindow(doc=_doc(cfg_b_lines))
    qtbot.addWidget(win)
    chk = win.sales_view.chk_customer_confirm
    sm, pm = win.sales_view.model, win.purchase_view.model
    sh, ph = _hdr(sm), _hdr(pm)
    cases = [
        (sm, sh, "部件名", "虚构部件改名", 0),
        (sm, sh, "型号", "虚构型号X", 1),
        (pm, ph, "发票类型", None, 2),       # 取与现值相反的 专票/普票
        (pm, ph, "确认发票类型", "普票", 3),
        (pm, ph, "实际成交价", "1300", 4),
        (pm, ph, "实际发票类型", "专票", 5),
    ]
    for m, h, header, val, r in cases:
        if not chk.isChecked():
            chk.click()
        assert win.doc.status == "客户已确认"
        if val is None:  # 发票类型：取反，保证值确实改变
            val = "普票" if win.doc.lines[r].invoice == "专票" else "专票"
        n0 = len(win.doc.logs)
        assert m.setData(m.index(r, h[header]), val, Qt.EditRole), header
        assert win.doc.lines[r].customer_confirmed is False, header
        assert win.doc.status == "已报价", header
        assert "客户确认已撤销" in win.doc.logs[-2].summary, header
        assert len(win.doc.logs) == n0 + 2  # 编辑＋聚合流转


# ---- R47：逐件「客户确认」单元格鼠标可点（修复 R46 整单可勾、逐件点不动）----


def test_customer_confirm_cell_user_checkable(qtbot, reg_profile, cfg_b_lines):
    """R47：销售「客户确认」单元格 flags 须含 ItemIsUserCheckable（鼠标单击可切换）。

    缺此 flag 时 QStyledItemDelegate 仍渲染勾选框但不响应鼠标点击——整单框是真
    QCheckBox 不受影响，故 R46 出现「整单可勾、逐件点不动」。R46 测试经 setData
    程序化写入绕过了点击路径而全绿；本测试钉死鼠标可点的必要条件 flags。
    """
    win = MainWindow(doc=_doc(cfg_b_lines))
    qtbot.addWidget(win)
    sm = win.sales_view.model
    sf = sm.flags(sm.index(0, _hdr(sm)["客户确认"]))
    assert sf & Qt.ItemIsEditable
    assert sf & Qt.ItemIsUserCheckable          # 鼠标可点必要条件（R47 修复点）
    for view in (win.purchase_view, win.review_view):
        m = view.model
        f = m.flags(m.index(0, _hdr(m)["客户确认"]))
        assert not (f & Qt.ItemIsEditable)       # 只读展示
        assert not (f & Qt.ItemIsUserCheckable)  # 采购/审阅不可点


def test_customer_confirm_cell_mouse_click(qtbot, reg_profile, cfg_b_lines):
    """R47：鼠标单击销售「客户确认」单元格勾选框 → 该件确认翻转＋一条盖章（端到端可点）。

    钉死两处修复：① flags 含 ItemIsUserCheckable（委托才响应点击）；② setData 用
    Qt.CheckState(value) 归一（委托鼠标路径传 int 2，直接 ==Qt.Checked 对 int 判 False）。
    """
    from PySide6.QtWidgets import QStyle, QStyleOptionViewItem, QAbstractItemView
    win = MainWindow(doc=_doc(cfg_b_lines))
    qtbot.addWidget(win)
    win.resize(1500, 800)
    win.show()
    sm = win.sales_view.model
    idx = sm.index(0, _hdr(sm)["客户确认"])
    assert win.doc.lines[0].customer_confirmed is False
    view = win.sales_view.table
    view.scrollTo(idx, QAbstractItemView.EnsureVisible)  # 该列靠右，先滚进视口
    qtbot.wait(20)
    opt = QStyleOptionViewItem()
    opt.rect = view.visualRect(idx)
    opt.features = QStyleOptionViewItem.HasCheckIndicator
    opt.checkState = Qt.Unchecked
    check = view.style().subElementRect(QStyle.SE_ItemViewItemCheckIndicator, opt, view)
    n0 = len(win.doc.logs)
    qtbot.mouseClick(view.viewport(), Qt.LeftButton, pos=check.center())
    assert win.doc.lines[0].customer_confirmed is True   # 单击勾选框即翻转
    assert len(win.doc.logs) == n0 + 1                    # 编辑盖章（未全件确认，无聚合流转）
    qtbot.mouseClick(view.viewport(), Qt.LeftButton, pos=check.center())
    assert win.doc.lines[0].customer_confirmed is False  # 再点取消


def test_customer_confirm_setdata_int_checkstate(qtbot, reg_profile, cfg_b_lines):
    """R47：setData 经 CheckStateRole 传 int（委托鼠标路径 static_cast<int>）须正确翻转。

    PySide6 严格枚举 2 == Qt.Checked 为 False；须 Qt.CheckState(value) 归一，
    int 与枚举两种入参都兼容（R46 测试只传枚举故漏检鼠标 int 路径）。
    """
    win = MainWindow(doc=_doc(cfg_b_lines))
    qtbot.addWidget(win)
    sm = win.sales_view.model
    idx = sm.index(0, _hdr(sm)["客户确认"])
    assert sm.setData(idx, 2, Qt.CheckStateRole) is True   # int Checked
    assert win.doc.lines[0].customer_confirmed is True
    assert sm.setData(idx, 0, Qt.CheckStateRole) is True   # int Unchecked
    assert win.doc.lines[0].customer_confirmed is False
    assert sm.setData(idx, Qt.Checked, Qt.CheckStateRole) is True  # 枚举仍兼容
    assert win.doc.lines[0].customer_confirmed is True