"""状态记录测试（Task 2）：常规/非常规流转、任意废弃、日志只增不改。

全部使用虚构值（红线1：真实报价数据永不入库）。
"""
from pc_quote_flow.model import LogEntry, QuoteDoc
from pc_quote_flow.states import STATES, can_transition, transition


def _doc(status: str = "询价") -> QuoteDoc:
    return QuoteDoc(config_name="虚构配置A", status=status)


def _stamp(action: str = "状态变更", version: int = 1) -> LogEntry:
    return LogEntry(
        time="2026-11-18 10:00",
        operator="张三",
        role="销售客服",
        machine="TEST-PC",
        win_account="testuser",
        view="销售视图",
        action=action,
        summary="虚构测试",
        version=version,
    )


def test_valid_path():
    """询价→已报价→客户已确认→待审批→采购中→已完成：每步常规且 logs 递增。"""
    doc = _doc()
    path = ["询价", "已报价", "客户已确认", "待审批", "采购中", "已完成"]
    for frm, to in zip(path, path[1:]):
        assert doc.status == frm
        assert can_transition(frm, to) is True
        n = len(doc.logs)
        transition(doc, to, _stamp(version=n + 1))
        assert doc.status == to
        assert len(doc.logs) == n + 1


def test_reject_back():
    """审批驳回退回已报价：待审批→已报价 是常规流转。"""
    assert can_transition("待审批", "已报价") is True
    doc = _doc("待审批")
    transition(doc, "已报价", _stamp())
    assert doc.status == "已报价"
    assert len(doc.logs) == 1


def test_irregular_not_blocked():
    """询价→已完成：can_transition False，但 transition 仍生效并留痕（不拦截）。"""
    assert can_transition("询价", "已完成") is False
    doc = _doc()
    stamp = _stamp()
    transition(doc, "已完成", stamp)
    assert doc.status == "已完成"
    assert doc.logs[-1] is stamp
    assert "非常规流转" in doc.logs[-1].action


def test_discard_anywhere():
    """除已废弃外，任意状态→已废弃 均为常规流转。"""
    for frm in STATES:
        if frm == "已废弃":
            continue
        assert can_transition(frm, "已废弃") is True
    assert can_transition("已废弃", "已废弃") is False


def test_log_append_only():
    """transition 前后 logs[:n] 不变（只增不改，红线4）；常规与非常规均如此。"""
    doc = _doc()
    transition(doc, "已报价", _stamp(version=1))
    transition(doc, "客户已确认", _stamp(version=2))
    before = list(doc.logs)
    n = len(before)
    transition(doc, "待审批", _stamp(version=3))
    assert len(doc.logs) == n + 1
    assert doc.logs[:n] == before
    assert all(a is b for a, b in zip(doc.logs[:n], before))
    # 非常规流转（待审批→询价）同样不得改动既有日志
    before = list(doc.logs)
    n = len(before)
    transition(doc, "询价", _stamp(version=4))
    assert len(doc.logs) == n + 1
    assert doc.logs[:n] == before
    assert all(a is b for a, b in zip(doc.logs[:n], before))