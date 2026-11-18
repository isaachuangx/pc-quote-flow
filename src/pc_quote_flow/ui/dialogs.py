"""对话框（Task 8/9）：首次运行登记 / 反算写回 / 设置 / 审批意见。

登记与设置经 identity.save_profile 写 profile.json（四字段齐全，R17①/R22④）；
反算写回对话框只发 writeback_requested(目标价) 信号——apply_reverse+新鲜盖章+
append 一条+refresh 由 MainWindow 按 R22① 完成（对话框不写日志，避免双重 append）。
审批意见对话框（Task 9）只发 approval_requested(结论,意见) 信号——新鲜盖章+
review.record_approval（内部已留痕）由 MainWindow 完成（R18① 不双重留痕）。
非模态对话框均设 WA_DeleteOnClose，关闭即销毁防子对象累积（M4）。
全部中文文案；身份只做留痕不做权限（红线2）。
"""
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QSpinBox, QVBoxLayout,
)

from .. import identity, pricing
from ..money import fen, pct2
from ..model import QuoteDoc
from ..tax import TaxProfile

_MODE_CN = {"markup": "成本加成", "margin": "销售毛利率"}


class RegisterDialog(QDialog):
    """首次运行登记（切换操作人复用）。

    姓名预填 windows_account() 可编辑；角色默认"销售客服"（ROLES 三选）；
    机器名/Windows账户为只读 OS 锚点，显示并写入 Profile 四字段（R22④）。
    确认后 save_profile；取消则 exec() 返回 Rejected（MainWindow 据此退出）。
    """

    def __init__(self, parent=None, title: str = "首次运行登记"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.profile: identity.Profile | None = None
        form = QFormLayout()
        self.txt_name = QLineEdit(identity.windows_account())
        self.combo_role = QComboBox()
        self.combo_role.addItems(identity.ROLES)
        self.combo_role.setCurrentText("销售客服")
        self.txt_machine = QLineEdit(identity.machine_name())
        self.txt_machine.setReadOnly(True)
        self.txt_win = QLineEdit(identity.windows_account())
        self.txt_win.setReadOnly(True)
        form.addRow("操作人姓名：", self.txt_name)
        form.addRow("角色：", self.combo_role)
        form.addRow("机器名（只读锚点）：", self.txt_machine)
        form.addRow("Windows账户（只读锚点）：", self.txt_win)
        hint = QLabel("身份用于修改日志留痕（事后追责），不做权限控制；视图可任意切换。")
        hint.setWordWrap(True)
        self.btn_ok = QPushButton("登记并继续")
        self.btn_cancel = QPushButton("取消")
        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.btn_ok)
        row.addWidget(self.btn_cancel)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(hint)
        lay.addLayout(row)

    def accept(self) -> None:
        name = self.txt_name.text().strip()
        if not name:
            QMessageBox.warning(self, "登记", "请填写操作人姓名（用于日志留痕）")
            return
        self.profile = identity.Profile(
            name=name,
            role=self.combo_role.currentText(),
            machine=self.txt_machine.text(),
            win_account=self.txt_win.text(),
        )
        identity.save_profile(self.profile)
        super().accept()


class ApprovalDialog(QDialog):
    """审批意见（Task 9）：结论 同意|驳回|需调整 ＋ 意见 → approval_requested 信号。

    非模态 show()；写回链在 MainWindow：identity.make_stamp 新鲜盖章 →
    review.record_approval(doc, conclusion, opinion, stamp, p)（内部置状态并 append
    一条日志，调用方绝不重复 append，R18①）。审批仅记录，不做权限门禁（红线2）。
    """

    approval_requested = Signal(str, str)  # (结论, 意见)

    def __init__(self, doc: QuoteDoc, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose)  # 关闭即销毁，防非模态子对象累积（M4）
        self.doc = doc
        self.setWindowTitle("填写审批意见（仅记录，不做权限门禁）")
        self.lbl_current = QLabel(f"当前状态：{doc.status}｜审批状态：{doc.approval_status}")
        self.combo_conclusion = QComboBox()
        self.combo_conclusion.addItems(["同意", "驳回", "需调整"])
        self.txt_opinion = QLineEdit()
        self.txt_opinion.setPlaceholderText("审批意见（可空）")
        self.btn_ok = QPushButton("提交审批意见")
        self.btn_cancel = QPushButton("取消")
        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)
        form = QFormLayout()
        form.addRow("审批结论：", self.combo_conclusion)
        form.addRow("审批意见：", self.txt_opinion)
        hint = QLabel("结论与意见记入审批记录（多轮只增不改）并流转状态备忘；"
                      "程序不做审批决策，不拦截任何操作。")
        hint.setWordWrap(True)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.btn_ok)
        row.addWidget(self.btn_cancel)
        lay = QVBoxLayout(self)
        lay.addWidget(self.lbl_current)
        lay.addLayout(form)
        lay.addWidget(hint)
        lay.addLayout(row)

    def accept(self) -> None:
        # combo 限定三结论（record_approval 内部再校验）；意见去首尾空白
        self.approval_requested.emit(self.combo_conclusion.currentText(),
                                     self.txt_opinion.text().strip())
        super().accept()


class ReverseDialog(QDialog):
    """反算写回（附录B.4）：输入谈妥的整机报价→预览两率与利润→"写回"发信号。

    非模态（show()）便于对照主窗口四数；写回链在 MainWindow（R22①）。
    """

    writeback_requested = Signal(object)  # Decimal 目标整机报价

    def __init__(self, doc: QuoteDoc, p: TaxProfile, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose)  # 关闭即销毁，防非模态子对象累积（M4）
        self.doc = doc
        self.p = p
        self.setWindowTitle("反算写回（输入谈妥的整机报价）")
        self.txt_target = QLineEdit()
        self.txt_target.setPlaceholderText("目标整机报价，如 4555.55")
        self.lbl_rev_rate = QLabel("—")
        self.lbl_rev_profit = QLabel("—")
        self.btn_preview = QPushButton("预览")
        self.btn_writeback = QPushButton("写回")
        self.btn_preview.clicked.connect(self._preview)
        self.btn_writeback.clicked.connect(self._writeback)
        form = QFormLayout()
        form.addRow("目标整机报价：", self.txt_target)
        form.addRow("反算加成率/毛利率：", self.lbl_rev_rate)
        form.addRow("利润额(不含税)：", self.lbl_rev_profit)
        hint = QLabel("写回按附录B.4：逐件全精度反算统一率、清空单项利润率、尾差落底价最大件；日志记目标价与尾差摘要。")
        hint.setWordWrap(True)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.btn_preview)
        row.addWidget(self.btn_writeback)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(hint)
        lay.addLayout(row)

    def _target(self) -> Decimal | None:
        try:
            target = Decimal(self.txt_target.text().strip())
        except InvalidOperation:
            QMessageBox.warning(self, "反算", "请输入数字目标价，如 4555.55")
            return None
        if not target.is_finite():
            QMessageBox.warning(self, "反算", "目标价必须是有限数值（NaN/Infinity 非法）")
            return None
        return target

    def _preview(self) -> None:
        t = self._target()
        if t is None:
            return
        try:
            dp = pricing.price_doc(self.doc.lines, self.doc.mode, self.doc.unified_rate, self.p)
            if dp.floor == 0:
                raise ValueError("底价为 0，无法反算利润率")
            markup = (t - dp.floor) / dp.floor
            margin = (t - dp.floor) / t
            profit = fen((t - dp.floor) / (1 + self.p.rate))
        except (ValueError, ArithmeticError) as e:
            self.lbl_rev_rate.setText(f"无法反算：{e}")
            self.lbl_rev_profit.setText("—")
            return
        self.lbl_rev_rate.setText(
            f"加成率 {pct2(markup)}% ／ 毛利率 {pct2(margin)}%（当前模式：{_MODE_CN[self.doc.mode]}）"
        )
        self.lbl_rev_profit.setText(str(profit))

    def _writeback(self) -> None:
        t = self._target()
        if t is None:
            return
        self.writeback_requested.emit(t)
        self.accept()


class SettingsDialog(QDialog):
    """设置：操作人姓名/角色、默认算法、报价有效期天数；税率 v1 固定 13% 只读展示。

    默认算法/有效期只影响新建文档；姓名/角色变更由 MainWindow 记切换日志（R22⑧）。
    """

    def __init__(self, profile: identity.Profile, default_mode: str = "markup",
                 valid_days: int = 30, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.profile = profile
        self.default_mode = default_mode
        self.valid_days = valid_days
        form = QFormLayout()
        self.txt_name = QLineEdit(profile.name)
        self.combo_role = QComboBox()
        self.combo_role.addItems(identity.ROLES)
        self.combo_role.setCurrentText(profile.role)
        self.combo_mode = QComboBox()
        self.combo_mode.addItems(["成本加成", "销售毛利率"])
        self.combo_mode.setCurrentText(_MODE_CN[default_mode])
        self.spin_days = QSpinBox()
        self.spin_days.setRange(1, 3650)
        self.spin_days.setValue(valid_days)
        self.lbl_tax = QLabel("13%（一般纳税人，v1 固定；小规模 1% 仅预留）")
        form.addRow("操作人姓名：", self.txt_name)
        form.addRow("角色：", self.combo_role)
        form.addRow("默认算法（新建文档）：", self.combo_mode)
        form.addRow("默认有效期天数（新建文档）：", self.spin_days)
        form.addRow("增值税率：", self.lbl_tax)
        self.btn_ok = QPushButton("保存设置")
        self.btn_cancel = QPushButton("取消")
        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.btn_ok)
        row.addWidget(self.btn_cancel)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addLayout(row)

    def accept(self) -> None:
        name = self.txt_name.text().strip()
        if not name:
            QMessageBox.warning(self, "设置", "请填写操作人姓名（用于日志留痕）")
            return
        self.profile = identity.Profile(
            name=name, role=self.combo_role.currentText(),
            machine=self.profile.machine, win_account=self.profile.win_account,
        )
        identity.save_profile(self.profile)
        self.default_mode = "markup" if self.combo_mode.currentText() == "成本加成" else "margin"
        self.valid_days = self.spin_days.value()
        super().accept()
