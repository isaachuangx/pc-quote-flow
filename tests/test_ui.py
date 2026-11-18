"""UI 外壳测试（task-8-brief Step 1）：附录A虚构夹具 + samples 虚构样例。

brief 七测试名与最小断言逐字照做；另加一条模型编辑留痕测试钉死 R22⑧/R22⑨
（setData 编辑→盖章日志+重算刷新；派生列只读；审阅视图全只读）。
红线1：只用虚构数据（cfg_b_lines/samples/虚构配置B.xlsx）+ tmp_path；
monkeypatch APPDATA→tmp_path，真实 profile.json 永不入库。
GUI 离屏渲染由 conftest.py:11 设置（QT_QPA_PLATFORM=offscreen）。
"""
import subprocess
import sys
from decimal import Decimal as D
from pathlib import Path

import openpyxl
import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from pc_quote_flow import identity, model, pricing, store
from pc_quote_flow.ui.app import MainWindow
from pc_quote_flow.ui.dialogs import RegisterDialog, ReverseDialog
from pc_quote_flow.ui.table_model import QuoteTableModel

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_B = REPO_ROOT / "samples" / "虚构配置B.xlsx"


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


def lines(dicts: list[dict]) -> list[model.QuoteLine]:
    """夹具 dict → QuoteLine（price→unit_price，保留原始票种）。"""
    return [
        model.QuoteLine(
            name=l["name"], model=l["model"], qty=l["qty"],
            unit_price=D(l["price"]), invoice=l["invoice"],
        )
        for l in dicts
    ]


def make_doc(cfg_b_lines: list[dict]) -> model.QuoteDoc:
    """虚构配置B + markup10 默认口径（与 samples/虚构配置B.xlsx 一致）。"""
    return model.QuoteDoc(
        config_name="虚构配置B",
        customer="示例客户",
        quote_date="2026-11-18",
        valid_until="2026-12-31",
        creator="虚构操作员",
        mode="markup",
        unified_rate=D("0.10"),
        lines=lines(cfg_b_lines),
    )


# ---- brief 七测试（名与最小断言逐字 task-8-brief Step 1）----


def test_first_run_registration(qtbot, tmp_path, monkeypatch):
    # MainWindow 构造→RegisterDialog 出现，填"测试客服"/销售客服→profile.json 生成
    monkeypatch.setenv("APPDATA", str(tmp_path))
    seen = []

    def fill():
        dlg = QApplication.activeModalWidget()
        seen.append(dlg)
        if not isinstance(dlg, RegisterDialog):
            return
        # 预填与只读 OS 锚点（R17①/R22④：Profile 四字段）
        assert dlg.txt_name.text() == identity.windows_account()
        assert dlg.combo_role.currentText() == "销售客服"
        assert dlg.txt_machine.isReadOnly()
        assert dlg.txt_machine.text() == identity.machine_name()
        assert dlg.txt_win.isReadOnly()
        assert dlg.txt_win.text() == identity.windows_account()
        dlg.txt_name.setText("测试客服")
        dlg.btn_ok.click()

    QTimer.singleShot(0, fill)
    win = MainWindow()
    qtbot.addWidget(win)
    assert seen and isinstance(seen[0], RegisterDialog)
    assert (tmp_path / "pc-quote-flow" / "profile.json").is_file()
    p = identity.load_profile()
    assert p == identity.Profile(
        name="测试客服", role="销售客服",
        machine=identity.machine_name(), win_account=identity.windows_account(),
    )
    assert win.profile == p
    assert "测试客服" in win.lbl_operator.text()


def test_four_numbers_update(qtbot, reg_profile):
    # 打开 samples/虚构配置B.xlsx，txt_rate 设"10"模式成本加成→四数逐字（R22②）
    win = MainWindow(path=SAMPLE_B)
    qtbot.addWidget(win)
    assert win.lbl_floor.text() == "4130.00"
    # 先改 8% 验证刷新真实发生（4130×1.08 逐件舍入求和=4460.40）
    win.txt_rate.setText("8")
    win.txt_rate.editingFinished.emit()
    assert win.lbl_quote.text() == "4460.40"
    win.txt_rate.setText("10")
    win.txt_rate.editingFinished.emit()
    # 模式切换真实生效：毛利率10% → Q=4588.89（附录B.7 #6），再切回成本加成
    win.combo_mode.setCurrentText("销售毛利率")
    assert win.lbl_quote.text() == "4588.89"
    assert win.lbl_profit.text() == "406.10"
    win.combo_mode.setCurrentText("成本加成")
    assert win.doc.unified_rate == D("0.10") and win.doc.mode == "markup"
    assert win.lbl_floor.text() == "4130.00"
    assert win.lbl_quote.text() == "4543.00"
    assert win.lbl_profit.text() == "365.49"
    assert win.lbl_markup.text() == "10.00%"
    assert win.lbl_margin.text() == "9.09%"


def test_below_floor_warning_not_block(qtbot, reg_profile):
    # rate −5→lbl_warning 可见且红色样式、导出按钮 isEnabled（红线2/R22⑩）
    win = MainWindow(path=SAMPLE_B)
    qtbot.addWidget(win)
    win.show()
    win.txt_rate.setText("-5")
    win.txt_rate.editingFinished.emit()
    dp = pricing.price_doc(win.doc.lines, win.doc.mode, win.doc.unified_rate, win.p)
    assert dp.quote < dp.floor
    assert win.lbl_warning.isVisible()
    assert "red" in win.lbl_warning.styleSheet().lower()
    assert "低于底价" in win.lbl_warning.text()
    assert win.btn_export_customer.isEnabled()
    assert win.btn_export_approval.isEnabled()
    assert win.btn_export_purchase.isEnabled()


def test_reverse_writeback(qtbot, reg_profile):
    # ReverseDialog 目标 4555.55 写回→doc 整机报价 4555.55（附录B.6 例5）
    win = MainWindow(path=SAMPLE_B)
    qtbot.addWidget(win)
    win.btn_reverse.click()
    dlg = win.findChild(ReverseDialog)
    assert dlg is not None
    dlg.txt_target.setText("4555.55")
    dlg.btn_preview.click()
    assert "10.30" in dlg.lbl_rev_rate.text()  # r*=425.55/4130≈10.3039%
    dlg.btn_writeback.click()
    # R22①：apply_reverse 返回文本→一条新鲜盖章，不双重 append
    last = win.doc.logs[-1]
    assert last.action == "反算写回"
    assert "4555.55" in last.summary and "尾差" in last.summary
    assert last.operator == "测试客服" and last.view == "销售"
    dp = pricing.price_doc(win.doc.lines, win.doc.mode, win.doc.unified_rate, win.p)
    assert dp.quote == D("4555.55")
    assert win.lbl_quote.text() == "4555.55"
    assert win.doc.lines[0].quote_adjust == D("0.01")  # 尾差→底价最大件 CPU
    assert all(ln.item_rate is None for ln in win.doc.lines)
    assert win.txt_rate.text() == "10.30"  # 写回后统一率同步显示


def test_selftest_flag():
    # subprocess 跑 python -m pc_quote_flow --selftest→returncode 0 且 stdout 含 SELFTEST OK
    proc = subprocess.run(
        [sys.executable, "-m", "pc_quote_flow", "--selftest"],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
        encoding="utf-8", timeout=180,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "SELFTEST OK" in proc.stdout


def test_open_external_change_logs(qtbot, tmp_path, monkeypatch, cfg_b_lines, reg_profile):
    # store.save 生成文件后手改某单元格制造哈希不一致→MainWindow 打开→留痕（R15/R22⑤）
    doc = make_doc(cfg_b_lines)
    path = tmp_path / "虚构配置B.xlsx"
    creator = identity.Profile("虚构操作员", "销售客服", "XU-PC", "xuni")
    stamp = identity.make_stamp(creator, view="销售视图", action="创建文件", summary="虚构：创建", version=0)
    store.save(doc, path, stamp)
    # 程序外手改：CPU 含税成本单价 1000→1010（哈希字段，必触发警告）
    wb = openpyxl.load_workbook(path)
    ws = wb["部件明细"]
    hdr = {c.value: i + 1 for i, c in enumerate(ws[1])}
    ws.cell(row=2, column=hdr["含税成本单价"]).value = "1010"
    wb.save(path)
    wb.close()
    warned = []
    monkeypatch.setattr(
        QMessageBox, "warning",
        staticmethod(lambda parent, title, text, *a, **k: warned.append((title, text)) or QMessageBox.Ok),
    )
    win = MainWindow(path=path)
    qtbot.addWidget(win)
    assert warned and any("程序外被修改" in t for _, t in warned)
    assert win.doc.lines[0].unit_price == D("1010")
    last = win.doc.logs[-1]
    assert last.action == "打开文件"
    assert "程序外被修改" in last.summary
    assert last.operator == reg_profile.name == "测试客服"
    assert last.role == "销售客服"
    assert last.view == "销售视图"
    assert last.machine == identity.machine_name()
    assert last.win_account == identity.windows_account()
    assert last.version == win.doc.version == 1
    # warnings 为空则不额外记日志：干净打开样例（文件内仅 1 条创建日志）
    win2 = MainWindow(path=SAMPLE_B)
    qtbot.addWidget(win2)
    assert len(win2.doc.logs) == 1


def test_export_oserror_and_caller_save(qtbot, tmp_path, monkeypatch, cfg_b_lines, reg_profile):
    # monkeypatch Workbook.save 抛 OSError→点导出 UI 捕获提示不崩溃；
    # 恢复后导出客户报价单→调用方 store.save 使工作文件 version 递增（R21①/R20⑧）
    doc = make_doc(cfg_b_lines)
    work = tmp_path / "虚构配置B_工作.xlsx"
    creator = identity.Profile("虚构操作员", "销售客服", "XU-PC", "xuni")
    store.save(doc, work, identity.make_stamp(creator, view="销售视图", action="创建文件", summary="虚构：创建", version=0))
    win = MainWindow(path=work)
    qtbot.addWidget(win)
    v0 = win.doc.version
    assert v0 == 1
    out = tmp_path / "虚构配置B_客户_报价.xlsx"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName",
        staticmethod(lambda *a, **k: (str(out), "xlsx (*.xlsx)")),
    )
    critical = []
    monkeypatch.setattr(
        QMessageBox, "critical",
        staticmethod(lambda parent, title, text, *a, **k: critical.append((title, text)) or QMessageBox.Ok),
    )

    def boom(self, filename):
        raise OSError("虚构：文件被占用")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(openpyxl.workbook.Workbook, "save", boom)
        win.btn_export_customer.click()  # 不崩溃即通过第一关
    assert critical and any("导出失败" in title for title, _ in critical)
    assert win.doc.version == v0  # 失败不触发调用方 save
    assert not out.exists()
    assert win.lbl_quote.text() == "4543.00"  # 窗口仍可用
    # 恢复后导出成功→调用方 store.save 递增工作文件版本
    win.btn_export_customer.click()
    assert out.exists()
    assert win.doc.version == v0 + 1
    assert win.doc.logs[-1].action == "保存"
    loaded, warnings = store.load(work)
    assert loaded.version == v0 + 1 and not warnings


# ---- R22⑧/R22⑨ 钉死测试：模型编辑留痕 + 派生列只读 + 视图列过滤 ----


def test_model_edit_logs_and_refresh(qtbot, reg_profile):
    win = MainWindow(path=SAMPLE_B)
    qtbot.addWidget(win)
    m = win.sales_view.model
    assert isinstance(m, QuoteTableModel)
    hdr = {m.headerData(c, Qt.Horizontal): c for c in range(m.columnCount())}
    # 销售视图可编辑列（R22⑨ 清单逐字）
    for h in ("部件名", "型号", "数量", "含税成本单价", "发票类型", "供应商", "平台", "商品链接", "单项利润率"):
        assert m.flags(m.index(0, hdr[h])) & Qt.ItemIsEditable, h
    # 派生列只读
    for h in ("件底价", "件报价"):
        assert not (m.flags(m.index(0, hdr[h])) & Qt.ItemIsEditable), h
    # 审阅视图全列只读
    rm = QuoteTableModel(win.doc, "审阅", win.p)
    assert all(
        not (rm.flags(rm.index(r, c)) & Qt.ItemIsEditable)
        for r in range(rm.rowCount()) for c in range(rm.columnCount())
    )
    # 编辑 CPU 数量 1→2：字段写入+一条盖章+四数刷新（f=2260→B=5260.00，Q=5786.00）
    n0 = len(win.doc.logs)
    assert m.setData(m.index(0, hdr["数量"]), "2", Qt.EditRole)
    assert win.doc.lines[0].qty == 2
    assert len(win.doc.logs) == n0 + 1
    last = win.doc.logs[-1]
    assert last.action == "编辑明细" and last.operator == "测试客服"
    assert "数量" in last.summary and "1" in last.summary and "2" in last.summary
    assert win.lbl_floor.text() == "5260.00"
    assert win.lbl_quote.text() == "5786.00"
    assert m.data(m.index(0, hdr["件底价"]), Qt.DisplayRole) == "2260.00"
    assert m.data(m.index(0, hdr["件报价"]), Qt.DisplayRole) == "2486.00"
    # 非法输入拒绝（不改字段、不记日志）
    assert not m.setData(m.index(0, hdr["含税成本单价"]), "abc", Qt.EditRole)
    assert win.doc.lines[0].unit_price == D("1000")
    assert len(win.doc.logs) == n0 + 1
