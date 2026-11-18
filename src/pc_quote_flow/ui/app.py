"""程序入口与主窗口（Task 8）。

main(argv) 解析 --selftest 与可选 file.xlsx：selftest 无 GUI（附录A/B pricing 断言 +
temp 目录 store 往返），源码模式打印 stdout+退出码；windowed exe 模式（frozen）
以退出码表达结果并把同样输出写 %TEMP%/pc-quote-flow-selftest.log（R22⑦，Task 10 依赖）。

MainWindow：工具栏（当前操作人/打开/保存/设置/切换操作人 + 三种导出按钮）+
视图 tab（销售|采购|审阅；采购/审阅本任务占位，Task 9 替换）+ 销售视图四数面板。
所有写操作经 identity.make_stamp 新鲜对象记日志，只增不改（红线4/R22⑧）；
无权限门禁：低于底价仅红字警告+导出前一次确认，导出按钮永不 disable（红线2）。
打开文件哈希不一致 → 提示"程序外被修改"+一条打开留痕（R15/R22⑤）。
导出成功 → 调用方 store.save 递增工作文件版本（R20⑧：exports 自身不 save）。
"""
import json
import os
import sys
import tempfile
import traceback
from datetime import date, timedelta
from decimal import Decimal, DivisionByZero, InvalidOperation
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QLabel, QMainWindow, QMessageBox,
    QPushButton, QTabWidget, QToolBar, QVBoxLayout, QWidget,
)

from .. import exports, identity, pricing, store, tax
from ..money import pct2
from ..model import QuoteDoc, QuoteLine
from .dialogs import RegisterDialog, ReverseDialog, SettingsDialog
from .sales_view import SalesView

_MODE_CN = {"markup": "成本加成", "margin": "销售毛利率"}
_CN_MODE = {v: k for k, v in _MODE_CN.items()}
_VIEWS = ("销售视图", "采购视图", "审阅视图")

# 附录A 虚构配置（与 tests/conftest.py、samples/make_samples.py 逐字同源；红线1 禁真实价格）
_CFG_A = [
    ("CPU（盒装）", "2000", "专票"), ("主板", "1000", "专票"), ("内存 32G 套条", "800", "京东专票"),
    ("固态 500G", "600", "京东专票"), ("机械 2TB", "900", "专票"), ("电源 650W", "300", "专票"),
    ("散热双塔", "100", "专票"), ("机箱", "80", "专票"), ("风扇 120mm", "20", "专票"),
]
_CFG_B = [
    ("CPU（散片）", "1000", "普票"), ("主板", "1000", "专票"), ("内存 16G", "400", "京东专票"),
    ("固态 500G", "600", "专票"), ("机械 1TB", "500", "京东专票"), ("电源 650W", "300", "专票"),
    ("散热双塔", "100", "专票"), ("机箱", "80", "专票"), ("风扇 120mm", "20", "专票"),
]


def _cfg_lines(table) -> list[QuoteLine]:
    return [QuoteLine(name=n, unit_price=Decimal(pr), invoice=inv) for n, pr, inv in table]


def _selftest_checks() -> list[str]:
    """附录A/B 断言 + temp 目录 store 往返（全虚构数据）；任一失败抛异常。"""
    p = tax.TaxProfile()
    out: list[str] = []

    def check(label: str, cond: bool) -> None:
        if not cond:
            raise AssertionError(f"自检失败：{label}")
        out.append(f"通过：{label}")

    # 配置A markup10%（附录B.6 例1/2/3）
    dpa = pricing.price_doc(_cfg_lines(_CFG_A), "markup", Decimal("0.10"), p)
    check("配置A 底价 5800.00", dpa.floor == Decimal("5800.00"))
    check("配置A 加成10% 报价 6380.00", dpa.quote == Decimal("6380.00"))
    check("配置A 利润(不含税) 513.27", dpa.profit_excl == Decimal("513.27"))
    check("配置A 毛利率显示 9.09", pct2(dpa.margin) == Decimal("9.09"))
    # 配置B markup10%（附录B.6 例4、B.7 #5）
    dpb = pricing.price_doc(_cfg_lines(_CFG_B), "markup", Decimal("0.10"), p)
    check("配置B 底价 4130.00", dpb.floor == Decimal("4130.00"))
    check("配置B 加成10% 报价 4543.00", dpb.quote == Decimal("4543.00"))
    check("配置B 利润(不含税) 365.49", dpb.profit_excl == Decimal("365.49"))
    check("配置B 加成率 10.00 / 毛利率 9.09",
          pct2(dpb.markup) == Decimal("10.00") and pct2(dpb.margin) == Decimal("9.09"))
    # 配置B margin10%（附录B.7 #6）
    dpm = pricing.price_doc(_cfg_lines(_CFG_B), "margin", Decimal("0.10"), p)
    check("配置B 毛利率10% 报价 4588.89", dpm.quote == Decimal("4588.89"))
    check("配置B 毛利率10% 利润 406.10", dpm.profit_excl == Decimal("406.10"))
    # 反算写回 T=4555.55（附录B.6 例5：尾差 +0.01 → CPU 件报价 1246.44）
    doc = QuoteDoc(config_name="虚构配置B", mode="markup", unified_rate=Decimal("0.10"),
                   lines=_cfg_lines(_CFG_B))
    pricing.apply_reverse(doc, Decimal("4555.55"), "markup", p)
    dp2 = pricing.price_doc(doc.lines, doc.mode, doc.unified_rate, p)
    check("反算写回 合计精确 4555.55", dp2.quote == Decimal("4555.55"))
    check("反算写回 尾差→底价最大件 CPU 件报价 1246.44", dp2.line_quotes[0] == Decimal("1246.44"))
    # 数量舍入陷阱（附录B.6 例7：先乘数量再舍入）
    dp3 = pricing.price_doc([QuoteLine(name="虚构件", unit_price=Decimal("99.99"), qty=3, invoice="普票")],
                            "markup", Decimal("0.10"), p)
    check("数量舍入 件底价 338.97", dp3.line_floors[0] == Decimal("338.97"))
    check("数量舍入 件报价 372.86", dp3.line_quotes[0] == Decimal("372.86"))
    # store 往返（temp 目录；版本递增/.bak/日志只增）
    with tempfile.TemporaryDirectory(prefix="pcqf-selftest-") as td:
        path = Path(td) / "虚构配置B.xlsx"
        prof = identity.Profile("自检员", "销售客服", "SELFTEST-PC", "selftest")
        doc2 = QuoteDoc(config_name="虚构配置B", customer="示例客户", quote_date="2026-11-18",
                        valid_until="2026-12-31", creator="自检员", mode="markup",
                        unified_rate=Decimal("0.10"), lines=_cfg_lines(_CFG_B))
        store.save(doc2, path, identity.make_stamp(prof, view="销售视图", action="创建文件",
                                                   summary="自检：创建", version=0))
        loaded, warnings = store.load(path)
        check("store 往返 无外部改动警告", not warnings)
        check("store 往返 版本=1 明细9件 日志1条",
              loaded.version == 1 and len(loaded.lines) == 9 and len(loaded.logs) == 1)
        check("store 往返 模式/统一率一致", loaded.mode == "markup" and loaded.unified_rate == Decimal("0.10"))
        store.save(loaded, path, identity.make_stamp(prof, view="销售视图", action="保存",
                                                     summary="自检：再保存", version=loaded.version))
        check("store 二次保存 版本=2 且留 .bak", loaded.version == 2 and path.with_suffix(".bak").exists())
        loaded2, w2 = store.load(path)
        check("store 二次往返 日志只增（2条）", not w2 and len(loaded2.logs) == 2)
    return out


def run_selftest() -> int:
    """--selftest 入口：成功 0 / 失败 1；frozen 模式写 %TEMP% 日志（R22⑦）。"""
    try:
        lines = _selftest_checks()
        ok = True
    except Exception:
        lines = [traceback.format_exc()]
        ok = False
    lines.append("SELFTEST OK" if ok else "SELFTEST FAIL")
    text = "\n".join(lines) + "\n"
    if getattr(sys, "frozen", False):
        # windowed exe 无 stdout：退出码表达结果，同样输出落 %TEMP% 日志供 Task 10 验证
        try:
            log = Path(os.environ.get("TEMP") or tempfile.gettempdir()) / "pc-quote-flow-selftest.log"
            log.write_text(text, encoding="utf-8")
        except OSError:
            pass
        if sys.stdout is not None:
            print(text, end="")
    else:
        print(text, end="")
    return 0 if ok else 1


def _load_settings() -> tuple[str, int]:
    """读 settings.json（默认算法/有效期天数）；缺失/损坏/APPDATA 缺失 → 默认值。"""
    try:
        data = json.loads((identity.profile_dir() / "settings.json").read_text(encoding="utf-8"))
        if isinstance(data, dict):
            mode, days = data.get("default_mode"), data.get("valid_days")
            if mode in _MODE_CN and isinstance(days, int) and 1 <= days <= 3650:
                return mode, days
    except (KeyError, OSError, ValueError):
        pass
    return "markup", 30


def _save_settings(mode: str, days: int) -> None:
    """写 settings.json；失败不阻断使用（内存值仍生效）。"""
    try:
        d = identity.profile_dir()
        d.mkdir(parents=True, exist_ok=True)
        (d / "settings.json").write_text(
            json.dumps({"default_mode": mode, "valid_days": days}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except (KeyError, OSError):
        pass


def _placeholder(text: str) -> QWidget:
    """采购/审阅 tab 占位（Task 9 替换，本任务不实现其逻辑，R22⑨）。"""
    w = QWidget()
    lay = QVBoxLayout(w)
    lab = QLabel(text)
    lab.setAlignment(Qt.AlignCenter)
    lay.addWidget(lab)
    return w


class MainWindow(QMainWindow):
    """主窗口：工具栏 + 视图 tab + 销售视图；统一 refresh_pricing 刷新四数。"""

    def __init__(self, path: Path | None = None, parent=None):
        super().__init__(parent)
        self.p = tax.TaxProfile()
        self.path: Path | None = None
        # 首次运行：load_profile 损坏一律 None；APPDATA 缺失抛 KeyError 视为首次运行（R17②/R22④）
        profile: identity.Profile | None = None
        try:
            profile = identity.load_profile()
        except KeyError:
            profile = None
        if profile is None:
            dlg = RegisterDialog(self)
            if dlg.exec() != QDialog.Accepted or dlg.profile is None:
                return  # 取消登记：profile 属性不赋值，main() 以 getattr 探测后退出
            profile = dlg.profile
        self.profile: identity.Profile = profile  # 构造成功后恒非 None（取消路径已提前返回）
        self.default_mode, self.valid_days = _load_settings()
        self.doc = self._make_new_doc()
        self._build_ui()
        self._sync_rate_controls()
        self.refresh_pricing()
        if path is not None:
            self.load_file(Path(path))

    # ---- 构建 ----
    def _make_new_doc(self) -> QuoteDoc:
        today = date.today()
        return QuoteDoc(
            config_name="新建报价单", creator=self.profile.name,
            quote_date=today.isoformat(),
            valid_until=(today + timedelta(days=self.valid_days)).isoformat(),
            mode=self.default_mode,
        )

    def _build_ui(self) -> None:
        self.setWindowTitle("pc-quote-flow 装机报价流转")
        tb = QToolBar("工具栏")
        self.addToolBar(tb)
        self.lbl_operator = QLabel()
        tb.addWidget(self.lbl_operator)
        self.btn_switch = QPushButton("切换操作人")
        self.btn_open = QPushButton("打开")
        self.btn_save = QPushButton("保存")
        self.btn_settings = QPushButton("设置")
        for b in (self.btn_switch, self.btn_open, self.btn_save, self.btn_settings):
            tb.addWidget(b)
        tb.addSeparator()
        self.btn_export_customer = QPushButton("导出客户报价单")
        self.btn_export_approval = QPushButton("导出审批文件")
        self.btn_export_purchase = QPushButton("导出采购单")
        for b in (self.btn_export_customer, self.btn_export_approval, self.btn_export_purchase):
            tb.addWidget(b)  # 永不 disable（红线2：无权限门禁）
        self.tabs = QTabWidget()
        self.sales_view = SalesView(self.doc, self.p)
        self.tabs.addTab(self.sales_view, "销售")
        self.tabs.addTab(_placeholder("采购视图（Task 9 实现）"), "采购")
        self.tabs.addTab(_placeholder("审阅视图（Task 9 实现）"), "审阅")
        self.setCentralWidget(self.tabs)
        # 四数/利润率控件引用（与销售视图同一对象，便于统一刷新与测试定位）
        self.lbl_floor = self.sales_view.lbl_floor
        self.lbl_quote = self.sales_view.lbl_quote
        self.lbl_profit = self.sales_view.lbl_profit
        self.lbl_markup = self.sales_view.lbl_markup
        self.lbl_margin = self.sales_view.lbl_margin
        self.lbl_warning = self.sales_view.lbl_warning
        self.txt_rate = self.sales_view.txt_rate
        self.combo_mode = self.sales_view.combo_mode
        self.btn_reverse = self.sales_view.btn_reverse
        # 信号接线
        self.txt_rate.editingFinished.connect(self._on_rate_edited)
        self.combo_mode.currentTextChanged.connect(self._on_mode_changed)
        self.btn_reverse.clicked.connect(self._open_reverse)
        self.sales_view.model.edited.connect(self._on_model_edited)
        self.btn_open.clicked.connect(self._open_file_dialog)
        self.btn_save.clicked.connect(lambda: self.save_file())
        self.btn_settings.clicked.connect(self._open_settings)
        self.btn_switch.clicked.connect(self._switch_operator)
        self.btn_export_customer.clicked.connect(lambda: self._export("customer"))
        self.btn_export_approval.clicked.connect(lambda: self._export("approval"))
        self.btn_export_purchase.clicked.connect(lambda: self._export("purchase"))
        self._update_operator_label()
        self.statusBar().showMessage("就绪")

    def current_view(self) -> str:
        return _VIEWS[self.tabs.currentIndex()]

    def _update_operator_label(self) -> None:
        self.lbl_operator.setText(f"当前操作人：{self.profile.name}（{self.profile.role}）")

    def _update_title(self) -> None:
        self.setWindowTitle(f"{self.doc.config_name} v{self.doc.version}（{self.doc.status}） - pc-quote-flow")
        loc = str(self.path) if self.path else "未保存"
        self.statusBar().showMessage(
            f"{loc} ｜ 状态：{self.doc.status} ｜ 有效期至：{self.doc.valid_until or '—'} ｜ v{self.doc.version}"
        )

    # ---- 统一刷新（R22②③：一切刷新走 price_doc）----
    def refresh_pricing(self) -> None:
        dp = None
        if self.doc.lines:
            try:
                dp = pricing.price_doc(self.doc.lines, self.doc.mode, self.doc.unified_rate, self.p)
            except (ValueError, ArithmeticError) as e:
                self.sales_view.show_calc_error(str(e))
                self.sales_view.model.refresh()
                self._update_title()
                return
        self.sales_view.set_pricing(dp)
        self.sales_view.model.refresh()
        self._update_title()

    def _sync_rate_controls(self) -> None:
        """doc → 利润率输入/模式下拉（阻塞信号避免回环）。"""
        self.txt_rate.blockSignals(True)
        self.combo_mode.blockSignals(True)
        self.txt_rate.setText(str(pct2(self.doc.unified_rate)))
        self.combo_mode.setCurrentText(_MODE_CN[self.doc.mode])
        self.txt_rate.blockSignals(False)
        self.combo_mode.blockSignals(False)

    # ---- 利润率/模式/明细编辑（均盖章留痕）----
    def _on_rate_edited(self) -> None:
        text = self.txt_rate.text().strip()
        try:
            pct = Decimal(text)
        except InvalidOperation:
            QMessageBox.warning(self, "利润率", f"请输入百分比数字（如 10 表示 10%），当前输入：{text!r}")
            self._sync_rate_controls()
            return
        rate = pct / 100  # 百分比输入口径（R22③：输 10 → 0.10）
        if self.doc.mode == "margin" and rate >= 1:
            QMessageBox.warning(self, "利润率", "毛利率模式的利润率必须小于 100%")
            self._sync_rate_controls()
            return
        if rate == self.doc.unified_rate:
            return
        old = self.doc.unified_rate
        self.doc.unified_rate = rate
        self.doc.logs.append(identity.make_stamp(
            self.profile, view=self.current_view(), action="修改利润率",
            summary=f"统一利润率 {pct2(old)}%→{pct2(rate)}%", version=self.doc.version,
        ))
        self.refresh_pricing()

    def _on_mode_changed(self, text: str) -> None:
        mode = _CN_MODE.get(text)
        if mode is None or mode == self.doc.mode:
            return
        if mode == "margin" and self.doc.unified_rate >= 1:
            QMessageBox.warning(self, "利润率", "毛利率模式的利润率必须小于 100%，请先调低利润率")
            self._sync_rate_controls()
            return
        old = self.doc.mode
        self.doc.mode = mode
        self.doc.logs.append(identity.make_stamp(
            self.profile, view=self.current_view(), action="修改算法模式",
            summary=f"算法模式 {_MODE_CN[old]}→{_MODE_CN[mode]}", version=self.doc.version,
        ))
        self.refresh_pricing()

    def _on_model_edited(self, summary: str) -> None:
        """模型 setData 成功 → 一条新鲜盖章 + 统一刷新（R22⑧）。"""
        self.doc.logs.append(identity.make_stamp(
            self.profile, view=self.current_view(), action="编辑明细",
            summary=summary, version=self.doc.version,
        ))
        self.refresh_pricing()

    # ---- 反算写回（R22①：apply_reverse 返回文本→一条盖章，不双重 append）----
    def _open_reverse(self) -> None:
        dlg = ReverseDialog(self.doc, self.p, self)
        dlg.writeback_requested.connect(self._on_reverse_writeback)
        dlg.show()  # 非模态，便于对照主窗口四数

    def _on_reverse_writeback(self, target: Decimal) -> None:
        try:
            summary = pricing.apply_reverse(self.doc, target, self.doc.mode, self.p)
        except (ValueError, ArithmeticError) as e:
            QMessageBox.warning(self, "反算写回", f"无法反算写回：{e}")
            return
        self.doc.logs.append(identity.make_stamp(
            self.profile, view="销售", action="反算写回",
            summary=summary, version=self.doc.version,
        ))
        self._sync_rate_controls()
        self.refresh_pricing()

    # ---- 打开/保存（R15/R22⑤：外部改动留痕；store 原子保存）----
    def load_file(self, path: Path) -> None:
        try:
            doc, warnings = store.load(path)
        except store.StoreError as e:
            QMessageBox.critical(self, "打开失败", str(e))
            return
        except Exception as e:  # 损坏/非法 xlsx 不崩溃
            QMessageBox.critical(self, "打开失败", f"无法读取文件：{e}")
            return
        self.doc = doc
        self.path = Path(path)
        if warnings:
            summary = "；".join(warnings)
            QMessageBox.warning(self, "打开文件", summary)
            doc.logs.append(identity.make_stamp(
                self.profile, view=self.current_view(), action="打开文件",
                summary=summary, version=doc.version,
            ))
        self.sales_view.set_doc(doc)
        self.sales_view.model.edited.connect(self._on_model_edited)
        self._sync_rate_controls()
        self.refresh_pricing()

    def _open_file_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "打开报价文件", "", "Excel 文件 (*.xlsx *.bak);;所有文件 (*)")
        if path:
            self.load_file(Path(path))

    def save_file(self) -> bool:
        if self.path is None:
            default = f"{self.doc.config_name}_v{self.doc.version + 1}.xlsx"
            path, _ = QFileDialog.getSaveFileName(self, "保存工作文件", default, "Excel 文件 (*.xlsx)")
            if not path:
                return False
            self.path = Path(path)
        stamp = identity.make_stamp(
            self.profile, view=self.current_view(), action="保存",
            summary=f"保存工作文件（{_MODE_CN[self.doc.mode]}，统一利润率 {pct2(self.doc.unified_rate)}%）",
            version=self.doc.version,
        )
        try:
            store.save(self.doc, self.path, stamp)
        except OSError as e:
            QMessageBox.critical(self, "保存失败", f"保存失败：{e}（文件被占用或磁盘不可写）")
            return False
        self.refresh_pricing()
        return True

    # ---- 设置/切换操作人 ----
    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.profile, self.default_mode, self.valid_days, self)
        if dlg.exec() != QDialog.Accepted or dlg.profile is None:
            return
        new_p = dlg.profile
        if (new_p.name, new_p.role) != (self.profile.name, self.profile.role):
            identity.switch_operator(self.doc, new_p, self.current_view())  # 自身 append 一条
        self.profile = new_p
        self.default_mode = dlg.default_mode
        self.valid_days = dlg.valid_days
        _save_settings(self.default_mode, self.valid_days)
        self._update_operator_label()
        self.refresh_pricing()

    def _switch_operator(self) -> None:
        dlg = RegisterDialog(self, title="切换操作人（登记新操作人）")
        if dlg.exec() != QDialog.Accepted or dlg.profile is None:
            return
        new_p = dlg.profile
        identity.switch_operator(self.doc, new_p, self.current_view())  # 自身 append 一条，勿重复（R22⑧）
        self.profile = new_p
        self._update_operator_label()
        self.refresh_pricing()

    # ---- 三种导出（R22⑥：确认一次/OSError 不崩溃/中文提示/调用方 save）----
    def _export(self, kind: str) -> None:
        label, fn = {
            "customer": ("客户报价单", exports.export_customer),
            "approval": ("审批文件", exports.export_approval),
            "purchase": ("采购单", exports.export_purchase),
        }[kind]
        if self.path is None and not self.save_file():
            return  # 导出成功后需调用方保存工作文件（R20⑧），先确立工作文件路径
        work = self.path
        if work is None:
            return
        default = {
            "customer": f"{self.doc.config_name}_客户_报价_v{self.doc.version}.xlsx",
            "approval": f"{self.doc.config_name}_客户_审批_v{self.doc.version}.xlsx",
            "purchase": f"{self.doc.config_name}_采购_v{self.doc.version}.xlsx",
        }[kind]
        path, _ = QFileDialog.getSaveFileName(self, f"导出{label}", default, "Excel 文件 (*.xlsx)")
        if not path:
            return
        quote_txt = "0.00"
        if self.doc.lines:
            try:
                quote_txt = str(pricing.price_doc(self.doc.lines, self.doc.mode, self.doc.unified_rate, self.p).quote)
            except (ValueError, ArithmeticError):
                quote_txt = "计算错误"
        stamp = identity.make_stamp(
            self.profile, view=self.current_view(), action="导出",
            summary=f"导出{label}（整机报价 {quote_txt}，来源 v{self.doc.version}）",
            version=self.doc.version,
        )
        try:
            if kind == "customer":
                try:
                    fn(self.doc, Path(path), stamp)
                except exports.NeedsConfirmation as e:
                    ret = QMessageBox.question(
                        self, "低于底价确认", f"{e}。是否确认导出？",
                        QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
                    )
                    if ret != QMessageBox.Yes:
                        return  # 用户取消：不导出、不保存
                    fn(self.doc, Path(path), stamp, confirmed=True)
            else:
                fn(self.doc, Path(path), stamp)
        except OSError as e:
            QMessageBox.critical(self, "导出失败", f"导出失败：{e}（文件被占用或磁盘不可写）")
            return
        except ValueError as e:  # 空明细/非法日期等（R19①②，中文消息）
            QMessageBox.warning(self, "无法导出", str(e))
            return
        except DivisionByZero:  # 非 ValueError 子类，须分别捕获（R22⑥）
            QMessageBox.warning(self, "无法导出", "计算除零：请检查明细单价/数量与利润率")
            return
        # 导出成功 → 调用方保存工作文件，version+1（R20⑧/R22⑥）
        save_stamp = identity.make_stamp(
            self.profile, view=self.current_view(), action="保存",
            summary=f"导出{label}后保存工作文件", version=self.doc.version,
        )
        try:
            store.save(self.doc, work, save_stamp)
        except OSError as e:
            QMessageBox.critical(self, "保存失败", f"{label}已导出，但工作文件保存失败：{e}")
            return
        self.refresh_pricing()
        self.statusBar().showMessage(f"已导出{label}：{path}", 8000)


def main(argv: list[str] | None = None) -> int:
    """入口：--selftest 无 GUI 自检；否则 QApplication + MainWindow（可选打开 file.xlsx）。"""
    args = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in args:
        return run_selftest()
    path = next((Path(a) for a in args if not a.startswith("-")), None)
    app = QApplication.instance() or QApplication(["pc-quote-flow"])
    win = MainWindow(path=path)
    if getattr(win, "profile", None) is None:
        return 0  # 首次登记被取消：安静退出
    win.show()
    return app.exec()
