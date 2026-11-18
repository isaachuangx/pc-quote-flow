"""销售视图（Task 8）：四数面板 + 利润率输入 + 明细表格 + 低于底价红色警告。

四数显示口径（R22②）：底价/报价/利润取 DocPricing 已舍入值的 str()；
两率用 money.pct2（返回 Decimal 不带%）由本层追加 "%"。
低于底价 → lbl_warning 红字可见，绝不 disable 任何操作（红线2/R22⑩）。
供应商/商品链接列可由 checkbox 隐藏（R22⑨）；派生列只读由模型保证。
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QTableView, QVBoxLayout, QWidget,
)

from ..money import pct2
from ..model import QuoteDoc
from ..pricing import DocPricing
from ..tax import TaxProfile
from .table_model import QuoteTableModel

_WARN_BELOW = "警告：整机报价低于底价！导出前需一次确认（不阻止操作）"


class SalesView(QWidget):
    """销售视图面板；MainWindow 持有其控件引用并统一 refresh_pricing。"""

    def __init__(self, doc: QuoteDoc, p: TaxProfile, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.p = p
        # 四数面板（objectName 与控件同名，便于测试定位）
        grid = QGridLayout()
        self.lbl_floor = QLabel("0.00")
        self.lbl_quote = QLabel("0.00")
        self.lbl_profit = QLabel("0.00")
        self.lbl_markup = QLabel("0.00%")
        self.lbl_margin = QLabel("0.00%")
        for i, (cap, val) in enumerate([
            ("底价", self.lbl_floor), ("客户报价", self.lbl_quote),
            ("利润(不含税)", self.lbl_profit), ("加成率", self.lbl_markup),
            ("毛利率", self.lbl_margin),
        ]):
            lab = QLabel(cap)
            lab.setAlignment(Qt.AlignCenter)
            val.setAlignment(Qt.AlignCenter)
            val.setStyleSheet("font-size: 16px; font-weight: bold;")
            grid.addWidget(lab, 0, i)
            grid.addWidget(val, 1, i)
        self.lbl_floor.setObjectName("lbl_floor")
        self.lbl_quote.setObjectName("lbl_quote")
        self.lbl_profit.setObjectName("lbl_profit")
        self.lbl_markup.setObjectName("lbl_markup")
        self.lbl_margin.setObjectName("lbl_margin")
        # 利润率输入行：百分比口径（输 10 → 0.10，R22③）
        self.txt_rate = QLineEdit()
        self.txt_rate.setObjectName("txt_rate")
        self.txt_rate.setPlaceholderText("百分比，如 10 表示 10%")
        self.combo_mode = QComboBox()
        self.combo_mode.setObjectName("combo_mode")
        self.combo_mode.addItems(["成本加成", "销售毛利率"])
        self.btn_reverse = QPushButton("反算写回…")
        rate_row = QHBoxLayout()
        rate_row.addWidget(QLabel("利润率(%)："))
        rate_row.addWidget(self.txt_rate)
        rate_row.addWidget(self.combo_mode)
        rate_row.addWidget(self.btn_reverse)
        rate_row.addStretch(1)
        # 列显示控制（R22⑨）
        self.chk_supplier = QCheckBox("显示供应商")
        self.chk_supplier.setChecked(True)
        self.chk_link = QCheckBox("显示商品链接")
        self.chk_link.setChecked(True)
        col_row = QHBoxLayout()
        col_row.addWidget(self.chk_supplier)
        col_row.addWidget(self.chk_link)
        col_row.addStretch(1)
        # 明细表格
        self.table = QTableView()
        self.model = QuoteTableModel(doc, "销售", p)
        self.table.setModel(self.model)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.chk_supplier.toggled.connect(self._sync_hidden)
        self.chk_link.toggled.connect(self._sync_hidden)
        # 低于底价警告（红字，常显不门禁）
        self.lbl_warning = QLabel(_WARN_BELOW)
        self.lbl_warning.setObjectName("lbl_warning")
        self.lbl_warning.setStyleSheet("color: red; font-weight: bold;")
        self.lbl_warning.hide()
        lay = QVBoxLayout(self)
        lay.addLayout(grid)
        lay.addLayout(rate_row)
        lay.addLayout(col_row)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.lbl_warning)
        self._sync_hidden()

    def set_doc(self, doc: QuoteDoc) -> None:
        """打开新文件后重建模型（doc 引用更换，列隐藏状态保留）。"""
        self.doc = doc
        self.model = QuoteTableModel(doc, "销售", self.p)
        self.table.setModel(self.model)
        self._sync_hidden()

    def _sync_hidden(self) -> None:
        hdr = {self.model.headerData(c, Qt.Horizontal): c for c in range(self.model.columnCount())}
        self.table.setColumnHidden(hdr["供应商"], not self.chk_supplier.isChecked())
        self.table.setColumnHidden(hdr["商品链接"], not self.chk_link.isChecked())

    def set_pricing(self, dp: DocPricing | None) -> None:
        """四数刷新（R22②）+ 低于底价判定（R22⑩）；dp=None（空明细）显示 0.00。"""
        self.lbl_warning.setText(_WARN_BELOW)
        if dp is None:
            self.lbl_floor.setText("0.00")
            self.lbl_quote.setText("0.00")
            self.lbl_profit.setText("0.00")
            self.lbl_markup.setText("0.00%")
            self.lbl_margin.setText("0.00%")
            self.lbl_warning.hide()
            return
        self.lbl_floor.setText(str(dp.floor))
        self.lbl_quote.setText(str(dp.quote))
        self.lbl_profit.setText(str(dp.profit_excl))
        self.lbl_markup.setText(f"{pct2(dp.markup)}%")
        self.lbl_margin.setText(f"{pct2(dp.margin)}%")
        self.lbl_warning.setVisible(dp.quote < dp.floor)

    def show_calc_error(self, msg: str) -> None:
        """非法输入（如毛利率≥100%、未知票种）：四数置 — 并红字提示，不崩溃。"""
        for lab in (self.lbl_floor, self.lbl_quote, self.lbl_profit, self.lbl_markup, self.lbl_margin):
            lab.setText("—")
        self.lbl_warning.setText(f"计算错误：{msg}（请检查利润率/发票类型）")
        self.lbl_warning.setStyleSheet("color: red; font-weight: bold;")
        self.lbl_warning.show()
