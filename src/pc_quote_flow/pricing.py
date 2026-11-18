"""报价计算（Task 3）：四数/单项覆盖/反算写回/实际利润。

数学口径：设计文档附录B（B.1–B.5）为唯一权威（AGENTS.md 红线6）。
- 金额一律 Decimal，中间量全精度，仅输出时 ROUND_HALF_UP 到分（红线3）；
- 件报价由全精度件底价计算（不是显示舍入值，B.1/B.6 例7）；
- 整机报价 Q = Σ 舍入后件报价（明细合计=总价）；整机底价 B = fen(Σ全精度件底价)。
本模块不做审批/拦截/权限（红线2）；apply_reverse 只返回日志摘要文本，
不写 doc.logs——盖章与只增写入由调用方负责（红线4）。
"""
from dataclasses import dataclass
from decimal import Decimal

from . import tax
from .money import fen
from .model import QuoteDoc, QuoteLine
from .tax import TaxProfile

_MODES = ("markup", "margin")


def _check_mode(mode: str) -> None:
    if mode not in _MODES:
        raise ValueError(f"未知算法模式: {mode!r}（仅支持 markup/margin）")


def line_quote(floor: Decimal, rate: Decimal, mode: str) -> Decimal:
    """件报价 q_i（舍入到分，B.3）：markup=fen(f_i×(1+r_i))；margin=fen(f_i÷(1−m_i))。

    floor 必须传全精度件底价（B.1：不得用显示舍入值复算）。
    """
    _check_mode(mode)
    if mode == "markup":
        return fen(floor * (1 + rate))
    if rate >= 1:
        raise ValueError(f"毛利率模式件率必须小于 1: {rate}")
    return fen(floor / (1 - rate))


@dataclass
class DocPricing:
    """整机定价结果（B.3 四数 + 件明细）。

    line_floors：显示舍入后的件底价；floor=fen(Σ全精度件底价)；quote=Σline_quotes；
    profit_excl=fen((Q−B)/(1+t))；markup/margin 全精度（显示层再 pct2）。
    """

    line_floors: list[Decimal]
    line_quotes: list[Decimal]
    floor: Decimal
    quote: Decimal
    profit_excl: Decimal
    markup: Decimal
    margin: Decimal


def price_doc(lines: list[QuoteLine], mode: str, unified_rate: Decimal, p: TaxProfile) -> DocPricing:
    """整机定价：件率 = item_rate if not None else unified_rate（单项覆盖优先，B.1/B.3）。

    line_quotes[i] = line_quote(全精度件底价, 件率, mode) + quote_adjust[i]。
    """
    _check_mode(mode)
    floors_full: list[Decimal] = []
    line_quotes: list[Decimal] = []
    for ln in lines:
        f = tax.floor_contrib(ln.unit_price, ln.qty, ln.invoice, p)
        rate = ln.item_rate if ln.item_rate is not None else unified_rate
        floors_full.append(f)
        line_quotes.append(line_quote(f, rate, mode) + ln.quote_adjust)
    floor = fen(sum(floors_full, Decimal("0")))
    quote = sum(line_quotes, Decimal("0"))
    profit_excl = fen((quote - floor) / (1 + p.rate))
    markup = (quote - floor) / floor
    margin = (quote - floor) / quote
    return DocPricing(
        line_floors=[fen(f) for f in floors_full],
        line_quotes=line_quotes,
        floor=floor,
        quote=quote,
        profit_excl=profit_excl,
        markup=markup,
        margin=margin,
    )


def reverse_rate(quote: Decimal, floor: Decimal, mode: str) -> Decimal:
    """反解统一率（全精度，B.4）：markup r*=T/B−1；margin m*=1−B/T。

    实现为 (T−B)/B 与 (T−B)/Q：与 B.4 代数恒等（亦即 B.3 两率定义），
    且避免 Decimal 28 位有效数字下"先除后减 1"的末位精度损失，保证全精度相等。
    """
    _check_mode(mode)
    if mode == "markup":
        return (quote - floor) / floor
    return (quote - floor) / quote


def apply_reverse(doc: QuoteDoc, target: Decimal, mode: str, p: TaxProfile) -> str:
    """反算写回（B.4）：统一率←反解率、模式←mode、清除全部单项覆盖与报价调整；

    重算后尾差 drift = target − Σ件报价 加到**底价最大件**的 quote_adjust
    （其余件 quote_adjust=0），保证 Σ件报价 精确等于 target。
    只修改 doc 字段并返回日志摘要文本；不写 doc.logs（盖章由调用方负责，红线4）。
    """
    _check_mode(mode)
    if not doc.lines:
        raise ValueError("部件明细为空，无法反算写回")
    floor = price_doc(doc.lines, mode, doc.unified_rate, p).floor
    doc.unified_rate = reverse_rate(target, floor, mode)
    doc.mode = mode
    for ln in doc.lines:
        ln.item_rate = None
        ln.quote_adjust = Decimal("0")
    dp = price_doc(doc.lines, mode, doc.unified_rate, p)
    drift = target - dp.quote
    # 底价最大件吸收尾差（按全精度件底价比较；并列取首件）
    idx = max(
        range(len(doc.lines)),
        key=lambda i: tax.floor_contrib(doc.lines[i].unit_price, doc.lines[i].qty, doc.lines[i].invoice, p),
    )
    doc.lines[idx].quote_adjust = drift
    return (
        f"反算写回：目标 {target}（{mode}），统一率 {doc.unified_rate}；"
        f"尾差调整 {drift} → {doc.lines[idx].name}（quote_adjust={drift}）"
    )


@dataclass
class ActualsResult:
    """采购回写对照（B.5）：cost_excl=C'、floor=B'（有效价口径，舍入到分）。

    real_profit=fen(Q/(1+t)−C'全精度)；expected_profit=报价时口径 fen((Q−B)/(1+t))。
    eroded：真实<预期（侵蚀提示）；negative：真实<0（红色警告）。均只提示不拦截（红线2）。
    """

    cost_excl: Decimal
    floor: Decimal
    real_profit: Decimal
    expected_profit: Decimal
    eroded: bool
    negative: bool


def _effective(ln: QuoteLine) -> tuple[Decimal, str]:
    """有效价回退链（B.5）：实际成交价→确认价→报价时成本价；发票类型同链回退。

    取首个非 None 价格所在层，发票从该层起沿链取首个非 None（末层 invoice 必非 None）。
    """
    chain = (
        (ln.actual_price, ln.actual_invoice),
        (ln.confirm_price, ln.confirm_invoice),
        (ln.unit_price, ln.invoice),
    )
    for i, (price, _) in enumerate(chain):
        if price is not None:
            invoice = next(inv for _, inv in chain[i:] if inv is not None)
            return price, invoice
    raise AssertionError("unit_price 不应为 None")  # 不可达：末层价格恒非 None


def actuals(doc: QuoteDoc, p: TaxProfile) -> ActualsResult:
    """采购回写后的真实利润（B.5）：Q 一经发出固定（按 unit_price 报价口径重算），

    C'=Σcost_excl(有效价)、B'=Σfloor_contrib(有效价)（全精度求和后舍入）。
    """
    dp = price_doc(doc.lines, doc.mode, doc.unified_rate, p)
    c_full = Decimal("0")
    b_full = Decimal("0")
    for ln in doc.lines:
        price, invoice = _effective(ln)
        c_full += tax.cost_excl(price, ln.qty, invoice, p)
        b_full += tax.floor_contrib(price, ln.qty, invoice, p)
    real = fen(dp.quote / (1 + p.rate) - c_full)
    expected = dp.profit_excl
    return ActualsResult(
        cost_excl=fen(c_full),
        floor=fen(b_full),
        real_profit=real,
        expected_profit=expected,
        eroded=real < expected,
        negative=real < 0,
    )