# -*- coding: utf-8 -*-
"""采购视图（Task 9）：核价双底价 + 采购回写 + 真实利润对照（附录B.5）。

数学一律消费 pricing.price_doc/actuals 与 tax.floor_contrib（附录B 唯一权威，不新造公式）：
- 报价时底价 B = dp.floor（锁定报价时口径）；
- 确认后底价（brief 口径）：confirm_price 非 None → 确认价，否则成本价（不看 confirmed 标志，
  与 pricing._effective 确认阶段对齐）；发票同条件独立回退（confirm_invoice → invoice），
  Σ floor_contrib 全精度求和后 fen() 到分；
- 真实利润走 pricing.actuals（实际→确认→成本回退链），eroded/negative 仅提示。
低于底价仅红字警告，绝不 disable 任何操作（红线2 无权限门禁）；审批状态只读展示。
商品链接列可编辑（R43 采购确认货源）：双击回归默认编辑（粘贴/填写），
右键「打开链接」经 QDesktopServices.openUrl 打开浏览器核价。
编辑留痕经 model.edited 信号交 MainWindow 盖章（视图一律 current_view() 长名，R23①）。
"""
from decimal import Decimal

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QGridLayout, QLabel, QMenu, QTableView, QVBoxLayout, QWidget

from .. import pricing, tax
from ..money import fen
from ..model import QuoteDoc
from ..pricing import DocPricing
from ..tax import TaxProfile
from .table_model import QuoteTableModel

_WARN_BELOW_CONFIRMED = "已低于底价，请按公司流程审批"
_EROSION_TEXT = "真实利润低于预期利润：采购成本侵蚀了利润（仅提示，不阻止操作）"


class PurchaseView(QWidget):
    def __init__(self, doc: QuoteDoc, p: TaxProfile, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.p = p
        # 顶部：审批状态只读标签（状态仅流转备忘，不做权限门禁，spec §13.10）
        self.lbl_approval_status = QLabel()
        self.lbl_approval_status.setObjectName("lbl_approval_status")
        self.lbl_approval_status.setWordWrap(True)
        # 三层价格并列（B.5）：报价时底价 B ／ 确认后底价（确认价口径）／ 客户报价 Q
        self.lbl_floor_at_quote = QLabel("0.00")
        self.lbl_floor_confirmed = QLabel("0.00")
        self.lbl_quote = QLabel("0.00")
        grid = QGridLayout()
        for c, (cap, lab) in enumerate((("报价时底价", self.lbl_floor_at_quote),
                                        ("确认后底价（确认价口径）", self.lbl_floor_confirmed),
                                        ("客户报价", self.lbl_quote))):
            capw = QLabel(cap)
            capw.setStyleSheet("color: gray;")
            lab.setObjectName(f"lbl_{('floor_at_quote', 'floor_confirmed', 'quote')[c]}")
            lab.setStyleSheet("font-weight: bold;")
            grid.addWidget(capw, 0, c)
            grid.addWidget(lab, 1, c)
        # 真实利润面板（B.5：实际→确认→成本回退链，pricing.actuals）
        self.lbl_real_profit = QLabel("—")
        self.lbl_expected_profit = QLabel("—")
        self.lbl_cost_excl = QLabel("—")
        self.lbl_floor_effective = QLabel("—")
        agrid = QGridLayout()
        for c, (cap, lab) in enumerate((("真实利润(不含税)", self.lbl_real_profit),
                                        ("预期利润(不含税)", self.lbl_expected_profit),
                                        ("不含税成本 C'", self.lbl_cost_excl),
                                        ("有效价底价 B'（实际→确认→成本）", self.lbl_floor_effective))):
            capw = QLabel(cap)
            capw.setStyleSheet("color: gray;")
            lab.setObjectName(f"lbl_{('real_profit', 'expected_profit', 'cost_excl', 'floor_effective')[c]}")
            lab.setStyleSheet("font-weight: bold;")
            agrid.addWidget(capw, 0, c)
            agrid.addWidget(lab, 1, c)
        self.lbl_erosion = QLabel(_EROSION_TEXT)
        self.lbl_erosion.setObjectName("lbl_erosion")
        self.lbl_erosion.setStyleSheet("color: #b36b00; font-weight: bold;")
        self.lbl_erosion.setWordWrap(True)
        self.lbl_erosion.hide()
        # 明细表（采购视图列集与可编辑白名单见 table_model）
        self.table = QTableView()
        self.model = QuoteTableModel(doc, "采购", p)
        self.table.setModel(self.model)
        self.table.horizontalHeader().setStretchLastSection(True)
        # R43：链接列可编辑（双击默认编辑）；打开浏览器改走右键「打开链接」
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_context_menu)
        # 警告标签（确认后底价 > 客户报价 → 可见；绝不 disable 导出，红线2）
        self.lbl_warning = QLabel(_WARN_BELOW_CONFIRMED)
        self.lbl_warning.setObjectName("lbl_warning")
        self.lbl_warning.setStyleSheet("color: red; font-weight: bold;")
        self.lbl_warning.setWordWrap(True)
        self.lbl_warning.hide()
        lay = QVBoxLayout(self)
        lay.addWidget(self.lbl_approval_status)
        lay.addLayout(grid)
        lay.addLayout(agrid)
        lay.addWidget(self.lbl_erosion)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.lbl_warning)
        self.set_pricing(None)  # 初始态（MainWindow.refresh_pricing 随后刷真实值）

    def set_doc(self, doc: QuoteDoc) -> None:
        """载入文件后换 doc：重建模型（edited 信号由 MainWindow 重连）。"""
        self.doc = doc
        self.model = QuoteTableModel(doc, "采购", self.p)
        self.table.setModel(self.model)

    def set_pricing(self, dp: DocPricing | None) -> None:
        """刷新双底价/警告/真实利润面板。dp=None（空明细）→ 0.00/—，不抛。"""
        self.lbl_approval_status.setText(
            f"审批状态：{self.doc.approval_status}｜审批人：{self.doc.approver or '—'}"
            f"｜意见：{self.doc.approval_opinion or '—'}"
        )
        self.lbl_warning.setText(_WARN_BELOW_CONFIRMED)
        self.lbl_warning.setStyleSheet("color: red; font-weight: bold;")
        if dp is None:
            self.lbl_floor_at_quote.setText("0.00")
            self.lbl_floor_confirmed.setText("0.00")
            self.lbl_quote.setText("0.00")
            self._reset_actuals()
            self.lbl_warning.hide()
            return
        try:
            floor_conf = self._confirmed_floor()
        except (ValueError, ArithmeticError) as e:  # 脏发票/非有限价 → 降级不崩
            self.show_calc_error(str(e))
            return
        # I2：fen(NaN)=NaN 静默不抛（quantize 对 NaN 不报错），须显式守卫非有限，
        # 否则下方 floor_conf > dp.quote 抛 InvalidOperation 逃逸；None（空 doc）放行
        if floor_conf is not None and not floor_conf.is_finite():
            self.show_calc_error("确认后底价非有限（确认价/成本价含 NaN/Infinity）")
            return
        self.lbl_floor_at_quote.setText(str(dp.floor))
        self.lbl_floor_confirmed.setText(str(floor_conf))
        self.lbl_quote.setText(str(dp.quote))
        self.lbl_warning.setVisible(floor_conf > dp.quote)
        self._refresh_actuals()

    def _confirmed_floor(self) -> Decimal:
        """确认后底价（brief/控制者口径）：确认价优先（非 None），否则成本价；
        发票独立同条件回退（confirm_invoice 非 None → 确认票种，否则 invoice）。
        不看 confirmed 标志：该列不在任何视图可编辑白名单（默认 False，仅文件往返可 True），
        以 flag 门禁会使纯 GUI 录入的确认价永不生效（Important-1）；
        与 pricing._effective 确认阶段口径对齐。全精度 Σ floor_contrib 后一次 fen()（附录B.1 先算后舍）。"""
        total = Decimal("0")
        for ln in self.doc.lines:
            price = ln.confirm_price if ln.confirm_price is not None else ln.unit_price
            invoice = ln.confirm_invoice if ln.confirm_invoice is not None else ln.invoice
            total += tax.floor_contrib(price, ln.qty, invoice, self.p)
        return fen(total)

    def _refresh_actuals(self) -> None:
        try:
            a = pricing.actuals(self.doc, self.p)
        except (ValueError, ArithmeticError):  # 空明细/非有限 → 面板降级
            self._reset_actuals()
            return
        self.lbl_real_profit.setText(str(a.real_profit))
        self.lbl_expected_profit.setText(str(a.expected_profit))
        self.lbl_cost_excl.setText(str(a.cost_excl))
        self.lbl_floor_effective.setText(str(a.floor))
        self.lbl_erosion.setVisible(a.eroded)
        self.lbl_real_profit.setStyleSheet(
            "color: red; font-weight: bold;" if a.negative else "font-weight: bold;"
        )

    def _reset_actuals(self) -> None:
        for lab in (self.lbl_real_profit, self.lbl_expected_profit,
                    self.lbl_cost_excl, self.lbl_floor_effective):
            lab.setText("—")
        self.lbl_real_profit.setStyleSheet("font-weight: bold;")
        self.lbl_erosion.hide()

    def show_calc_error(self, msg: str) -> None:
        """计算错误降级（与 MainWindow.refresh_pricing 守卫联动）：显示 — 与错误提示，不崩。"""
        for lab in (self.lbl_floor_at_quote, self.lbl_floor_confirmed, self.lbl_quote):
            lab.setText("—")
        self._reset_actuals()
        self.lbl_warning.setText(f"计算错误：{msg}（请检查利润率/发票类型）")
        self.lbl_warning.setStyleSheet("color: red; font-weight: bold;")
        self.lbl_warning.show()

    def _open_link(self, index) -> None:
        """打开商品链接 URL（仅链接列且非空；右键「打开链接」触发）。"""
        if not index.isValid():
            return
        if self.model.headerData(index.column(), Qt.Horizontal) != "商品链接":
            return
        ln = self.doc.lines[index.row()]
        if ln.link:
            QDesktopServices.openUrl(QUrl(ln.link))

    def _on_context_menu(self, pos) -> None:
        """右键菜单：仅商品链接列且非空时提供「打开链接」（R43）。"""
        idx = self.table.indexAt(pos)
        if not idx.isValid():
            return
        if self.model.headerData(idx.column(), Qt.Horizontal) != "商品链接":
            return
        if not self.doc.lines[idx.row()].link:
            return
        menu = QMenu(self.table)
        act = menu.addAction("打开链接")
        act.triggered.connect(lambda: self._open_link(idx))
        menu.exec(self.table.viewport().mapToGlobal(pos))
