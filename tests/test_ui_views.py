# -*- coding: utf-8 -*-
"""Task 9 视图测试（采购/审阅/审批对话框）：真实 widget（qtbot），全虚构数据（附录A 配置B）。

简报五测试：test_purchase_link_opens / test_confirmed_floor_hint / test_review_readonly /
test_approval_dialog_writes / test_erosion_hint（期望值逐字见 task-9-brief.md:14）。
另钉死控制者裁定：R23① view 长名统一、R24 NM1/NM2 硬化、M4 对话框生命周期、
对照打开、双底价/真实利润守卫（B.5/B.6 虚构算例）。
模态 QMessageBox/QFileDialog 一律 monkeypatch；QDesktopServices.openUrl 捕获不外跳；
非模态对话框经按钮驱动（offscreen 无 exec 阻塞）。
"""
from decimal import Decimal as D
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import QFileDialog, QMessageBox

import pc_quote_flow.ui.purchase_view as pvmod
from pc_quote_flow import identity, model, store, tax
from pc_quote_flow.ui.app import MainWindow
from pc_quote_flow.ui.dialogs import ApprovalDialog, ReverseDialog
from pc_quote_flow.ui.purchase_view import PurchaseView
from pc_quote_flow.ui.review_view import ReviewView
from pc_quote_flow.ui.sales_view import SalesView

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_B = REPO_ROOT / "samples" / "虚构配置B.xlsx"


@pytest.fixture
def reg_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    p = identity.Profile("测试客服", "销售客服", "XU-PC", "xuni")
    identity.save_profile(p)
    return p


def lines(cfg_b_lines):
    # conftest 夹具为 dict 列表（name/model/qty/price/invoice），逐字段构造
    return [model.QuoteLine(name=d["name"], model=d["model"], qty=d["qty"],
                            unit_price=D(d["price"]), invoice=d["invoice"]) for d in cfg_b_lines]


def make_doc(cfg_b_lines):
    return model.QuoteDoc(config_name="虚构配置B", mode="markup", unified_rate=D("0.10"), lines=lines(cfg_b_lines))


def hdr(model_):
    return {model_.headerData(i, Qt.Horizontal): i for i in range(model_.columnCount())}


@pytest.fixture
def msgbox(monkeypatch):
    # Qt6 无 QMessageBox.info 静态便捷函数；本套件只涉及 warning/critical
    rec = {"warning": [], "critical": []}
    for k in rec:
        monkeypatch.setattr(QMessageBox, k, staticmethod(lambda *a, _k=k, **kw: rec[_k].append(a) or QMessageBox.Ok))
    return rec


# ---- 简报五测试（期望值逐字） ----------------------------------------------


def test_purchase_link_opens(qtbot, reg_profile, cfg_b_lines, monkeypatch):
    """R43：采购商品链接可编辑（双击回归默认编辑，不再打开浏览器）；
    右键「打开链接」→ QDesktopServices.openUrl。
    hang-safe：直构 PurchaseView（不走 MainWindow 事件循环）；右键菜单用 FakeMenu
    同步 trigger（offscreen 下真实 QMenu.exec 模态阻塞会挂起，绝不执行真实菜单）。"""
    doc = make_doc(cfg_b_lines)
    doc.lines[0].link = "https://example.com/item"
    pv = PurchaseView(doc, tax.TaxProfile())
    qtbot.addWidget(pv)
    m = pv.model
    h = hdr(m)
    idx = m.index(0, h["商品链接"])
    assert m.flags(idx) & Qt.ItemIsEditable  # R43：链接归采购编辑
    assert pv.table.contextMenuPolicy() == Qt.CustomContextMenu
    assert not hasattr(pv, "_on_double_clicked")  # 双击打开已移除，回归默认编辑
    captured = []
    monkeypatch.setattr(QDesktopServices, "openUrl",
                        staticmethod(lambda url: captured.append(url.toString()) or True))
    # 双击不再打开链接（编辑路径；内联编辑器非模态，offscreen 安全）
    pv.table.doubleClicked.emit(idx)
    assert captured == []
    # 打开逻辑直测：链接列 → openUrl；其他列/空链接 → 不打开
    pv._open_link(idx)
    assert captured == ["https://example.com/item"]
    pv._open_link(m.index(0, h["确认价"]))
    assert captured == ["https://example.com/item"]
    doc.lines[1].link = ""
    pv._open_link(m.index(1, h["商品链接"]))
    assert captured == ["https://example.com/item"]

    # 右键接线：FakeMenu 记录 addAction 并同步 trigger「打开链接」（QAction.trigger 直连不阻塞）
    class FakeMenu:
        def __init__(self, parent=None):
            self._acts = []

        def addAction(self, text):
            a = QAction(text)
            self._acts.append(a)
            return a

        def exec(self, *a, **k):
            for act in self._acts:
                if act.text() == "打开链接":
                    act.trigger()
            return None

    monkeypatch.setattr(pvmod, "QMenu", FakeMenu)
    monkeypatch.setattr(pv.table, "indexAt", lambda pos: idx)
    pv._on_context_menu(QPoint(0, 0))
    assert captured == ["https://example.com/item"] * 2
    # 空链接右键 → 不建菜单、不打开
    monkeypatch.setattr(pv.table, "indexAt", lambda pos: m.index(1, h["商品链接"]))
    pv._on_context_menu(QPoint(0, 0))
    assert captured == ["https://example.com/item"] * 2
    # 非链接列右键 → 不建菜单、不打开
    monkeypatch.setattr(pv.table, "indexAt", lambda pos: m.index(0, h["确认价"]))
    pv._on_context_menu(QPoint(0, 0))
    assert captured == ["https://example.com/item"] * 2


def test_purchase_cost_source_editable_stamps(qtbot, reg_profile, cfg_b_lines):
    """R43：成本/发票/供应商/平台/商品链接归采购编辑——setData 成功＋盖章 view=采购视图＋派生列重算。"""
    doc = make_doc(cfg_b_lines)
    win = MainWindow(doc=doc)
    qtbot.addWidget(win)
    win.show()
    win.tabs.setCurrentIndex(1)
    assert win.current_view() == "采购视图"
    m = win.purchase_view.model
    h = hdr(m)
    n0 = len(doc.logs)
    # 含税成本单价 1000→1100（普票）：件底价 1100×1.13=1243.00，件报价 1243×1.1=1367.30（附录B 口径）
    assert m.flags(m.index(0, h["含税成本单价"])) & Qt.ItemIsEditable
    assert m.setData(m.index(0, h["含税成本单价"]), "1100", Qt.EditRole)
    assert doc.lines[0].unit_price == D("1100")
    assert len(doc.logs) == n0 + 1
    last = doc.logs[-1]
    assert last.action == "编辑明细" and last.view == "采购视图"
    assert "含税成本单价" in last.summary
    assert m.data(m.index(0, h["件底价"]), Qt.DisplayRole) == "1243.00"
    assert m.data(m.index(0, h["件报价"]), Qt.DisplayRole) == "1367.30"
    assert win.lbl_floor.text() == "4243.00"   # 4130−1130+1243
    assert win.lbl_quote.text() == "4667.30"   # 4543−1243+1367.30
    # 发票类型/供应商/平台/商品链接：可编辑＋setData 盖章（view=采购视图）
    for header, field, val in (
        ("发票类型", "invoice", "专票"),
        ("供应商", "supplier", "虚构供应商"),
        ("平台", "platform", "虚构平台"),
        ("商品链接", "link", "https://example.com/item"),
    ):
        idx = m.index(0, h[header])
        assert m.flags(idx) & Qt.ItemIsEditable, header
        n1 = len(doc.logs)
        assert m.setData(idx, val, Qt.EditRole), header
        assert getattr(doc.lines[0], field) == val, header
        assert len(doc.logs) == n1 + 1
        assert doc.logs[-1].view == "采购视图" and doc.logs[-1].action == "编辑明细"
        assert header in doc.logs[-1].summary


def test_sales_cost_source_readonly(qtbot, reg_profile, cfg_b_lines):
    """R43：销售视图成本/发票/供应商/平台/商品链接只读（flags 无编辑位、setData 拒写）；
    部件名/型号/数量/单项利润率仍可编辑。直构 SalesView，避免 MainWindow 事件循环。"""
    doc = make_doc(cfg_b_lines)
    sv = SalesView(doc, tax.TaxProfile())
    qtbot.addWidget(sv)
    m = sv.model
    h = hdr(m)
    ln = doc.lines[0]
    for header, field in (
        ("含税成本单价", "unit_price"), ("发票类型", "invoice"),
        ("供应商", "supplier"), ("平台", "platform"), ("商品链接", "link"),
    ):
        idx = m.index(0, h[header])
        assert not (m.flags(idx) & Qt.ItemIsEditable), header
        old = getattr(ln, field)
        n0 = len(doc.logs)
        assert not m.setData(idx, "9999" if field == "unit_price" else "虚构改值", Qt.EditRole), header
        assert getattr(ln, field) == old, header
        assert len(doc.logs) == n0
    for header in ("部件名", "型号", "数量", "单项利润率"):
        assert m.flags(m.index(0, h[header])) & Qt.ItemIsEditable, header
    # 销售仍可编辑部件配置（数量 1→2 成功写入）
    assert m.setData(m.index(0, h["数量"]), "2", Qt.EditRole)
    assert ln.qty == 2


def test_sales_link_opens(qtbot, reg_profile, cfg_b_lines, monkeypatch):
    """R43：销售视图商品链接只读展示，双击打开浏览器看采购货源（不能改）。"""
    doc = make_doc(cfg_b_lines)
    doc.lines[0].link = "https://example.com/item"
    sv = SalesView(doc, tax.TaxProfile())
    qtbot.addWidget(sv)
    m = sv.model
    h = hdr(m)
    idx = m.index(0, h["商品链接"])
    assert not (m.flags(idx) & Qt.ItemIsEditable)  # 销售只读
    captured = []
    monkeypatch.setattr(QDesktopServices, "openUrl",
                        staticmethod(lambda url: captured.append(url.toString()) or True))
    sv.table.doubleClicked.emit(idx)
    assert captured == ["https://example.com/item"]
    # 双击其他列不打开链接
    sv.table.doubleClicked.emit(m.index(0, h["部件名"]))
    assert captured == ["https://example.com/item"]
    # 空链接双击 → 不调用 openUrl
    doc.lines[1].link = ""
    sv.table.doubleClicked.emit(m.index(1, h["商品链接"]))
    assert captured == ["https://example.com/item"]


def test_confirmed_floor_hint(qtbot, reg_profile, cfg_b_lines):
    """CPU 确认价 2000 普票 → 确认后底价 5260.00 > 客户报价 4543.00：红字提示可见，导出仍 enabled。"""
    doc = make_doc(cfg_b_lines)
    cpu = doc.lines[0]
    cpu.confirmed = True
    cpu.confirm_price = D("2000")
    cpu.confirm_invoice = "普票"
    win = MainWindow(doc=doc)
    qtbot.addWidget(win)
    win.show()
    win.tabs.setCurrentIndex(1)  # 采购 tab 须为当前页，isVisible 才沿父链成立
    pv = win.purchase_view
    assert pv.lbl_floor_at_quote.text() == "4130.00"   # 报价时口径 B（附录B.6 例3）
    assert pv.lbl_floor_confirmed.text() == "5260.00"  # 2000×1.13 + 3000 = 5260.00
    assert pv.lbl_quote.text() == "4543.00"
    assert pv.lbl_warning.isVisible()
    assert "已低于底价，请按公司流程审批" in pv.lbl_warning.text()
    assert "red" in pv.lbl_warning.styleSheet().lower()
    # 红线2：无权限门禁——警告不 disable 任何导出
    assert win.btn_export_customer.isEnabled()
    assert win.btn_export_approval.isEnabled()
    assert win.btn_export_purchase.isEnabled()


def test_review_readonly(qtbot, reg_profile, cfg_b_lines):
    """审阅视图全列只读（spec §13.10）；日志表亦只读；setData 拒写。"""
    doc = make_doc(cfg_b_lines)
    doc.logs.append(identity.make_stamp(reg_profile, view="销售视图", action="创建文件",
                                        summary="虚构：创建", version=0))
    rv = ReviewView(doc, tax.TaxProfile())
    qtbot.addWidget(rv)
    m = rv.model
    assert m.view == "审阅"
    for r in range(m.rowCount()):
        for c in range(m.columnCount()):
            assert not (m.flags(m.index(r, c)) & Qt.ItemIsEditable)
    h = hdr(m)
    assert not m.setData(m.index(0, h["确认价"]), "2000", Qt.EditRole)
    assert doc.lines[0].confirm_price is None
    assert not m.setData(m.index(0, h["部件名"]), "改名", Qt.EditRole)
    assert doc.lines[0].name == "CPU（散片）"
    # 修改日志表：行数=日志数，全列只读
    assert rv.log_model.rowCount() == len(doc.logs) == 1
    for c in range(rv.log_model.columnCount()):
        assert not (rv.log_model.flags(rv.log_model.index(0, c)) & Qt.ItemIsEditable)
    assert rv.log_model.data(rv.log_model.index(0, 0), Qt.DisplayRole) == doc.logs[0].time


def test_approval_dialog_writes(qtbot, reg_profile, cfg_b_lines):
    """ApprovalDialog 提交「同意」→ review.record_approval 写 doc（状态流转+审批记录+单条日志，R18①）。"""
    doc = make_doc(cfg_b_lines)
    doc.status = "待审批"  # 同意→采购中 为常规流转（states.NORMAL）
    win = MainWindow(doc=doc)
    qtbot.addWidget(win)
    win.tabs.setCurrentIndex(2)
    assert win.current_view() == "审阅视图"
    n0 = len(doc.logs)
    win.review_view.btn_approval.click()
    dlg = win.findChild(ApprovalDialog)
    assert dlg is not None
    dlg.combo_conclusion.setCurrentText("同意")
    dlg.txt_opinion.setText("虚构意见：价格可接受，同意采购")
    dlg.btn_ok.click()
    assert doc.status == "采购中"
    assert doc.approval_status == "已同意"
    assert doc.approver == "测试客服"
    assert doc.approval_opinion == "虚构意见：价格可接受，同意采购"
    assert len(doc.approvals) == 1
    assert doc.approvals[0].round == 1
    assert doc.approvals[0].conclusion == "同意"
    assert doc.approvals[0].opinion == "虚构意见：价格可接受，同意采购"
    assert doc.approvals[0].approver == "测试客服"
    # 单条留痕（record_approval 内部 states.transition 已 append，调用方不再追加，R18①）
    assert len(doc.logs) == n0 + 1
    last = doc.logs[-1]
    assert "审批记录" in last.action
    assert last.view == "审阅视图"          # R23①：长名统一
    assert last.operator == "测试客服"
    assert last.role == "销售客服"
    assert last.machine == "XU-PC"
    assert last.win_account == "xuni"
    assert "第1轮审批" in last.summary and "同意" in last.summary
    # 摘要块/采购顶部审批标签/日志表同步刷新
    assert "已同意" in win.review_view.lbl_sum_approval_status.text()
    assert "已同意" in win.purchase_view.lbl_approval_status.text()
    assert win.review_view.log_model.rowCount() == len(doc.logs)


def test_erosion_hint(qtbot, reg_profile, cfg_b_lines):
    """CPU 实际价 1050 → 真实利润 315.49（B.5 虚构算例）+ 侵蚀提示可见。"""
    doc = make_doc(cfg_b_lines)
    doc.lines[0].actual_price = D("1050")
    win = MainWindow(doc=doc)
    qtbot.addWidget(win)
    win.show()
    win.tabs.setCurrentIndex(1)
    pv = win.purchase_view
    assert pv.lbl_real_profit.text() == "315.49"
    assert pv.lbl_expected_profit.text() == "365.49"
    assert pv.lbl_erosion.isVisible()
    assert "侵蚀" in pv.lbl_erosion.text()
    assert "red" not in pv.lbl_real_profit.styleSheet().lower()  # 正利润不标红
    # 侵蚀仅提示，不阻止导出（红线2）
    assert win.btn_export_customer.isEnabled()


# ---- 控制者裁定与守卫补测 ---------------------------------------------------


def test_negative_profit_red(qtbot, reg_profile, cfg_b_lines):
    """B.6 例6 极端：CPU 实际 2000 → 真实利润 −634.51 红色，导出仍 enabled。"""
    doc = make_doc(cfg_b_lines)
    doc.lines[0].actual_price = D("2000")
    win = MainWindow(doc=doc)
    qtbot.addWidget(win)
    win.show()
    win.tabs.setCurrentIndex(1)
    pv = win.purchase_view
    assert pv.lbl_real_profit.text() == "-634.51"
    assert "red" in pv.lbl_real_profit.styleSheet().lower()
    assert pv.lbl_erosion.isVisible()
    assert win.btn_export_customer.isEnabled()


def test_purchase_edit_stamp_view(qtbot, reg_profile, cfg_b_lines):
    """采购视图编辑经 MainWindow 盖章 view=「采购视图」（R23①），真实利润面板联动。"""
    doc = make_doc(cfg_b_lines)
    win = MainWindow(doc=doc)
    qtbot.addWidget(win)
    win.show()
    win.tabs.setCurrentIndex(1)
    assert win.current_view() == "采购视图"
    m = win.purchase_view.model
    h = hdr(m)
    n0 = len(doc.logs)
    assert m.setData(m.index(0, h["实际成交价"]), "1050", Qt.EditRole)
    assert doc.lines[0].actual_price == D("1050")
    assert len(doc.logs) == n0 + 1
    last = doc.logs[-1]
    assert last.action == "编辑明细" and last.view == "采购视图"
    assert win.purchase_view.lbl_real_profit.text() == "315.49"
    assert win.purchase_view.lbl_erosion.isVisible()
    # 采购回写不动客户报价（报价时口径锁定）
    assert win.lbl_quote.text() == "4543.00"


def test_item_rate_display_noop(qtbot, reg_profile, cfg_b_lines):
    """R24 NM1：单项利润率按显示口径（pct2）相同的回车为 no-op，不改写全精度率、不留痕。"""
    doc = make_doc(cfg_b_lines)
    win = MainWindow(doc=doc)
    qtbot.addWidget(win)
    m = win.sales_view.model
    idx = m.index(0, hdr(m)["单项利润率"])
    assert m.setData(idx, "12.3456789", Qt.EditRole)
    assert doc.lines[0].item_rate == D("0.123456789")
    n0 = len(doc.logs)
    # 双击预填显示值 "12.35" 回车 → pct2 相同 → no-op（镜像 app.py 利润率回读守卫）
    assert m.data(idx, Qt.DisplayRole) == "12.35"
    assert not m.setData(idx, "12.35", Qt.EditRole)
    assert doc.lines[0].item_rate == D("0.123456789")
    assert len(doc.logs) == n0
    # 真实显示变化仍写入
    assert m.setData(idx, "12.36", Qt.EditRole)
    assert doc.lines[0].item_rate == D("0.1236")
    # 清空（→None 跟随统一率）是真实变化，允许
    assert m.setData(idx, "", Qt.EditRole)
    assert doc.lines[0].item_rate is None


def test_sync_rate_and_mode_non_finite(qtbot, reg_profile, cfg_b_lines, msgbox):
    """R24 NM2/OS3：非有限 unified_rate 下回读/编辑/模式切换不抛，显示降级。"""
    doc = make_doc(cfg_b_lines)
    win = MainWindow(doc=doc)
    qtbot.addWidget(win)
    win.doc.unified_rate = D("NaN")
    win._sync_rate_controls()  # 不抛 InvalidOperation
    assert win.txt_rate.text() == "—"
    win.refresh_pricing()      # 既有非有限守卫 → 计算错误面板
    assert "计算错误" in win.sales_view.lbl_warning.text()
    # 焦点离开合法输入 → 修复写回（旧值 NaN 时 pct2 比较须跳过）
    win.txt_rate.setText("10")
    win.txt_rate.editingFinished.emit()
    assert win.doc.unified_rate == D("0.10")
    assert win.doc.logs[-1].action == "修改利润率"
    # 非有限 doc 切毛利率模式 → 守卫拦截回退，不抛
    win.doc.unified_rate = D("Infinity")
    win.combo_mode.setCurrentText("销售毛利率")
    assert win.doc.mode == "markup"
    assert msgbox["warning"]
    win._sync_rate_controls()
    assert win.txt_rate.text() == "—"


def test_dialogs_delete_on_close(qtbot, reg_profile):
    """M4：ReverseDialog/ApprovalDialog 设 WA_DeleteOnClose，关闭后不残留子对象。"""
    win = MainWindow(path=SAMPLE_B)
    qtbot.addWidget(win)
    win.btn_reverse.click()
    dlg = win.findChild(ReverseDialog)
    assert dlg is not None
    assert dlg.testAttribute(Qt.WA_DeleteOnClose)
    dlg.txt_target.setText("4555.55")
    dlg.btn_writeback.click()  # accept → 关闭即销毁
    qtbot.wait(20)
    assert win.findChild(ReverseDialog) is None
    win.tabs.setCurrentIndex(2)
    win.review_view.btn_approval.click()
    adlg = win.findChild(ApprovalDialog)
    assert adlg is not None
    assert adlg.testAttribute(Qt.WA_DeleteOnClose)
    adlg.btn_cancel.click()
    qtbot.wait(20)
    assert win.findChild(ApprovalDialog) is None


def test_compare_open(qtbot, tmp_path, reg_profile, cfg_b_lines, monkeypatch, msgbox):
    """对照打开：选第二份文件 → 新 MainWindow（同一 profile）；失败中文提示不崩溃。"""
    doc2 = make_doc(cfg_b_lines)
    doc2.config_name = "虚构配置B对照"
    path2 = tmp_path / "虚构配置B对照.xlsx"
    creator = identity.make_stamp(reg_profile, view="销售视图", action="创建文件",
                                  summary="虚构：创建", version=0)
    store.save(doc2, path2, creator)
    win = MainWindow(path=SAMPLE_B)
    qtbot.addWidget(win)
    win.tabs.setCurrentIndex(2)
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(path2), "")))
    win.review_view.btn_compare.click()
    assert len(win._compare_windows) == 1
    w2 = win._compare_windows[0]
    qtbot.addWidget(w2)
    assert w2.doc.config_name == "虚构配置B对照"
    assert w2.profile == win.profile      # 同一注册身份
    assert w2.path == path2
    assert w2.lbl_quote.text() == "4543.00"
    assert w2.isVisible()
    # 失败路径：不存在的文件 → 中文 critical，不新建窗口、不崩溃
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(tmp_path / "不存在.xlsx"), "")))
    win.review_view.btn_compare.click()
    assert len(win._compare_windows) == 1
    assert msgbox["critical"] and "对照打开失败" in msgbox["critical"][-1][1]  # a=(parent,标题,正文)


def test_empty_doc_views_no_crash(qtbot, reg_profile):
    """空明细守卫：采购面板 0.00/—、审阅摘要降级提示，均不抛（review.summary 空明细会抛）。"""
    win = MainWindow()  # 新建 doc，lines 为空
    qtbot.addWidget(win)
    win.show()
    pv = win.purchase_view
    assert pv.lbl_floor_at_quote.text() == "0.00"
    assert pv.lbl_floor_confirmed.text() == "0.00"
    assert pv.lbl_real_profit.text() == "—"
    assert not pv.lbl_warning.isVisible()
    win.tabs.setCurrentIndex(2)
    rv = win.review_view
    assert "空" in rv.lbl_sum_hint.text()
    assert rv.lbl_sum_floor.text() == "—"
    assert rv.lbl_sum_quote.text() == "—"


def test_review_summary_values(qtbot, reg_profile, cfg_b_lines):
    """审批摘要块消费 review.summary（B.6 例3 + 普票统计 + 极值件率）。"""
    doc = make_doc(cfg_b_lines)
    doc.customer = "虚构客户"
    doc.valid_until = "2026-12-31"
    win = MainWindow(doc=doc)
    qtbot.addWidget(win)
    rv = win.review_view
    assert rv.lbl_sum_config.text() == "虚构配置B"
    assert rv.lbl_sum_customer.text() == "虚构客户"
    assert rv.lbl_sum_status.text() == "询价"  # model.QuoteDoc.status 默认值（states.STATES 首态）
    assert rv.lbl_sum_approval_status.text() == "未提交"
    assert rv.lbl_sum_floor.text() == "4130.00"
    assert rv.lbl_sum_quote.text() == "4543.00"
    assert rv.lbl_sum_profit.text() == "365.49"
    assert rv.lbl_sum_markup.text() == "10.00%"
    assert rv.lbl_sum_margin.text() == "9.09%"
    assert "1" in rv.lbl_sum_ordinary.text() and "130.00" in rv.lbl_sum_ordinary.text()
    assert "CPU（散片）" in rv.lbl_sum_max_rate.text() and "10.00%" in rv.lbl_sum_max_rate.text()
    assert "CPU（散片）" in rv.lbl_sum_min_rate.text()
    assert rv.lbl_sum_below_floor.text() == "否"
    assert rv.lbl_sum_expired.text() == "否"
    assert rv.lbl_sum_valid_until.text() == "2026-12-31"
    assert rv.lbl_sum_version.text() == "0"


def test_purchase_view_standalone(qtbot, reg_profile, cfg_b_lines):
    """PurchaseView 可独立构造（doc, p），set_doc 重建模型（load_file 契约）。"""
    doc = make_doc(cfg_b_lines)
    pv = PurchaseView(doc, tax.TaxProfile())
    qtbot.addWidget(pv)
    assert pv.model.view == "采购"
    assert pv.model.rowCount() == 9
    doc2 = make_doc(cfg_b_lines)
    doc2.config_name = "虚构配置B二号"
    pv.set_doc(doc2)
    assert pv.doc is doc2
    assert pv.model.doc is doc2
    assert pv.model.rowCount() == 9


# ---- Fix Round 1（Important-1）：确认后底价去 confirmed 标志门禁 ----------------
# 根因：confirmed 列不在任何视图可编辑白名单（默认 False，仅文件往返可 True），
# 旧实现以 flag 门禁确认价 → 纯 GUI 录入的确认价永不进入确认后底价，
# 与 pricing._effective 确认阶段口径（None 合并回退）及 actuals 面板自相矛盾。


def test_confirmed_floor_gui_without_flag(qtbot, reg_profile, cfg_b_lines, msgbox):
    """纯 GUI 工作流：confirmed 保持默认 False，仅录入确认价/确认票种 →
    确认后底价用确认价 5260.00、红警告触发、导出仍 enabled（Important-1 回归）。"""
    doc = make_doc(cfg_b_lines)
    cpu = doc.lines[0]
    assert cpu.confirmed is False  # model 默认值；「价格已确认」列不可编辑，不得靠置位绕过
    cpu.confirm_price = D("2000")
    cpu.confirm_invoice = "普票"
    win = MainWindow(doc=doc)
    qtbot.addWidget(win)
    win.show()
    win.tabs.setCurrentIndex(1)  # 采购 tab 须为当前页，isVisible 才沿父链成立
    pv = win.purchase_view
    h = hdr(pv.model)
    # 修复不得偏离简报可编辑列清单：「价格已确认」仍仅显示
    assert not (pv.model.flags(pv.model.index(0, h["价格已确认"])) & Qt.ItemIsEditable)
    assert pv.lbl_floor_confirmed.text() == "5260.00"  # 2000×1.13 + 3000 = 5260.00
    # 与同屏 actuals 面板一致（未录实际价时 _effective 确认阶段同口径）
    assert pv.lbl_floor_effective.text() == "5260.00"
    assert pv.lbl_warning.isVisible()
    assert "已低于底价，请按公司流程审批" in pv.lbl_warning.text()
    # 红线2：警告不 disable 任何导出
    assert win.btn_export_customer.isEnabled()
    assert win.btn_export_approval.isEnabled()
    assert win.btn_export_purchase.isEnabled()


def test_confirmed_floor_none_fallback(qtbot, reg_profile, cfg_b_lines, msgbox):
    """对照：未录确认价（confirm_price=None）→ 确认后底价回退成本口径 4130.00，无警告。"""
    doc = make_doc(cfg_b_lines)
    cpu = doc.lines[0]
    assert cpu.confirm_price is None and cpu.confirmed is False
    win = MainWindow(doc=doc)
    qtbot.addWidget(win)
    win.show()
    win.tabs.setCurrentIndex(1)
    pv = win.purchase_view
    assert pv.lbl_floor_confirmed.text() == "4130.00"  # 成本口径 B（附录B.6 例3）
    assert not pv.lbl_warning.isVisible()
    assert win.btn_export_customer.isEnabled()


def test_confirmed_floor_invoice_only_fallback(qtbot, reg_profile, cfg_b_lines, msgbox):
    """仅录确认票种（未录确认价）→ 票种独立回退到确认层：CPU 1000 专票 → 4000.00。"""
    doc = make_doc(cfg_b_lines)
    cpu = doc.lines[0]
    assert cpu.confirm_price is None and cpu.confirmed is False
    cpu.confirm_invoice = "专票"
    win = MainWindow(doc=doc)
    qtbot.addWidget(win)
    win.show()
    win.tabs.setCurrentIndex(1)
    pv = win.purchase_view
    assert pv.lbl_floor_confirmed.text() == "4000.00"  # 1000×1 + 3000 = 4000.00
    assert not pv.lbl_warning.isVisible()  # 4000.00 < 报价 4543.00
