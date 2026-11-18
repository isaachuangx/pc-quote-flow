"""审批摘要与结论写回（Task 7）：管理层审阅辅助，仅记录不决策（红线2）。

数学口径：设计文档附录B（B.3 四数）为唯一权威（红线6）——摘要直接消费
pricing.price_doc 输出，不新造公式；件有效加成率 = 件报价/全精度件底价−1
（件底价用 tax.floor_contrib 全精度值，不用显示舍入值，红线3）。
summary 为报价时口径（unit_price），不调 actuals（真实利润属采购回写对照，B.5）。
record_approval 仅记录管理层结论与意见并做状态流转备忘：非常规流转不拦截
（states.transition 只加前缀留痕）；日志只增不改，多轮审批只 append（红线4）。
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from . import pricing, states, tax
from .money import fen
from .model import ApprovalRecord, LogEntry, QuoteDoc
from .tax import TaxProfile

_CONCLUSIONS = ("同意", "驳回", "需调整")
_STATUS_BY_CONCLUSION = {"同意": "已同意", "驳回": "已驳回", "需调整": "需调整"}
_TARGET_BY_CONCLUSION = {"同意": "采购中", "驳回": "已报价", "需调整": "已报价"}


@dataclass
class Summary:
    """审批摘要（task-7-brief:9 十三字段，名序逐字）。

    floor/quote/profit_excl 舍入到分（DocPricing 已是）；markup/margin 全精度
    （显示层再 pct2）；max/min_rate_line 为首个极值件 (name, 件有效加成率)。
    below_floor/expired 只标记不拦截（红线2）。
    """

    floor: Decimal
    quote: Decimal
    profit_excl: Decimal
    markup: Decimal
    margin: Decimal
    ordinary_count: int
    ordinary_tax_impact: Decimal
    max_rate_line: tuple[str, Decimal]
    min_rate_line: tuple[str, Decimal]
    below_floor: bool
    expired: bool
    valid_until: str
    version: int


def summary(doc: QuoteDoc, p: TaxProfile, today: date | None = None) -> Summary:
    """报价时口径审批摘要（B.3 四数 + 普票影响 + 件率分布 + 底价/有效期标记）。

    件有效加成率 = dp.line_quotes[i]/全精度件底价−1（与件报价口径一致，红线3）；
    件底价==0 的件率记 Decimal(0) 防除零；极值取首个极值件（并列取首件）。
    ordinary_tax_impact = fen(P×p.rate)，P=Σ普票行 unit_price×qty（报价时口径）。
    expired：valid_until 空→False；today（默认 date.today()）> 有效期→True；
    格式非法抛 ValueError（数据损坏，由 UI 层捕获）。
    """
    dp = pricing.price_doc(doc.lines, doc.mode, doc.unified_rate, p)
    rates: list[tuple[str, Decimal]] = []
    ordinary_count = 0
    ordinary_total = Decimal("0")
    for i, ln in enumerate(doc.lines):
        f = tax.floor_contrib(ln.unit_price, ln.qty, ln.invoice, p)
        rate = dp.line_quotes[i] / f - 1 if f != 0 else Decimal("0")
        rates.append((ln.name, rate))
        if tax.normalize_invoice(ln.invoice) == "普票":
            ordinary_count += 1
            ordinary_total += ln.unit_price * ln.qty
    # max/min 对并列极值返回首个（Python 语义），即"首个极值件"
    max_rate_line = max(rates, key=lambda t: t[1])
    min_rate_line = min(rates, key=lambda t: t[1])
    if today is None:
        today = date.today()
    expired = bool(doc.valid_until) and today > date.fromisoformat(doc.valid_until)
    return Summary(
        floor=dp.floor,
        quote=dp.quote,
        profit_excl=dp.profit_excl,
        markup=dp.markup,
        margin=dp.margin,
        ordinary_count=ordinary_count,
        ordinary_tax_impact=fen(ordinary_total * p.rate),
        max_rate_line=max_rate_line,
        min_rate_line=min_rate_line,
        below_floor=dp.quote < dp.floor,
        expired=expired,
        valid_until=doc.valid_until,
        version=doc.version,
    )


def record_approval(doc: QuoteDoc, conclusion: str, opinion: str, stamp: LogEntry, p: TaxProfile) -> None:
    """记录管理层审批结论与意见并流转状态（仅记录，不做审批决策，红线2）。

    conclusion ∉ {同意,驳回,需调整} → ValueError（先校验后写，非法结论不改 doc）。
    approvals 只 append（round=len+1，八字段映射自 stamp，红线4）；总览四字段同步。
    同意→采购中；驳回/需调整→已报价。stamp.action 置"审批记录"后交
    states.transition 一次完成置状态+append 日志（非常规时前缀"非常规流转："，
    不拦截）；本函数不再单独 append，避免双重写入（裁定 R18①）。
    p 按 brief 签名保留：记录结论与流转不需重算价，此处不消费。
    """
    if conclusion not in _CONCLUSIONS:
        raise ValueError(f"非法审批结论：{conclusion!r}（仅支持 同意/驳回/需调整）")
    stamp.action = "审批记录"
    states.transition(doc, _TARGET_BY_CONCLUSION[conclusion], stamp)
    doc.approvals.append(
        ApprovalRecord(
            round=len(doc.approvals) + 1,
            time=stamp.time,
            approver=stamp.operator,
            role=stamp.role,
            machine=stamp.machine,
            win_account=stamp.win_account,
            conclusion=conclusion,
            opinion=opinion,
        )
    )
    doc.approval_status = _STATUS_BY_CONCLUSION[conclusion]
    doc.approver = stamp.operator
    doc.approval_time = stamp.time
    doc.approval_opinion = opinion
