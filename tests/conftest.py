"""pytest 共享夹具：附录A虚构配置A/B（测试只用虚构值，真实报价数据永不入库）。

部件名/数量/含税单价/票种逐字照抄设计文档附录A两张表；
附录A无型号列，model 一律空串（与 Task 2 QuoteLine.model 默认值一致）。
"""
import os

import pytest

# GUI 测试离屏渲染（AGENTS.md §3）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _line(name: str, price: str, invoice: str, qty: int = 1, model: str = "") -> dict:
    return {"name": name, "model": model, "qty": qty, "price": price, "invoice": invoice}


@pytest.fixture
def cfg_a_lines() -> list[dict]:
    """虚构配置A（全部专票）：采购 5800，C=5132.74，B=5800.00，应缴增值税 0。"""
    return [
        _line("CPU（盒装）", "2000", "专票"),
        _line("主板", "1000", "专票"),
        _line("内存 32G 套条", "800", "京东专票"),
        _line("固态 500G", "600", "京东专票"),
        _line("机械 2TB", "900", "专票"),
        _line("电源 650W", "300", "专票"),
        _line("散热双塔", "100", "专票"),
        _line("机箱", "80", "专票"),
        _line("风扇 120mm", "20", "专票"),
    ]


@pytest.fixture
def cfg_b_lines() -> list[dict]:
    """虚构配置B（CPU 普票，其余专票）：采购 4000，C=3654.87，B=4130.00，应缴增值税 130.00。"""
    return [
        _line("CPU（散片）", "1000", "普票"),
        _line("主板", "1000", "专票"),
        _line("内存 16G", "400", "京东专票"),
        _line("固态 500G", "600", "专票"),
        _line("机械 1TB", "500", "京东专票"),
        _line("电源 650W", "300", "专票"),
        _line("散热双塔", "100", "专票"),
        _line("机箱", "80", "专票"),
        _line("风扇 120mm", "20", "专票"),
    ]
