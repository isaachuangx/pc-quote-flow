"""三种隔离导出（Task 6）：客户报价单/审批文件/采购单（红线5）。

隔离口径（task-6-brief + 裁定 R20）：
- 客户报价单：全新单 sheet，只含对外信息行+件报价明细；任何角落（单元格/批注/
  隐藏行列/文档属性）不含成本/底价/供应商/发票/链接/确认价/实际价/订单号（R20⑪）；
- 审批文件：复用 store._build_workbook 四表（内部文件，允许批注与日志，R20⑤）
  +「审批摘要」sheet（review.summary 十三字段两列键值，R20④）；
- 采购单：全新单 sheet，含内部采购字段但不含报价/利润/底价；发票类型确认优先
  并归一化，订单号/实际成交价恒留空供采购填写（R20⑦）。
数学一律消费 pricing.price_doc / review.summary 输出，不新造公式（红线6）。
低于底价只警告+导出前一次确认，绝不永久阻止（红线2，R20⑩）；空明细守卫镜像
pricing.apply_reverse 先例（R20②）。一次导出一条日志不双重 append（R20①）；
导出不调 store.save、不递增版本，工作文件保存是调用方职责（R20⑧）；导出文件
原子写（tmp+os.replace，store._atomic_write_workbook），且写成功后才改 doc
状态/日志/溯源（终审 T6M1 取代旧 R20⑨「直接 wb.save」：写失败不得留幻影审计；
审批文件内嵌本次留痕，先改后写、失败全量回滚）。日志只增不改（红线4）。
"""
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import openpyxl
from openpyxl.worksheet.worksheet import Worksheet

from . import pricing, review, states, store, tax
from .money import pct2
from .model import LogEntry, QuoteDoc
from .tax import TaxProfile


class NeedsConfirmation(Exception):
    """整机报价低于底价且未确认：UI 弹一次确认后以 confirmed=True 重试（红线2）。"""


def _require_lines(doc: QuoteDoc, label: str) -> None:
    """空明细守卫（R20②）：避免 price_doc/summary 的除零外泄，先校验后写。"""
    if not doc.lines:
        raise ValueError(f"部件明细为空，无法导出{label}")


def _stamp_provenance(doc: QuoteDoc, stamp: LogEntry, label: str) -> None:
    """溯源三字段（R20⑥）：导出人/时间取自盖章，类型取导出标签。"""
    doc.last_export_by = stamp.operator
    doc.last_export_time = stamp.time
    doc.last_export_type = label


def _single_sheet(name: str) -> tuple[openpyxl.Workbook, Worksheet]:
    """全新单 sheet 工作簿（R20⑪）：绝不复用 store._build_workbook（其批注含"成本"）。

    无批注/无隐藏行列/无定义名称；文档属性中性（只留程序名，不含内部字段）。
    """
    wb = openpyxl.Workbook()
    ws = wb.create_sheet(name)
    wb.remove(wb.worksheets[0])  # 移除默认空表，只留单 sheet（同 store._build_workbook 手法）
    wb.properties.creator = "pc-quote-flow"
    wb.properties.lastModifiedBy = "pc-quote-flow"
    return wb, ws


def export_customer(
    doc: QuoteDoc,
    path: Path,
    stamp: LogEntry,
    confirmed: bool = False,
    round_to_yuan: bool = False,
) -> None:
    """客户报价单：信息行（两列键值）+明细（部件名/型号/数量/件报价）；流转→已报价。

    先判低于底价再改 doc（R20⑩）：报价<底价且未确认 → NeedsConfirmation
    （doc 零改动、无日志、无文件）；确认后放行并在日志摘要追加"低于底价确认导出"。
    round_to_yuan=True 时整机报价 ROUND_HALF_UP 到元且省略整个明细表（R20③）。
    一次导出一条日志：states.transition 自身 append，不再单独 append（R20①）。
    """
    _require_lines(doc, "客户报价单")
    dp = pricing.price_doc(doc.lines, doc.mode, doc.unified_rate, TaxProfile())
    below_floor = dp.quote < dp.floor
    if below_floor and not confirmed:
        raise NeedsConfirmation("整机报价低于底价，需确认后导出")
    quote = dp.quote.quantize(Decimal("1"), rounding=ROUND_HALF_UP) if round_to_yuan else dp.quote
    wb, ws = _single_sheet("客户报价单")
    for row in (
        ("配置名", doc.config_name),
        ("客户名", doc.customer),
        ("报价日期", doc.quote_date),
        ("有效期至", doc.valid_until),
        ("整机报价", str(quote)),
        ("导出人", stamp.operator),
        ("导出时间", stamp.time),
        ("来源版本", str(doc.version)),
    ):
        ws.append(row)
    if not round_to_yuan:
        ws.append([])  # 空行分隔信息区与明细区
        ws.append(["部件名", "型号", "数量", "件报价"])
        for ln, q in zip(doc.lines, dp.line_quotes):
            ws.append([ln.name, ln.model, ln.qty, str(q)])
    # T6M1：原子写成功后才改 doc（状态/日志/溯源）——写失败 doc 与 stamp 零改动
    store._atomic_write_workbook(wb, Path(path))
    stamp.action = "导出客户报价单"
    if below_floor:
        stamp.summary = f"{stamp.summary}；低于底价确认导出" if stamp.summary else "低于底价确认导出"
    states.transition(doc, "已报价", stamp)
    _stamp_provenance(doc, stamp, "客户报价单")


def export_approval(doc: QuoteDoc, path: Path, stamp: LogEntry) -> None:
    """审批文件：store 四表全量内部字段 +「审批摘要」sheet；流转→待审批。

    四表复用 store._build_workbook（DRY，结构/派生列/批注一致，R20⑤；内部文件
    允许批注与日志）；溯源先于建簿写入，总览即带导出人/时间/来源版本（版本号列）。
    摘要两列键值：报价侧 13 行（率用 pct2 显示、金额 str、bool→是/否、极值件转 str，
    R20④）＋采购侧汇总 8 行（R45，确认价口径 B.5，消费 review.procurement_summary）。
    """
    _require_lines(doc, "审批文件")
    # 先校验后写：定价/摘要可能 ValueError（非法模式/票种/日期），此时 doc 零改动
    dp = pricing.price_doc(doc.lines, doc.mode, doc.unified_rate, TaxProfile())
    s = review.summary(doc, TaxProfile())
    # R45：采购侧汇总（确认价口径，B.5）——先校验后写，pricing/review 抛错时 doc 零改动
    ps = review.procurement_summary(doc, TaxProfile())
    # T6M1：审批文件内嵌本次流转日志/溯源/状态，必须先改后写；
    # 快照全部 mutation，原子写失败时全量回滚（doc 与 stamp 恢复原样，无幻影审计）
    old_status = doc.status
    old_prov = (doc.last_export_by, doc.last_export_time, doc.last_export_type)
    old_action = stamp.action
    stamp.action = "导出审批文件"
    states.transition(doc, "待审批", stamp)
    _stamp_provenance(doc, stamp, "审批文件")
    wb = store._build_workbook(doc, dp)
    ws = wb.create_sheet("审批摘要")
    ws.append(["字段", "值"])
    for row in (
        ("整机底价", str(s.floor)),
        ("整机报价", str(s.quote)),
        ("利润额(不含税)", str(s.profit_excl)),
        ("加成率", str(pct2(s.markup))),
        ("毛利率", str(pct2(s.margin))),
        ("普票件数", str(s.ordinary_count)),
        ("普票增值税影响", str(s.ordinary_tax_impact)),
        ("最高件率件", f"{s.max_rate_line[0]}:{pct2(s.max_rate_line[1])}"),
        ("最低件率件", f"{s.min_rate_line[0]}:{pct2(s.min_rate_line[1])}"),
        ("低于底价", "是" if s.below_floor else "否"),
        ("已过期", "是" if s.expired else "否"),
        ("有效期至", s.valid_until),
        ("版本", str(s.version)),
    ):
        ws.append(row)
    # R45：采购侧汇总（确认价口径，B.5）——合并审批含采购款项合理性；仅标记不拦截（红线2）
    ws.append([])
    ws.append(["采购侧汇总（确认价口径，B.5）", ""])
    for row in (
        ("确认后底价", str(ps.confirmed_floor)),
        ("确认成本合计(含税)", str(ps.confirmed_cost_incl)),
        ("有效不含税成本", str(ps.cost_excl)),
        ("真实利润(不含税)", str(ps.real_profit)),
        ("报价时预期利润(不含税)", str(ps.expected_profit)),
        ("利润侵蚀", "是" if ps.eroded else "否"),
        ("负利润警告", "是" if ps.negative else "否"),
        ("报价低于确认后底价", "是" if ps.below_confirmed_floor else "否"),
    ):
        ws.append(row)
    try:
        store._atomic_write_workbook(wb, Path(path))
    except Exception:
        doc.status = old_status
        doc.logs.pop()
        doc.last_export_by, doc.last_export_time, doc.last_export_type = old_prov
        stamp.action = old_action
        raise


def export_purchase(doc: QuoteDoc, path: Path, stamp: LogEntry) -> None:
    """采购单：信息行+采购明细；不改状态，直接 append 一条日志（R20①）。

    明细列：部件名/型号/数量/含税成本单价/确认价/发票类型(确认优先+归一化)/
    供应商/平台/商品链接/订单号(留空)/实际成交价(留空)/备注（R20⑦）；
    不含客户报价/利润/底价（红线5）。
    """
    _require_lines(doc, "采购单")
    # 先校验后写：发票归一化可能 ValueError（数据损坏），此时 doc 零改动
    rows = []
    for ln in doc.lines:
        invoice = tax.normalize_invoice(ln.confirm_invoice if ln.confirm_invoice is not None else ln.invoice)
        rows.append([
            ln.name, ln.model, ln.qty, str(ln.unit_price),
            str(ln.confirm_price) if ln.confirm_price is not None else "",
            invoice, ln.supplier, ln.platform, ln.link,
            "", "",  # 订单号/实际成交价恒留空供采购填写（即便 doc 有值，R20⑦）
            ln.note,
        ])
    wb, ws = _single_sheet("采购单")
    for row in (
        ("配置名", doc.config_name),
        ("客户名", doc.customer),
        ("审批状态", doc.approval_status),
        ("导出人", stamp.operator),
        ("导出时间", stamp.time),
        ("来源版本", str(doc.version)),
    ):
        ws.append(row)
    ws.append([])  # 空行分隔信息区与明细区
    ws.append(["部件名", "型号", "数量", "含税成本单价", "确认价", "发票类型", "供应商", "平台", "商品链接", "订单号", "实际成交价", "备注"])
    for row in rows:
        ws.append(row)
    # T6M1：原子写成功后才 append 日志/溯源——写失败 doc 与 stamp 零改动
    store._atomic_write_workbook(wb, Path(path))
    stamp.action = "导出采购单"
    doc.logs.append(stamp)
    _stamp_provenance(doc, stamp, "采购单")
