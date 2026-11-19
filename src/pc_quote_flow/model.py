"""数据模型（Task 2）：部件行/审批记录/日志条目/报价单。

字段名与顺序即 Interfaces（task-2-brief）；金额一律 Decimal（红线3）。
纯数据类，不做审批/拦截/权限（红线2）；状态流转见 states.py。
"""
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class QuoteLine:
    """部件明细行（对应 xlsx「部件明细」sheet）。

    unit_price 为含税成本单价；confirm_* 为采购确认价/发票；
    item_rate 为单项利润率（None=跟随整机统一利润率）；
    quote_adjust 为反算写回的件报价调整；actual_* 为实际成交回写。
    confirmed=「价格已确认」（采购侧遗留标志，只读、无逻辑消费，不动）；
    customer_confirmed=「客户确认」（R46 销售侧状态标签，整单勾选为其聚合）。
    """

    name: str
    model: str = ""
    qty: int = 1
    unit_price: Decimal = Decimal("0")
    invoice: str = "专票"
    supplier: str = ""
    platform: str = ""
    link: str = ""
    confirmed: bool = False
    confirm_price: Decimal | None = None
    confirm_invoice: str | None = None
    item_rate: Decimal | None = None
    customer_confirmed: bool = False  # R46 客户确认（销售侧）；独立于采购侧遗留 confirmed
    quote_adjust: Decimal = Decimal("0")
    actual_price: Decimal | None = None
    actual_invoice: str | None = None
    purchase_date: str = ""
    order_no: str = ""
    note: str = ""


@dataclass
class ApprovalRecord:
    """审批记录行（对应「审批记录」sheet，支持多轮）。

    程序仅记录管理层结论与意见，不做审批决策（红线2）。
    """

    round: int
    time: str
    approver: str
    role: str
    machine: str
    win_account: str
    conclusion: str
    opinion: str


@dataclass
class LogEntry:
    """修改日志条目（只增不改，红线4）。

    每次写操作盖章：操作人(姓名+角色)+机器名+Windows账户+视图+时间+版本。
    """

    time: str
    operator: str
    role: str
    machine: str
    win_account: str
    view: str
    action: str
    summary: str
    version: int


@dataclass
class QuoteDoc:
    """报价单（对应「报价总览」sheet + 明细/审批记录/修改日志）。

    mode："markup"（成本加成）| "margin"（毛利率）；
    status 只是流转备忘，不是权限门禁（红线2）。
    """

    config_name: str
    customer: str = ""
    quote_date: str = ""
    valid_until: str = ""
    status: str = "询价"
    version: int = 0
    creator: str = ""
    modifier: str = ""
    modify_time: str = ""
    mode: str = "markup"
    unified_rate: Decimal = Decimal("0")
    lines: list[QuoteLine] = field(default_factory=list)
    approvals: list[ApprovalRecord] = field(default_factory=list)
    logs: list[LogEntry] = field(default_factory=list)
    approval_status: str = "未提交"
    approver: str = ""
    approval_time: str = ""
    approval_opinion: str = ""
    last_export_by: str = ""
    last_export_time: str = ""
    last_export_type: str = ""
    content_hash: str = ""
    note: str = ""