"""明细表格模型（Task 8）：列按视图过滤、派生列只读、编辑触发重算与留痕信号。

数学消费 pricing.price_doc 输出（附录B 唯一权威，本层不新造公式）；
可编辑列按角色收口（R43）：销售编辑部件配置与利润率，成本/发票/供应商/平台/商品链接
由采购录入（销售只读展示），采购另编辑确认价/实际价回写；审阅视图全列只读（spec §13.10）。
setData 成功后发射 edited(变更摘要) 信号——由 MainWindow 经 identity.make_stamp
盖章留痕（红线4：每次写操作一条新鲜日志）；模型自身不写 logs（身份与数据分离）。
"""
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import QAbstractTableModel, Qt, Signal

from .. import pricing, tax
from ..money import pct2
from ..model import QuoteDoc
from ..tax import TaxProfile

# 列规格：(表头, 字段, 类型)。类型：str/int/dec/dec?(可空)/pct?(百分比可空)/
# invoice(归一化)/invoice?(可空)/bool/derived(派生只读)。
_SALES_COLS = [
    ("部件名", "name", "str"),
    ("型号", "model", "str"),
    ("数量", "qty", "int"),
    ("含税成本单价", "unit_price", "dec"),
    ("发票类型", "invoice", "invoice"),
    ("供应商", "supplier", "str"),
    ("平台", "platform", "str"),
    ("商品链接", "link", "str"),
    ("单项利润率", "item_rate", "pct?"),
    ("件底价", "line_floors", "derived"),
    ("件报价", "line_quotes", "derived"),
]
# 采购视图 = 销售列 + 采购录入字段 + 尾差 + 备注（Task 9 接线编辑）
_PURCHASE_COLS = _SALES_COLS[:9] + [
    ("价格已确认", "confirmed", "bool"),
    ("确认价", "confirm_price", "dec?"),
    ("确认发票类型", "confirm_invoice", "invoice?"),
    ("实际成交价", "actual_price", "dec?"),
    ("实际发票类型", "actual_invoice", "invoice?"),
    ("采购日期", "purchase_date", "str"),
    ("订单号", "order_no", "str"),
    ("报价尾差调整", "quote_adjust", "dec"),
    ("件底价", "line_floors", "derived"),
    ("件报价", "line_quotes", "derived"),
    ("备注", "note", "str"),
]
_COLUMNS = {"销售": _SALES_COLS, "采购": _PURCHASE_COLS, "审阅": _PURCHASE_COLS}
# 各视图可编辑表头（R43 角色收口：成本/发票/供应商/平台/链接归采购录入，销售只读；
# 审阅只读 spec §13.10。这是 UI 编辑权划分，不是权限门禁——红线2 仍生效）
_EDITABLE = {
    "销售": {"部件名", "型号", "数量", "单项利润率"},
    "采购": {"含税成本单价", "发票类型", "供应商", "平台", "商品链接",
             "确认价", "确认发票类型", "实际成交价", "实际发票类型", "采购日期", "订单号"},
    "审阅": set(),
}


class QuoteTableModel(QAbstractTableModel):
    """明细表模型：doc 为唯一数据源，派生列每次 refresh 重算（不缓存旧值）。"""

    edited = Signal(str)  # setData 成功后的变更摘要（MainWindow 负责盖章）

    def __init__(self, doc: QuoteDoc, view: str, p: TaxProfile, parent=None):
        super().__init__(parent)
        if view not in _COLUMNS:
            raise ValueError(f"未知视图：{view!r}（仅支持 销售/采购/审阅）")
        self.doc = doc
        self.view = view
        self.p = p
        self.cols = _COLUMNS[view]
        self._editable = _EDITABLE[view]
        self._dp = None
        self.refresh()

    # ---- 派生列刷新 ----
    def refresh(self) -> None:
        """重算派生列并通知整表更新；非法输入时派生列留空（MainWindow 另行提示）。"""
        try:
            self._dp = (
                pricing.price_doc(self.doc.lines, self.doc.mode, self.doc.unified_rate, self.p)
                if self.doc.lines else None
            )
        except (ValueError, ArithmeticError):
            self._dp = None
        if self.rowCount() and self.columnCount():
            self.dataChanged.emit(
                self.index(0, 0), self.index(self.rowCount() - 1, self.columnCount() - 1)
            )

    # ---- QAbstractTableModel 接口 ----
    def rowCount(self, parent=None) -> int:
        return 0 if parent is not None and parent.isValid() else len(self.doc.lines)

    def columnCount(self, parent=None) -> int:
        return 0 if parent is not None and parent.isValid() else len(self.cols)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self.cols[section][0]
        return str(section + 1)

    def data(self, index, role=Qt.DisplayRole):
        # EditRole 与 DisplayRole 同值（R23④）：QStyledItemDelegate.setEditorData
        # 取 EditRole 预填编辑器，返回 None 会弹空编辑器（空串回车可清空部件名键列）。
        # 各列解析口径自洽：pct? 显示 pct2/编辑 ÷100、bool 显示是否/编辑 ==是、
        # invoice 双向归一化、int/dec str 往返；derived 由 flags 挡编辑不可达。
        if not index.isValid() or role not in (Qt.DisplayRole, Qt.EditRole):
            return None
        ln = self.doc.lines[index.row()]
        _, field, kind = self.cols[index.column()]
        if kind == "derived":
            if self._dp is None:
                return ""
            vals = self._dp.line_floors if field == "line_floors" else self._dp.line_quotes
            return str(vals[index.row()])
        v = getattr(ln, field)
        if v is None:
            return ""
        if kind == "bool":
            return "是" if v else "否"
        if kind == "pct?":
            return str(pct2(v))
        return str(v)

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        f = Qt.ItemIsSelectable | Qt.ItemIsEnabled
        if self.cols[index.column()][0] in self._editable:
            f |= Qt.ItemIsEditable
        return f

    def setData(self, index, value, role=Qt.EditRole) -> bool:
        if not index.isValid() or role != Qt.EditRole:
            return False
        if not (self.flags(index) & Qt.ItemIsEditable):
            return False
        header, field, kind = self.cols[index.column()]
        ln = self.doc.lines[index.row()]
        try:
            new = self._parse(kind, value)
        except (ValueError, InvalidOperation):
            return False  # 非法输入：拒绝写入，不改字段、不记日志
        # 数据卫生（R23②，非权限门禁）：越界值与键列空串拒绝，不改字段、不记日志
        if field == "qty" and isinstance(new, int) and new < 1:
            return False  # 数量至少 1（0 使件底价/件报价恒 0，无业务意义）
        if field == "unit_price" and isinstance(new, Decimal) and new < 0:
            return False  # 含税成本单价不得为负
        if field == "name" and not str(new).strip():
            return False  # 部件名是 store 键列，空串会使工作文件不可打开（R23④纵深）
        old = getattr(ln, field)
        if new == old:
            return False
        # 显示口径 no-op 守卫（NM1，镜像 app._on_rate_edited）：pct? 列双击回车
        # 会按 pct2 预填的舍入值改写全精度率（如 0.12345→0.12）；显示不变则不写不记。
        # isinstance 收窄：None（空率/清空）显示口径不同，属真实变更，放行。
        if (kind == "pct?" and isinstance(new, Decimal) and isinstance(old, Decimal)
                and pct2(new) == pct2(old)):
            return False
        old_disp = self.data(index, Qt.DisplayRole)
        setattr(ln, field, new)
        self.dataChanged.emit(index, index)
        self.refresh()
        new_disp = self.data(index, Qt.DisplayRole)
        self.edited.emit(f"{ln.name}：{header} {old_disp or '空'}→{new_disp or '空'}")
        return True

    @staticmethod
    def _parse(kind: str, value):
        """按列类型解析编辑值；百分比输入按 % 数（输 12 → 0.12，与 txt_rate 同口径）。

        非有限 Decimal（NaN/Infinity/sNaN）一律按非法输入拒绝（R23②）。
        """
        s = str(value).strip()
        if kind == "str":
            return s
        if kind == "int":
            n = int(s)
            if n < 0:
                raise ValueError("数量不能为负")
            return n
        if kind in ("dec", "dec?"):
            if kind == "dec?" and s == "":
                return None
            d = Decimal(s)
            if not d.is_finite():
                raise ValueError("数值必须是有限值（NaN/Infinity 非法）")
            return d
        if kind == "pct?":
            if s == "":
                return None
            d = Decimal(s)
            if not d.is_finite():
                raise ValueError("数值必须是有限值（NaN/Infinity 非法）")
            return d / 100
        if kind in ("invoice", "invoice?"):
            if kind == "invoice?" and s == "":
                return None
            return tax.normalize_invoice(s)
        if kind == "bool":
            return s == "是"
        raise ValueError(f"不可编辑的列类型：{kind}")
