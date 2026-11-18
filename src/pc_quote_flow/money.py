"""金额舍入与百分比显示（设计文档附录B.1：全程 Decimal，中间量全精度，仅显示/输出时舍入）。"""
from decimal import Decimal, ROUND_HALF_UP

_CENT = Decimal("0.01")


def fen(x: Decimal) -> Decimal:
    """ROUND_HALF_UP（四舍五入）到分（0.01）。"""
    return x.quantize(_CENT, rounding=ROUND_HALF_UP)


def pct2(x: Decimal) -> Decimal:
    """比率 → 百分比显示值，保留 2 位小数（如 0.0909… → 9.09）。"""
    return fen(x * 100)
