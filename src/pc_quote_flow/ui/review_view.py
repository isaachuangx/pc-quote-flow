# -*- coding: utf-8 -*-
"""审阅视图（Task 9）：全列只读明细 + 审批摘要 + 修改日志 + 审批意见/对照打开。

- 明细用 QuoteTableModel(doc, "审阅", p)：_EDITABLE["审阅"]=∅，全列去 ItemIsEditable
  （spec §13.10 只读＋意见，不提供编辑入口）。
- 审批摘要消费 review.summary（报价时口径，附录B.3）；空明细/计算错误/非有限 → 降级提示不崩。
- 修改日志只读展示（LogTableModel，日志只增不改，红线4）。
- 「填写审批意见」→ ApprovalDialog（非模态，WA_DeleteOnClose）→ approval_requested 信号
  交 MainWindow 新鲜盖章调 review.record_approval（内部已留痕，绝不双重 append，R18①）。
- 「对照打开」→ compare_requested 信号交 MainWindow 开第二窗口（同一 profile）。
"""
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QLabel, QPushButton, QTableView,
                              QVBoxLayout, QWidget)

from .. import review
from ..model import LogEntry, QuoteDoc
from ..money import pct2
from ..tax import TaxProfile
from .dialogs import ApprovalDialog
from .table_model import QuoteTableModel

# 修改日志列（identity.LogEntry 九字段去掉 stamp 自身即八字段＋时间，全量展示）
_LOG_COLS = (("时间", "time"), ("操作人", "operator"), ("角色", "role"),
             ("机器名", "machine"), ("Windows账户", "win_account"), ("视图", "view"),
             ("动作", "action"), ("变更摘要", "summary"), ("文件版本", "version"))


class LogTableModel(QAbstractTableModel):
    """修改日志只读模型（只增不改的展示侧；写入只走 identity.make_stamp＋调用方 append）。"""

    def __init__(self, logs: list[LogEntry], parent=None):
        super().__init__(parent)
        self.logs = logs

    def refresh(self) -> None:
        self.beginResetModel()
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.logs)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(_LOG_COLS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return _LOG_COLS[section][0]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or role != Qt.DisplayRole:
            return None
        v = getattr(self.logs[index.row()], _LOG_COLS[index.column()][1])
        return str(v)

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        return Qt.ItemIsSelectable | Qt.ItemIsEnabled  # 无 ItemIsEditable → 只读


class ReviewView(QWidget):
    # I1：携框内 doc（ApprovalDialog.doc）→ MainWindow 对框内 doc 盖章 record_approval，
    # 换 doc 后残留提交不得落到当前 self.doc（非模态框 doc 错配）
    approval_requested = Signal(object, str, str)  # (框内doc, 结论, 意见)
    compare_requested = Signal()           # → MainWindow 对照打开第二窗口

    def __init__(self, doc: QuoteDoc, p: TaxProfile, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.p = p
        self._approval_dialogs: list[ApprovalDialog] = []  # I1：追踪已开审批框
        # ---- 审批摘要块（doc 概况 ＋ review.summary 各字段） ----
        self.lbl_sum_config = QLabel()
        self.lbl_sum_customer = QLabel()
        self.lbl_sum_status = QLabel()
        self.lbl_sum_approval_status = QLabel()
        self.lbl_sum_approver = QLabel()
        self.lbl_sum_approval_time = QLabel()
        self.lbl_sum_approval_opinion = QLabel()
        self.lbl_sum_floor = QLabel("—")
        self.lbl_sum_quote = QLabel("—")
        self.lbl_sum_profit = QLabel("—")
        self.lbl_sum_markup = QLabel("—")
        self.lbl_sum_margin = QLabel("—")
        self.lbl_sum_ordinary = QLabel("—")
        self.lbl_sum_max_rate = QLabel("—")
        self.lbl_sum_min_rate = QLabel("—")
        self.lbl_sum_below_floor = QLabel("—")
        self.lbl_sum_expired = QLabel("—")
        self.lbl_sum_valid_until = QLabel()
        self.lbl_sum_version = QLabel()
        self.lbl_sum_hint = QLabel()
        self.lbl_sum_hint.setObjectName("lbl_sum_hint")
        self.lbl_sum_hint.setWordWrap(True)
        pairs = (("配置名", self.lbl_sum_config), ("客户", self.lbl_sum_customer),
                 ("状态", self.lbl_sum_status), ("审批状态", self.lbl_sum_approval_status),
                 ("审批人", self.lbl_sum_approver), ("审批时间", self.lbl_sum_approval_time),
                 ("审批意见", self.lbl_sum_approval_opinion), ("底价", self.lbl_sum_floor),
                 ("客户报价", self.lbl_sum_quote), ("利润(不含税)", self.lbl_sum_profit),
                 ("加成率", self.lbl_sum_markup), ("毛利率", self.lbl_sum_margin),
                 ("普票统计", self.lbl_sum_ordinary), ("最高件率", self.lbl_sum_max_rate),
                 ("最低件率", self.lbl_sum_min_rate), ("低于底价", self.lbl_sum_below_floor),
                 ("已过期", self.lbl_sum_expired), ("有效期", self.lbl_sum_valid_until),
                 ("文件版本", self.lbl_sum_version))
        grid = QGridLayout()
        for i, (cap, lab) in enumerate(pairs):
            lab.setObjectName(f"lbl_sum_{cap}")
            capw = QLabel(cap)
            capw.setStyleSheet("color: gray;")
            grid.addWidget(capw, i // 3 * 2, i % 3)
            grid.addWidget(lab, i // 3 * 2 + 1, i % 3)
        # ---- 按钮：审批意见 / 对照打开 ----
        self.btn_approval = QPushButton("填写审批意见")
        self.btn_compare = QPushButton("对照打开")
        self.btn_approval.clicked.connect(self._open_approval_dialog)
        self.btn_compare.clicked.connect(lambda: self.compare_requested.emit())
        btn_row = QHBoxLayout()
        btn_row.addWidget(self.btn_approval)
        btn_row.addWidget(self.btn_compare)
        btn_row.addStretch(1)
        # ---- 只读明细表 ----
        self.table = QTableView()
        self.model = QuoteTableModel(doc, "审阅", p)
        self.table.setModel(self.model)
        self.table.horizontalHeader().setStretchLastSection(True)
        # ---- 修改日志表（只读） ----
        self.log_table = QTableView()
        self.log_model = LogTableModel(doc.logs)
        self.log_table.setModel(self.log_model)
        self.log_table.horizontalHeader().setStretchLastSection(True)
        lay = QVBoxLayout(self)
        lay.addLayout(grid)
        lay.addWidget(self.lbl_sum_hint)
        lay.addLayout(btn_row)
        lay.addWidget(QLabel("部件明细（审阅视图全列只读）"))
        lay.addWidget(self.table, 2)
        lay.addWidget(QLabel("修改日志（只增不改，只读展示）"))
        lay.addWidget(self.log_table, 1)
        self.refresh_summary()

    def set_doc(self, doc: QuoteDoc) -> None:
        """载入文件后换 doc：重建明细/日志模型（MainWindow 随后 refresh_pricing）。"""
        self.doc = doc
        self.model = QuoteTableModel(doc, "审阅", self.p)
        self.table.setModel(self.model)
        self.log_model = LogTableModel(doc.logs)
        self.log_table.setModel(self.log_model)

    def _open_approval_dialog(self) -> None:
        dlg = ApprovalDialog(self.doc, self)  # 非模态；WA_DeleteOnClose 防残留（M4）
        # I1：经转发层携框内 doc 再 re-emit（直连信号无法携带 dlg.doc）
        dlg.approval_requested.connect(
            lambda conclusion, opinion, d=dlg: self._relay_approval(d, conclusion, opinion))
        self._approval_dialogs.append(dlg)
        dlg.destroyed.connect(self._forget_approval_dialog)
        dlg.show()

    def _relay_approval(self, dlg: ApprovalDialog, conclusion: str, opinion: str) -> None:
        self.approval_requested.emit(dlg.doc, conclusion, opinion)

    def _forget_approval_dialog(self, obj) -> None:
        if obj in self._approval_dialogs:
            self._approval_dialogs.remove(obj)

    def close_approval_dialogs(self) -> None:
        """I1：MainWindow.load_file 换 doc 时关闭绑定旧 doc 的已开审批框。"""
        for dlg in list(self._approval_dialogs):
            dlg.close()

    def refresh_summary(self) -> None:
        """刷新审批摘要＋日志表。空明细/计算错误/非有限 → 降级提示，绝不抛。"""
        self.log_model.refresh()
        # doc 概况（与定价无关，直接读）
        self.lbl_sum_config.setText(self.doc.config_name)
        self.lbl_sum_customer.setText(self.doc.customer or "—")
        self.lbl_sum_status.setText(self.doc.status)
        self.lbl_sum_approval_status.setText(self.doc.approval_status)
        self.lbl_sum_approver.setText(self.doc.approver or "—")
        self.lbl_sum_approval_time.setText(self.doc.approval_time or "—")
        self.lbl_sum_approval_opinion.setText(self.doc.approval_opinion or "—")
        self.lbl_sum_valid_until.setText(self.doc.valid_until or "—")
        self.lbl_sum_version.setText(str(self.doc.version))
        if not self.doc.lines:  # review.summary 空明细会抛 → 前置守卫
            self._reset_summary_values("部件明细为空，无法生成审批摘要")
            return
        try:
            s = review.summary(self.doc, self.p)
        except (ValueError, ArithmeticError) as e:
            self._reset_summary_values(f"计算错误：{e}（请检查利润率/发票类型）")
            return
        if not (s.floor.is_finite() and s.quote.is_finite() and s.profit_excl.is_finite()
                and s.markup.is_finite() and s.margin.is_finite()):
            self._reset_summary_values("存在非有限数值（NaN/Infinity），请检查利润率/发票类型")
            return
        self.lbl_sum_hint.setText("")
        self.lbl_sum_floor.setText(str(s.floor))
        self.lbl_sum_quote.setText(str(s.quote))
        self.lbl_sum_profit.setText(str(s.profit_excl))
        self.lbl_sum_markup.setText(f"{pct2(s.markup)}%")
        self.lbl_sum_margin.setText(f"{pct2(s.margin)}%")
        self.lbl_sum_ordinary.setText(f"{s.ordinary_count} 件，增值税影响 {s.ordinary_tax_impact}")
        self.lbl_sum_max_rate.setText(f"{s.max_rate_line[0]}（{pct2(s.max_rate_line[1])}%）")
        self.lbl_sum_min_rate.setText(f"{s.min_rate_line[0]}（{pct2(s.min_rate_line[1])}%）")
        self.lbl_sum_below_floor.setText("是" if s.below_floor else "否")
        self.lbl_sum_expired.setText("是" if s.expired else "否")

    def _reset_summary_values(self, hint: str) -> None:
        for lab in (self.lbl_sum_floor, self.lbl_sum_quote, self.lbl_sum_profit,
                    self.lbl_sum_markup, self.lbl_sum_margin, self.lbl_sum_ordinary,
                    self.lbl_sum_max_rate, self.lbl_sum_min_rate,
                    self.lbl_sum_below_floor, self.lbl_sum_expired):
            lab.setText("—")
        self.lbl_sum_hint.setText(hint)

    def show_calc_error(self, msg: str) -> None:
        """MainWindow.refresh_pricing 计算错误路径联动降级（日志表仍刷新）。"""
        self._reset_summary_values(f"计算错误：{msg}（请检查利润率/发票类型）")
        self.log_model.refresh()
