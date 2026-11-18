"""状态记录（Task 2）：状态是流转备忘，不是权限门禁（红线2）。

非常规流转不拦截：can_transition 返回 False，transition 仍生效，
仅在日志 action 前缀"非常规流转"留痕。
"""
from pc_quote_flow.model import LogEntry, QuoteDoc

STATES: list[str] = ["询价", "已报价", "客户已确认", "待审批", "采购中", "已完成", "已废弃"]

TRANSITIONS: dict[str, set[str]] = {
    "询价": {"已报价", "已废弃"},
    "已报价": {"客户已确认", "询价", "已废弃"},
    "客户已确认": {"待审批", "已报价", "已废弃"},
    "待审批": {"采购中", "已报价", "已废弃"},
    "采购中": {"已完成", "待审批", "已废弃"},
    "已完成": {"已废弃"},
    "已废弃": set(),
}


def can_transition(frm: str, to: str) -> bool:
    """是否常规流转（仅判断，不拦截）；未知起始状态视为不可。"""
    return to in TRANSITIONS.get(frm, set())


def transition(doc: QuoteDoc, to: str, stamp: LogEntry) -> None:
    """置 doc.status 并追加日志；非常规流转不拦截，stamp.action 前缀"非常规流转"。"""
    if not can_transition(doc.status, to):
        stamp.action = f"非常规流转：{stamp.action}"
    doc.status = to
    doc.logs.append(stamp)