# -*- coding: utf-8 -*-
"""终审唯一修复波（10 FIX）回归测试——全虚构数据（附录A 配置B），真实报价永不入库（红线1）。

覆盖（task-final-review.md 修复清单）：
- I3  导出后置 save_file 异常扩捕 (OSError, ArithmeticError, ValueError)：全零成本不崩；
- OS2 store.save fail-fast＋写失败回滚：全零成本/写盘失败不留幻影版本/日志/修改人/哈希；
- T6M1 三导出原子写（tmp+os.replace）＋写成功后才改 doc（approval 失败回滚）：无幻影审计；
- I2  采购确认后底价 NaN 守卫：confirm_price=NaN 文件 load→refresh 不抛、走计算错误面板；
- T3M1 apply_reverse 底价直接 Σfloor_contrib 绕率校验：margin＋件率≥1 可反算，floor 逐位不变；
- I1  非模态对话框 doc 绑定＋load_file 换 doc 关闭已开框：残留提交只作用框内 doc；
- T4.BAK load 回写豁免大小写不敏感：.BAK 不再被回写覆盖。
模态 QMessageBox/QFileDialog 一律 monkeypatch（offscreen 不阻塞事件循环）。
"""
import io
import os
from decimal import Decimal as D
from pathlib import Path

import openpyxl
import pytest
from PySide6.QtWidgets import QFileDialog, QMessageBox

from pc_quote_flow import exports, identity, model, money, pricing, store, tax
from pc_quote_flow.ui.app import MainWindow
from pc_quote_flow.ui.dialogs import ApprovalDialog, ReverseDialog


@pytest.fixture
def reg_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    p = identity.Profile("测试客服", "销售客服", "XU-PC", "xuni")
    identity.save_profile(p)
    return p


@pytest.fixture
def msgbox(monkeypatch):
    rec = {"warning": [], "critical": []}
    for k in rec:
        monkeypatch.setattr(QMessageBox, k, staticmethod(lambda *a, _k=k, **kw: rec[_k].append(a) or QMessageBox.Ok))
    return rec


def lines(cfg_b_lines):
    return [model.QuoteLine(name=d["name"], model=d["model"], qty=d["qty"],
                            unit_price=D(d["price"]), invoice=d["invoice"]) for d in cfg_b_lines]


def make_doc(cfg_b_lines):
    return model.QuoteDoc(config_name="虚构配置B", mode="markup", unified_rate=D("0.10"), lines=lines(cfg_b_lines))


def creator_stamp(profile):
    return identity.make_stamp(profile, view="销售视图", action="创建文件", summary="虚构：创建", version=0)


def save_second_doc(cfg_b_lines, profile, tmp_path, name="虚构配置B二号", status="询价"):
    """造第二份虚构工作文件（docB）供 load_file 切换。"""
    doc = make_doc(cfg_b_lines)
    doc.config_name = name
    doc.status = status
    path = tmp_path / f"{name}.xlsx"
    store.save(doc, path, creator_stamp(profile))
    return path


def _zero_doc():
    return model.QuoteDoc(config_name="虚构全零成本", lines=[
        model.QuoteLine(name="虚构件甲", qty=1, unit_price=D("0"), invoice="专票"),
        model.QuoteLine(name="虚构件乙", qty=2, unit_price=D("0"), invoice="专票"),
    ])


# ---- I3：导出后置 save 异常扩捕（全零成本 unit_price=0 合法） ----------------


def test_export_post_save_all_zero_no_crash(qtbot, tmp_path, reg_profile, monkeypatch, msgbox):
    """全零成本 purchase 导出成功→后置 store.save 抛 DivisionUndefined（ArithmeticError）：
    修复前 except OSError 漏捕崩溃；修复后 critical 提示『已导出但保存失败』，不崩。"""
    doc = _zero_doc()
    win = MainWindow(doc=doc, profile=reg_profile)
    qtbot.addWidget(win)
    work = tmp_path / "虚构全零.xlsx"
    win.path = work
    dest = tmp_path / "虚构全零_采购.xlsx"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(dest), "")))
    n0 = len(doc.logs)
    win.btn_export_purchase.click()  # 修复前：DivisionUndefined 逃逸
    assert dest.exists()             # 导出本身成功（purchase 不定价）
    assert not work.exists()         # 后置 save 失败，工作文件未落盘
    assert msgbox["critical"], "应走错误提示而非崩溃"
    # critical 元组=(parent, 标题, 正文)：正文须含『已导出…保存失败』
    assert "已导出" in msgbox["critical"][-1][2] and "保存失败" in msgbox["critical"][-1][2]
    # 导出留痕保留（导出确实发生）；save 失败不留幻影版本/日志（OS2 同族）
    assert len(doc.logs) == n0 + 1 and doc.logs[-1].action == "导出采购单"
    assert doc.version == 0


# ---- OS2：store.save fail-fast＋写失败回滚 ----------------------------------


def test_save_all_zero_fail_fast_no_phantom(cfg_b_lines, reg_profile, tmp_path):
    """全零成本 save：_price 抛 ArithmeticError 必须先于一切 mutation——
    version/logs/modifier/modify_time/content_hash/stamp.version 全不变、文件未落盘。"""
    doc = make_doc(cfg_b_lines)
    for ln in doc.lines:
        ln.unit_price = D("0")
    stamp = identity.make_stamp(reg_profile, view="销售视图", action="编辑明细", summary="虚构：全零", version=0)
    path = tmp_path / "虚构全零.xlsx"
    with pytest.raises(ArithmeticError):
        store.save(doc, path, stamp)
    assert doc.version == 0
    assert doc.logs == []
    assert doc.modifier == "" and doc.modify_time == ""
    assert doc.content_hash == ""
    assert stamp.version == 0
    assert not path.exists()
    # tmp_path 内不得有任何工作文件产物（reg_profile 的 APPDATA 档案目录除外）
    assert not list(tmp_path.glob("*.xlsx")) and not list(tmp_path.glob("*.tmp")) \
        and not list(tmp_path.glob("*.bak"))


def test_save_wb_failure_rolls_back(cfg_b_lines, reg_profile, tmp_path, monkeypatch):
    """wb.save 写一半失败（OSError）：mutation 全回滚、tmp 清理、无目标文件。"""
    doc = make_doc(cfg_b_lines)
    stamp = identity.make_stamp(reg_profile, view="销售视图", action="编辑明细", summary="虚构", version=0)
    path = tmp_path / "虚构配置B.xlsx"

    def partial_save(wb, filename):
        Path(filename).write_bytes(b"partial")
        raise OSError("模拟磁盘满")

    monkeypatch.setattr(openpyxl.Workbook, "save", partial_save)
    with pytest.raises(OSError):
        store.save(doc, path, stamp)
    assert doc.version == 0 and doc.logs == []
    assert doc.modifier == "" and doc.modify_time == "" and doc.content_hash == ""
    assert stamp.version == 0
    assert not path.exists()
    assert list(tmp_path.glob("*.tmp")) == []


def test_save_replace_failure_rolls_back(cfg_b_lines, reg_profile, tmp_path, monkeypatch):
    """os.replace 失败（文件被占用）：mutation 全回滚、tmp 清理、无目标文件。"""
    doc = make_doc(cfg_b_lines)
    stamp = identity.make_stamp(reg_profile, view="销售视图", action="编辑明细", summary="虚构", version=0)
    path = tmp_path / "虚构配置B.xlsx"

    def boom(*a, **k):
        raise PermissionError("模拟文件被占用")

    monkeypatch.setattr(store.os, "replace", boom)
    with pytest.raises(OSError):
        store.save(doc, path, stamp)
    assert doc.version == 0 and doc.logs == []
    assert doc.modifier == "" and doc.modify_time == "" and doc.content_hash == ""
    assert stamp.version == 0
    assert not path.exists()
    assert list(tmp_path.glob("*.tmp")) == []


# ---- T6M1：三导出原子写＋写成功后才改 doc（无幻影审计） ----------------------


@pytest.mark.parametrize("kind", ["customer", "approval", "purchase"])
@pytest.mark.parametrize("fail_mode", ["save", "replace"])
def test_export_write_failure_no_phantom_audit(cfg_b_lines, reg_profile, tmp_path, monkeypatch, kind, fail_mode):
    """wb.save/os.replace 抛 OSError：doc.status/logs/last_export_*/stamp.action 全不变、
    无目标文件、无残留 tmp（approval 内嵌审计留痕，走失败回滚口径）。"""
    doc = make_doc(cfg_b_lines)
    doc.status = "询价"
    stamp = identity.make_stamp(reg_profile, view="销售视图", action="编辑明细", summary="虚构", version=0)
    snap = (doc.status, len(doc.logs), doc.last_export_by, doc.last_export_time,
            doc.last_export_type, stamp.action)

    if fail_mode == "save":
        def partial_save(wb, filename):
            Path(filename).write_bytes(b"partial")
            raise OSError("模拟磁盘满")
        monkeypatch.setattr(openpyxl.Workbook, "save", partial_save)
    else:
        def boom(*a, **k):
            raise PermissionError("模拟文件被占用")
        monkeypatch.setattr(store.os, "replace", boom)

    fn = {"customer": exports.export_customer,
          "approval": exports.export_approval,
          "purchase": exports.export_purchase}[kind]
    dest = tmp_path / f"虚构_{kind}.xlsx"
    with pytest.raises(OSError):
        fn(doc, dest, stamp)
    assert (doc.status, len(doc.logs), doc.last_export_by, doc.last_export_time,
            doc.last_export_type, stamp.action) == snap
    assert not dest.exists()
    assert list(tmp_path.glob("*.tmp")) == []


# ---- I2：采购确认后底价 NaN 守卫 --------------------------------------------


def test_purchase_nan_confirm_price_guard(qtbot, tmp_path, reg_profile, cfg_b_lines):
    """confirm_price=NaN 文件 load→MainWindow refresh：修复前 NaN>quote 抛 InvalidOperation
    逃逸（fen(NaN)=NaN 静默）；修复后走 show_calc_error，销售四数不受影响。"""
    doc = make_doc(cfg_b_lines)
    doc.lines[0].confirm_price = D("NaN")
    path = tmp_path / "虚构NaN确认.xlsx"
    store.save(doc, path, creator_stamp(reg_profile))  # 成本阶段有限→save 成功，NaN 以字符串落格
    win = MainWindow(path=path, profile=reg_profile)   # 修复前：构造期 refresh 即崩
    qtbot.addWidget(win)
    pv = win.purchase_view
    assert "计算错误" in pv.lbl_warning.text()
    assert pv.lbl_floor_confirmed.text() == "—"
    assert win.lbl_quote.text() == "4543.00"  # 成本阶段有限，销售四数照常


# ---- T3M1：apply_reverse 绕率校验（floor 逐位不变） --------------------------


@pytest.mark.parametrize("setup", ["unified_markup_ge1", "item_markup_ge1",
                                   "unified_margin_ge1", "item_margin_ge1"])
def test_apply_reverse_bypasses_rate_validation(cfg_b_lines, setup):
    """margin 目标反算时当前模式/件率≥1 不得先抛『毛利率必须小于100%』——
    反算本应替换这些率；floor 直接 Σfloor_contrib 全精度再 fen，与修前逐位一致。"""
    doc = make_doc(cfg_b_lines)
    if setup == "unified_markup_ge1":
        doc.mode, doc.unified_rate = "markup", D("1.5")
    elif setup == "item_markup_ge1":
        doc.mode = "markup"
        doc.lines[0].item_rate = D("1.2")
    elif setup == "unified_margin_ge1":
        doc.mode, doc.unified_rate = "margin", D("1.0")
    else:
        doc.mode, doc.unified_rate = "margin", D("0.10")
        doc.lines[0].item_rate = D("1.2")
    p = tax.TaxProfile()
    floor_before = money.fen(sum((tax.floor_contrib(ln.unit_price, ln.qty, ln.invoice, p)
                                  for ln in doc.lines), D("0")))
    summary = pricing.apply_reverse(doc, D("4588.89"), "margin", p)  # 修复前：ValueError
    dp = pricing.price_doc(doc.lines, "margin", doc.unified_rate, p)
    assert dp.quote == D("4588.89")
    assert dp.floor == floor_before == D("4130.00")  # 附录B.6 例3；floor 逐位不变
    assert all(ln.item_rate is None for ln in doc.lines)
    assert "反算写回" in summary and "尾差" in summary


# ---- I1：非模态对话框 doc 绑定＋换 doc 失效 ----------------------------------


def test_load_file_closes_open_dialogs(qtbot, tmp_path, reg_profile, cfg_b_lines):
    """开 ReverseDialog＋ApprovalDialog 后 load_file 换 doc：两框必须被关闭（失效），
    不得残留旧框提交污染新 doc。"""
    doc_a = make_doc(cfg_b_lines)
    doc_a.config_name = "虚构配置A"
    win = MainWindow(doc=doc_a, profile=reg_profile)
    qtbot.addWidget(win)
    win.btn_reverse.click()
    assert win.findChild(ReverseDialog) is not None
    win.tabs.setCurrentIndex(2)
    win.review_view.btn_approval.click()
    assert win.findChild(ApprovalDialog) is not None
    path_b = save_second_doc(cfg_b_lines, reg_profile, tmp_path)
    win.load_file(path_b)
    qtbot.wait(20)  # WA_DeleteOnClose 延迟销毁
    assert win.findChild(ReverseDialog) is None
    assert win.findChild(ApprovalDialog) is None
    assert win.doc.config_name == "虚构配置B二号"


def test_reverse_dialog_binds_its_own_doc(qtbot, tmp_path, reg_profile, cfg_b_lines, msgbox):
    """残留提交路径：开框(docA)→load_file(docB)→框信号仍提交 → 必须作用框内 docA，
    docB 定价不被污染（处理器绑定框内 doc，而非当前 self.doc）。"""
    doc_a = make_doc(cfg_b_lines)
    doc_a.config_name = "虚构配置A"
    win = MainWindow(doc=doc_a, profile=reg_profile)
    qtbot.addWidget(win)
    win.btn_reverse.click()
    rd = win.findChild(ReverseDialog)
    path_b = save_second_doc(cfg_b_lines, reg_profile, tmp_path)
    win.load_file(path_b)
    loaded = win.doc
    assert loaded is not doc_a
    n_b = len(loaded.logs)
    rd.writeback_requested.emit(D("4555.55"))  # 模拟残留信号（框内 doc 仍是 docA）
    assert doc_a.unified_rate != D("0.10")     # 反算写回落在 docA
    assert all(ln.item_rate is None for ln in doc_a.lines)
    assert doc_a.logs[-1].action == "反算写回"
    assert loaded.unified_rate == D("0.10")    # docB 未被污染
    assert len(loaded.logs) == n_b


def test_approval_dialog_binds_its_own_doc(qtbot, tmp_path, reg_profile, cfg_b_lines, msgbox):
    """残留提交路径：审批框(docA)→load_file(docB)→框信号仍提交 → 审批记录只落 docA，
    docB 不得新增审批记录/状态流转（只增持久，错误落 doc 即污染）。"""
    doc_a = make_doc(cfg_b_lines)
    doc_a.config_name = "虚构配置A"
    doc_a.status = "待审批"
    win = MainWindow(doc=doc_a, profile=reg_profile)
    qtbot.addWidget(win)
    win.tabs.setCurrentIndex(2)
    win.review_view.btn_approval.click()
    ad = win.findChild(ApprovalDialog)
    path_b = save_second_doc(cfg_b_lines, reg_profile, tmp_path, status="待审批")
    win.load_file(path_b)
    loaded = win.doc
    ad.approval_requested.emit("同意", "虚构意见：同意采购")
    assert len(doc_a.approvals) == 1 and doc_a.approvals[0].conclusion == "同意"
    assert doc_a.approval_status == "已同意" and doc_a.status == "采购中"
    assert loaded.approvals == [] and loaded.approval_status == "未提交"
    assert loaded.status == "待审批"


# ---- T4.BAK：备份豁免大小写不敏感 --------------------------------------------


def test_bak_uppercase_exempt_from_writeback(cfg_b_lines, reg_profile, tmp_path):
    """.BAK（大写后缀）与 .bak 同等待遇：脏备份 load 只警告，不回写覆盖、不再生备份。"""
    doc = make_doc(cfg_b_lines)
    p = tmp_path / "虚构配置B.xlsx"
    store.save(doc, p, creator_stamp(reg_profile))
    store.save(doc, p, creator_stamp(reg_profile))  # 产生 .bak（v1 快照）
    upper = tmp_path / "虚构配置B.BAK"
    os.replace(tmp_path / "虚构配置B.bak", upper)
    # 外部改成本（模拟 Excel 编辑备份）：openpyxl 按扩展名拒 .BAK，经 BytesIO 往返
    wb = openpyxl.load_workbook(io.BytesIO(upper.read_bytes()))
    wb["部件明细"].cell(row=2, column=4).value = 1234
    out = io.BytesIO()
    wb.save(out)
    wb.close()
    upper.write_bytes(out.getvalue())
    before = upper.read_bytes()
    mtime = upper.stat().st_mtime_ns
    loaded, warning = store.load(upper)
    assert warning is not None                      # 脏标记仍须提示
    assert loaded.lines[0].unit_price == D("1234")  # 外部值被读入
    assert upper.read_bytes() == before             # 修复前：.BAK 被回写覆盖
    assert upper.stat().st_mtime_ns == mtime
    assert not (tmp_path / "虚构配置B.tmp").exists()
    # 目录内工作文件仅 .BAK 与 .xlsx（reg_profile 的 APPDATA 档案目录除外）：无 .BAK.bak、无 tmp
    names = sorted(x.name for x in tmp_path.iterdir() if x.suffix.lower() in (".xlsx", ".bak", ".tmp"))
    assert names == ["虚构配置B.BAK", "虚构配置B.xlsx"]
