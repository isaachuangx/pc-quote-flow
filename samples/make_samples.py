"""生成虚构样例 xlsx（Task 4 Step 5）。

全部数字为虚构（设计文档附录A，与 tests/conftest.py 夹具逐字一致）；
真实报价数据永不入库（红线1）。仓库根目录运行：
    .venv/Scripts/python.exe samples/make_samples.py
重复运行先清理旧样例与 .bak，保证生成结果恒为 v1。
"""
from decimal import Decimal as D
from pathlib import Path

from pc_quote_flow import store
from pc_quote_flow.model import LogEntry, QuoteDoc, QuoteLine

# 附录A 虚构配置A（全部专票）：采购 5800，B=5800.00，加成10% → Q=6380.00，利润 513.27
CFG_A = [
    ("CPU（盒装）", "2000", "专票"),
    ("主板", "1000", "专票"),
    ("内存 32G 套条", "800", "京东专票"),
    ("固态 500G", "600", "京东专票"),
    ("机械 2TB", "900", "专票"),
    ("电源 650W", "300", "专票"),
    ("散热双塔", "100", "专票"),
    ("机箱", "80", "专票"),
    ("风扇 120mm", "20", "专票"),
]
# 附录A 虚构配置B（CPU 普票，其余专票）：采购 4000，B=4130.00，加成10% → Q=4543.00，利润 365.49
CFG_B = [
    ("CPU（散片）", "1000", "普票"),
    ("主板", "1000", "专票"),
    ("内存 16G", "400", "京东专票"),
    ("固态 500G", "600", "专票"),
    ("机械 1TB", "500", "京东专票"),
    ("电源 650W", "300", "专票"),
    ("散热双塔", "100", "专票"),
    ("机箱", "80", "专票"),
    ("风扇 120mm", "20", "专票"),
]


def build(name: str, table: list) -> QuoteDoc:
    return QuoteDoc(
        config_name=name,
        customer="示例客户",
        quote_date="2026-11-18",
        valid_until="2026-12-31",
        creator="虚构操作员",
        mode="markup",
        unified_rate=D("0.10"),
        lines=[QuoteLine(name=n, qty=1, unit_price=D(p), invoice=inv) for n, p, inv in table],
    )


def main() -> None:
    here = Path(__file__).resolve().parent
    for name, table in (("虚构配置A", CFG_A), ("虚构配置B", CFG_B)):
        for suffix in (".xlsx", ".bak"):
            (here / f"{name}{suffix}").unlink(missing_ok=True)
        doc = build(name, table)
        stamp = LogEntry(
            time="2026-11-18T09:00:00",
            operator="虚构操作员",
            role="销售客服",
            machine="XU-NI-PC",
            win_account="xuni",
            view="销售视图",
            action="创建文件",
            summary="生成虚构样例（附录A）",
            version=1,
        )
        path = here / f"{name}.xlsx"
        store.save(doc, path, stamp)
        loaded, warnings = store.load(path)
        assert not warnings, f"{name} 样例加载出现警告: {warnings}"
        print(f"已生成 {path.name}：v{loaded.version}，明细 {len(loaded.lines)} 件，日志 {len(loaded.logs)} 条，无外部改动警告")


if __name__ == "__main__":
    main()