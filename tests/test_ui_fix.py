"""Task 8 修复波回归测试（fix round 1）：钉死审查报告三处 Important 行为缺陷。

Important-1：统一率显示回读静默截断全精度（反算写回后仅焦点离开即改价）。
Important-2：非有限 Decimal（NaN/Infinity/sNaN）未拒绝→未捕获 InvalidOperation＋
             NaN 持久化污染；同址硬化：unit_price≥0、qty≥1、部件名空串拒绝。
Important-3：data() 只处理 DisplayRole，EditRole 返回 None→双击编辑空编辑器＋
             空串回车清空部件名键列（store.load 将抛 StoreError）。

红线1：只用虚构数据（samples/虚构配置B.xlsx）+ tmp_path + monkeypatch APPDATA。
红线6：不放宽/跳过/删除既有断言；本文件为新增覆盖，既有 tests/test_ui.py 零改动。
GUI 离屏渲染由 conftest.py:11 设置；offscreen 不投递焦点事件，焦点离开以
editingFinished.emit() 忠实模拟（与既有 test_ui.py 同口径，信号即焦点离开所发）。
"""
from decimal import Decimal as D
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog, QLineEdit, QMessageBox, QStyleOptionViewItem, QStyledItemDelegate,
)

from pc_quote_flow import identity, store
from pc_quote_flow.ui.app import MainWindow
from pc_quote_flow.ui.dialogs import ReverseDialog

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_B = REPO_ROOT / "samples" / "虚构配置B.xlsx"
# 反算写回 T=4555.55 的全精度统一率（(4555.55−4130.00)/4130.00，28 位有效数字）
FULL_RATE = D("0.1030387409200968523002421308")


@pytest.fixture
def reg_profile(tmp_path, monkeypatch):
    """预登记操作人（APPDATA→tmp_path）：跳过首次运行登记对话框。"""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    p = identity.Profile(
        name="测试客服",
        role="销售客服",
        machine=identity.machine_name(),
        win_account=identity.windows_account(),
    )
    identity.save_profile(p)
    return p


@pytest.fixture
def msgbox(monkeypatch):
    """记录 QMessageBox 调用（避免模态阻塞），返回 {warning/critical/question: [...]}。"""
    rec = {"warning": [], "critical": [], "question": []}
    monkeypatch.setattr(
        QMessageBox, "warning",
        staticmethod(lambda parent, title, text, *a, **k: rec["warning"].append((title, text)) or QMessageBox.Ok),
    )
    monkeypatch.setattr(
        QMessageBox, "critical",
        staticmethod(lambda parent, title, text, *a, **k: rec["critical"].append((title, text)) or QMessageBox.Ok),
    )
    monkeypatch.setattr(
        QMessageBox, "question",
        staticmethod(lambda parent, title, text, *a, **k: rec["question"].append((title, text)) or QMessageBox.No),
    )
    return rec


def _hdr(m) -> dict:
    return {m.headerData(c, Qt.Horizontal): c for c in range(m.columnCount())}


# ---- Important-1：显示回读不得截断全精度统一率 ----


def test_rate_focus_leave_preserves_full_precision(qtbot, reg_profile):
    win = MainWindow(path=SAMPLE_B)
    qtbot.addWidget(win)
    # 反算写回 4555.55 → 全精度统一率 + 显示 10.30
    win.btn_reverse.click()
    dlg = win.findChild(ReverseDialog)
    assert dlg is not None
    dlg.txt_target.setText("4555.55")
    dlg.btn_writeback.click()
    assert win.doc.unified_rate == FULL_RATE
    assert win.lbl_quote.text() == "4555.55"
    assert win.txt_rate.text() == "10.30"
    n0 = len(win.doc.logs)
    # 仅聚焦再离开（文本未改）：editingFinished 即焦点离开所发信号
    win.txt_rate.setFocus()
    win.txt_rate.editingFinished.emit()
    assert win.doc.unified_rate == FULL_RATE, "显示回读不得截断全精度统一率（红线3）"
    assert win.lbl_quote.text() == "4555.55", "焦点离开不得改变写回目标价"
    assert len(win.doc.logs) == n0, "未修改不得新增「修改利润率」日志"
    # 防修过头：真实修改仍生效并留痕
    win.txt_rate.setText("10.31")
    win.txt_rate.editingFinished.emit()
    assert win.doc.unified_rate == D("0.1031")
    assert len(win.doc.logs) == n0 + 1
    assert win.doc.logs[-1].action == "修改利润率"


# ---- Important-2：非有限输入拒绝（三解析入口）＋范围检查＋守卫/捕获 ----


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity", "sNaN"])
def test_rate_rejects_non_finite(qtbot, reg_profile, msgbox, bad):
    win = MainWindow(path=SAMPLE_B)
    qtbot.addWidget(win)
    r0, n0 = win.doc.unified_rate, len(win.doc.logs)
    win.txt_rate.setText(bad)
    win.txt_rate.editingFinished.emit()
    assert win.doc.unified_rate == r0, f"txt_rate 输 {bad} 不得写入 doc"
    assert len(win.doc.logs) == n0, "非法输入不记日志"
    assert win.lbl_quote.text() == "4543.00", "四数不得被污染"
    assert win.txt_rate.text() == "10.00", "拒绝后回滚显示"
    assert msgbox["warning"] and "有限" in msgbox["warning"][-1][1]


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "sNaN", "-100"])
def test_model_rejects_bad_unit_price(qtbot, reg_profile, bad):
    win = MainWindow(path=SAMPLE_B)
    qtbot.addWidget(win)
    m = win.sales_view.model
    idx = m.index(0, _hdr(m)["含税成本单价"])
    n0 = len(win.doc.logs)
    assert not m.setData(idx, bad, Qt.EditRole), f"单价 {bad} 应拒绝"
    assert win.doc.lines[0].unit_price == D("1000")
    assert len(win.doc.logs) == n0
    assert win.lbl_quote.text() == "4543.00"


@pytest.mark.parametrize("bad", ["0", "-1"])
def test_model_rejects_zero_or_negative_qty(qtbot, reg_profile, bad):
    win = MainWindow(path=SAMPLE_B)
    qtbot.addWidget(win)
    m = win.sales_view.model
    idx = m.index(0, _hdr(m)["数量"])
    n0 = len(win.doc.logs)
    assert not m.setData(idx, bad, Qt.EditRole), f"数量 {bad} 应拒绝（qty≥1）"
    assert win.doc.lines[0].qty == 1
    assert len(win.doc.logs) == n0


def test_reverse_target_rejects_non_finite(qtbot, reg_profile, msgbox):
    win = MainWindow(path=SAMPLE_B)
    qtbot.addWidget(win)
    win.btn_reverse.click()
    dlg = win.findChild(ReverseDialog)
    assert dlg is not None
    received = []
    dlg.writeback_requested.connect(received.append)
    r0, n0 = win.doc.unified_rate, len(win.doc.logs)
    for bad in ("NaN", "Infinity", "sNaN"):
        dlg.txt_target.setText(bad)
        assert dlg._target() is None, f"目标价 {bad} 应被拒绝"
        dlg.btn_writeback.click()
        assert not received, "非法目标价不得发写回信号"
    assert win.doc.unified_rate == r0
    assert len(win.doc.logs) == n0
    assert len(msgbox["warning"]) >= 3


@pytest.mark.parametrize("bad", ["NaN", "Infinity"])
def test_refresh_survives_non_finite_doc(qtbot, reg_profile, bad):
    win = MainWindow(path=SAMPLE_B)
    qtbot.addWidget(win)
    win.doc.unified_rate = D(bad)  # 模拟历史污染文件载入后的状态
    win.refresh_pricing()  # 不得抛未捕获异常
    assert "计算错误" in win.lbl_warning.text()
    assert win.lbl_quote.text() == "—"


def test_save_file_catches_arithmetic_error(qtbot, tmp_path, reg_profile, msgbox):
    win = MainWindow(path=SAMPLE_B)
    qtbot.addWidget(win)
    win.path = tmp_path / "虚构配置B_工作.xlsx"
    win.doc.unified_rate = D("Infinity")  # pct2(Infinity) 抛 InvalidOperation
    v0, n0 = win.doc.version, len(win.doc.logs)
    assert win.save_file() is False
    assert msgbox["critical"] and "保存失败" in msgbox["critical"][-1][0]
    assert win.doc.version == v0 and len(win.doc.logs) == n0
    assert not win.path.exists()


def test_save_file_survives_nan_doc(qtbot, tmp_path, reg_profile):
    win = MainWindow(path=SAMPLE_B)
    qtbot.addWidget(win)
    win.path = tmp_path / "虚构配置B_工作.xlsx"
    win.doc.unified_rate = D("NaN")  # store 以 str 写 NaN 不抛；崩点在随后 refresh
    v0 = win.doc.version
    assert win.save_file() is True  # 不得抛未捕获异常
    assert win.doc.version == v0 + 1
    assert "计算错误" in win.lbl_warning.text(), "refresh 守卫应覆盖 set_pricing"


def test_export_catches_arithmetic_error(qtbot, tmp_path, monkeypatch, reg_profile, msgbox):
    win = MainWindow(path=SAMPLE_B)
    qtbot.addWidget(win)
    out = tmp_path / "虚构配置B_客户_报价.xlsx"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName",
        staticmethod(lambda *a, **k: (str(out), "xlsx (*.xlsx)")),
    )
    win.doc.unified_rate = D("NaN")  # export_customer 的 q<f 比较抛 InvalidOperation
    v0, n0 = win.doc.version, len(win.doc.logs)
    err = None
    try:
        win.btn_export_customer.click()
    except Exception as e:  # noqa: BLE001 - 测试须捕获任何未捕获异常
        err = e
    assert err is None, f"导出不得抛未捕获异常：{err!r}"
    assert not out.exists()
    assert win.doc.version == v0 and len(win.doc.logs) == n0
    assert msgbox["warning"] and "无法导出" in msgbox["warning"][-1][0]


# ---- Important-3：EditRole 预填（真实 delegate 链）＋部件名键列保护 ----


def test_editrole_prefills_editor_via_delegate(qtbot, reg_profile):
    win = MainWindow(path=SAMPLE_B)
    qtbot.addWidget(win)
    m = win.sales_view.model
    hdr = _hdr(m)
    # 样例供应商为空，先经合法编辑填值
    assert m.setData(m.index(0, hdr["供应商"]), "虚构供应商", Qt.EditRole)
    tv = win.sales_view.table
    delegate = tv.itemDelegate()
    assert isinstance(delegate, QStyledItemDelegate)
    for h in ("数量", "部件名", "含税成本单价", "供应商", "发票类型"):
        idx = m.index(0, hdr[h])
        disp = m.data(idx, Qt.DisplayRole)
        assert disp, h
        assert m.data(idx, Qt.EditRole) == disp, f"{h} EditRole 应返回与 DisplayRole 同值"
        editor = delegate.createEditor(tv, QStyleOptionViewItem(), idx)
        try:
            delegate.setEditorData(editor, idx)
            assert isinstance(editor, QLineEdit), h
            assert editor.text() == disp, f"{h} 双击编辑器应预填当前值而非空串"
        finally:
            editor.deleteLater()


def test_doubleclick_enter_noop_via_delegate(qtbot, reg_profile):
    win = MainWindow(path=SAMPLE_B)
    qtbot.addWidget(win)
    m = win.sales_view.model
    idx = m.index(0, _hdr(m)["部件名"])
    name0 = win.doc.lines[0].name
    n0 = len(win.doc.logs)
    tv = win.sales_view.table
    delegate = tv.itemDelegate()
    editor = delegate.createEditor(tv, QStyleOptionViewItem(), idx)
    delegate.setEditorData(editor, idx)
    delegate.setModelData(editor, m, idx)  # 模拟双击后直接回车提交
    editor.deleteLater()
    assert win.doc.lines[0].name == name0, "双击+回车不得清空部件名（store 键列）"
    assert len(win.doc.logs) == n0, "无变更不得记编辑日志"


def test_empty_name_commit_rejected_and_store_roundtrip(qtbot, tmp_path, reg_profile):
    win = MainWindow(path=SAMPLE_B)
    qtbot.addWidget(win)
    m = win.sales_view.model
    idx = m.index(0, _hdr(m)["部件名"])
    n0 = len(win.doc.logs)
    assert not m.setData(idx, "", Qt.EditRole), "部件名空串应拒绝（键列保护）"
    assert win.doc.lines[0].name == "CPU（散片）"
    assert len(win.doc.logs) == n0
    # 键列未被清空 → 工作文件仍可保存并打开（store.load 不抛 StoreError）
    path = tmp_path / "虚构配置B_工作.xlsx"
    stamp = identity.make_stamp(
        win.profile, view="销售视图", action="保存", summary="测试：键列保护", version=win.doc.version,
    )
    store.save(win.doc, path, stamp)
    loaded, warnings = store.load(path)
    assert loaded.lines[0].name == "CPU（散片）" and not warnings


def test_empty_optional_str_still_allowed(qtbot, reg_profile):
    # 防过度拒绝：可选文本字段（供应商）允许清空，只有部件名是键列
    win = MainWindow(path=SAMPLE_B)
    qtbot.addWidget(win)
    m = win.sales_view.model
    hdr = _hdr(m)
    assert m.setData(m.index(0, hdr["供应商"]), "虚构供应商", Qt.EditRole)
    n0 = len(win.doc.logs)
    assert m.setData(m.index(0, hdr["供应商"]), "", Qt.EditRole)
    assert win.doc.lines[0].supplier == ""
    assert len(win.doc.logs) == n0 + 1
