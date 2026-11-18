"""税务口径：发票归一化、件底价贡献、不含税成本（设计文档 §8 与附录B.2/B.5）。

v1 仅一般纳税人（rate=0.13）；small_scale_rate=0.01 为小规模征收率预留参数
（spec §5/§8：底价=含税成本×(1+征收率)，利润=Q/(1+征收率)−含税成本），
v1 不实现界面，v1 公式不使用该参数。
所有函数返回全精度 Decimal，不舍入；舍入只在显示/输出层（money.fen）。
"""
from dataclasses import dataclass
from decimal import Decimal


@dataclass
class TaxProfile:
    """纳税人画像。

    rate：一般纳税人增值税率，v1 固定 0.13（设计文档 §5/附录B）。
    small_scale_rate：小规模征收率预留参数，默认 0.01（spec §5/§8：
        底价=含税成本×(1+征收率)，利润=Q/(1+征收率)−含税成本）；
        v1 不实现，floor_contrib/cost_excl 不使用该字段。
    """

    rate: Decimal = Decimal("0.13")
    small_scale_rate: Decimal = Decimal("0.01")


_INVOICE_ALIASES = {
    "专票": "专票",
    "京东专票": "专票",
    "普票": "普票",
    "普通发票": "普票",
}


def normalize_invoice(s: str) -> str:
    """发票类型归一化：京东专票→专票、普通发票→普票；其余 ValueError。"""
    try:
        return _INVOICE_ALIASES[s]
    except KeyError:
        raise ValueError(f"未知发票类型: {s!r}（仅支持 专票/京东专票/普票/普通发票）") from None


def floor_contrib(unit_price: Decimal, qty: int, invoice: str, p: TaxProfile) -> Decimal:
    """件底价贡献 f_i（全精度）：专票 = 含税行总价；普票 = 含税行总价×(1+rate)。

    普票无进项可抵，其 13% 增值税须从客户身上赚回（附录B.2 推导）。
    """
    invoice = normalize_invoice(invoice)
    line_total = unit_price * qty
    if invoice == "专票":
        return line_total
    return line_total * (1 + p.rate)


def cost_excl(unit_price: Decimal, qty: int, invoice: str, p: TaxProfile) -> Decimal:
    """件不含税成本（全精度）：专票 = 含税行总价/(1+rate)；普票 = 含税行总价。"""
    invoice = normalize_invoice(invoice)
    line_total = unit_price * qty
    if invoice == "专票":
        return line_total / (1 + p.rate)
    return line_total
