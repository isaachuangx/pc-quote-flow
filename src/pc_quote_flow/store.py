"""xlsx 持久化（Task 4）：原子保存/备份/哈希/版本/派生列重算/只增日志。

结构按 task-4-brief：四表（报价总览/部件明细/审批记录/修改日志），表头第 1 行、数据第 2 行起；
Decimal 以 str 写单元格、读回 Decimal；空值 None↔""/0 按字段类型映射；日期时间 ISO 字符串。
派生列 = pricing.price_doc 输出（附录B为唯一数学权威，不新造公式）：save 时写入，
load 时重算（spec §9「程序打开即重算」）；仅当哈希不一致（外部改动）且非 .bak 时才回写
刷新表内派生单元格（干净 load 零写盘；.bak 永不改写；回写遇 OSError 降级为警告）。
加成率/毛利率列写百分比显示值（money.pct2，B.1「百分比显示保留 2 位小数」）。
内容哈希排除版本号/日志/派生列 → 仅追加日志再 save 不触发外部改动警告。
日志只增不改（红线4）；save 盖章九字段齐全，version 自动 +1 并同步 stamp.version。
外部改动只警告不拦截（红线2）；缺表/缺列 → StoreError 中文消息指明缺哪个表/列。
"""
import hashlib
import json
import os
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

import openpyxl
from openpyxl.comments import Comment

from . import pricing
from .money import pct2
from .model import ApprovalRecord, LogEntry, QuoteDoc, QuoteLine

SHEETS = ["报价总览", "部件明细", "审批记录", "修改日志"]

OVERVIEW_COLS = ["配置名", "客户名", "报价日期", "有效期至", "状态", "版本号", "创建人", "修改人", "修改时间", "算法模式", "统一利润率", "整机底价", "整机报价", "利润额(不含税)", "加成率", "毛利率", "审批状态", "审批人", "审批时间", "审批意见", "最近导出人", "导出时间", "导出类型", "内容哈希", "备注"]

LINE_COLS = ["部件名", "型号", "数量", "含税成本单价", "发票类型", "供应商", "平台", "商品链接", "价格已确认", "确认价", "确认发票类型", "单项利润率", "报价尾差调整", "件底价", "件报价", "实际成交价", "实际发票类型", "采购日期", "订单号", "备注"]

APPROVAL_COLS = ["轮次", "时间", "审批人", "角色", "机器名", "Windows账户", "结论", "意见"]

LOG_COLS = ["时间", "操作人", "角色", "机器名", "Windows账户", "视图", "动作", "变更摘要", "文件版本"]

HASH_OVERVIEW_FIELDS = ["配置名", "客户名", "报价日期", "有效期至", "状态", "算法模式", "统一利润率", "审批状态", "审批人", "审批时间", "审批意见", "备注"]

HASH_LINE_FIELDS = [c for c in LINE_COLS if c not in ("件底价", "件报价")]


class StoreError(Exception):
    """读取错误：缺表/缺列/空键行（中文消息指明缺哪个表/列，或哪表哪行键为空）。"""


# 列头 → (dataclass 字段, 类型)。类型：str/int/dec/bool 及可空 dec?/str?（None↔""）。
_OV = {
    "配置名": ("config_name", "str"),
    "客户名": ("customer", "str"),
    "报价日期": ("quote_date", "str"),
    "有效期至": ("valid_until", "str"),
    "状态": ("status", "str"),
    "版本号": ("version", "int"),
    "创建人": ("creator", "str"),
    "修改人": ("modifier", "str"),
    "修改时间": ("modify_time", "str"),
    "算法模式": ("mode", "str"),
    "统一利润率": ("unified_rate", "dec"),
    "审批状态": ("approval_status", "str"),
    "审批人": ("approver", "str"),
    "审批时间": ("approval_time", "str"),
    "审批意见": ("approval_opinion", "str"),
    "最近导出人": ("last_export_by", "str"),
    "导出时间": ("last_export_time", "str"),
    "导出类型": ("last_export_type", "str"),
    "内容哈希": ("content_hash", "str"),
    "备注": ("note", "str"),
}
_LN = {
    "部件名": ("name", "str"),
    "型号": ("model", "str"),
    "数量": ("qty", "int"),
    "含税成本单价": ("unit_price", "dec"),
    "发票类型": ("invoice", "str"),
    "供应商": ("supplier", "str"),
    "平台": ("platform", "str"),
    "商品链接": ("link", "str"),
    "价格已确认": ("confirmed", "bool"),
    "确认价": ("confirm_price", "dec?"),
    "确认发票类型": ("confirm_invoice", "str?"),
    "单项利润率": ("item_rate", "dec?"),
    "报价尾差调整": ("quote_adjust", "dec"),
    "实际成交价": ("actual_price", "dec?"),
    "实际发票类型": ("actual_invoice", "str?"),
    "采购日期": ("purchase_date", "str"),
    "订单号": ("order_no", "str"),
    "备注": ("note", "str"),
}
_AP = {
    "轮次": ("round", "int"),
    "时间": ("time", "str"),
    "审批人": ("approver", "str"),
    "角色": ("role", "str"),
    "机器名": ("machine", "str"),
    "Windows账户": ("win_account", "str"),
    "结论": ("conclusion", "str"),
    "意见": ("opinion", "str"),
}
_LG = {
    "时间": ("time", "str"),
    "操作人": ("operator", "str"),
    "角色": ("role", "str"),
    "机器名": ("machine", "str"),
    "Windows账户": ("win_account", "str"),
    "视图": ("view", "str"),
    "动作": ("action", "str"),
    "变更摘要": ("summary", "str"),
    "文件版本": ("version", "int"),
}

_DERIVED_NOTE = "派生列由程序计算，手改成本后请重新用程序打开"


def content_hash(doc: QuoteDoc) -> str:
    """内容哈希：sha256(json.dumps([总览哈希字段值], [明细各行哈希字段值], [审批记录]))。

    排除版本号/日志/派生列（件底价/件报价）与修改人/时间/导出溯源字段；
    ensure_ascii=False、sort_keys=True、default=str（Decimal→str）保证跨保存稳定。
    """
    ov = [getattr(doc, _OV[c][0]) for c in HASH_OVERVIEW_FIELDS]
    lns = [[getattr(ln, _LN[c][0]) for c in HASH_LINE_FIELDS] for ln in doc.lines]
    aps = [asdict(a) for a in doc.approvals]
    payload = json.dumps([ov, lns, aps], ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _to_cell(value, kind: str):
    """字段值 → 单元格：Decimal 以 str 写入；bool→是/否；None→""。"""
    if kind == "bool":
        return "是" if value else "否"
    if value is None:
        return ""
    if kind in ("dec", "dec?"):
        return str(value)
    return value


def _from_cell(value, kind: str):
    """单元格 → 字段值：空值 None/"" 按类型映射（可空→None，int→0，dec→0，str→""）。"""
    if kind == "bool":
        return value == "是"
    if value is None or value == "":
        if kind in ("dec?", "str?"):
            return None
        if kind == "int":
            return 0
        if kind == "dec":
            return Decimal("0")
        return ""
    if kind == "int":
        return int(value)
    if kind in ("dec", "dec?"):
        return Decimal(str(value))
    return str(value)


def _price(doc: QuoteDoc):
    """派生列唯一来源 pricing.price_doc；空明细时显示 0.00（0/0 无定义，仅显示回退）。"""
    if not doc.lines:
        return None
    return pricing.price_doc(doc.lines, doc.mode, doc.unified_rate, pricing.TaxProfile())


def _overview_derived(dp) -> dict:
    if dp is None:
        return {c: "0.00" for c in ("整机底价", "整机报价", "利润额(不含税)", "加成率", "毛利率")}
    return {
        "整机底价": str(dp.floor),
        "整机报价": str(dp.quote),
        "利润额(不含税)": str(dp.profit_excl),
        "加成率": str(pct2(dp.markup)),
        "毛利率": str(pct2(dp.margin)),
    }


def _write_derived(wb, headers: dict, dp, line_rows=None) -> None:
    """把派生值写入总览第 2 行与明细各数据行（save 与 load 刷新共用）。

    line_rows：load 回写时各明细行的实际 Excel 行号（跳过空行后行号可能不连续）；
    save 时为 None，按连续行 i+2 写入。
    """
    ws = wb["报价总览"]
    for col, val in _overview_derived(dp).items():
        ws.cell(row=2, column=headers["报价总览"][col]).value = val
    ws = wb["部件明细"]
    if dp is not None:
        for i, (f, q) in enumerate(zip(dp.line_floors, dp.line_quotes)):
            r = line_rows[i] if line_rows is not None else i + 2
            ws.cell(row=r, column=headers["部件明细"]["件底价"]).value = str(f)
            ws.cell(row=r, column=headers["部件明细"]["件报价"]).value = str(q)


def _build_workbook(doc: QuoteDoc, dp) -> openpyxl.Workbook:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    headers: dict = {}
    for name, cols in (
        ("报价总览", OVERVIEW_COLS),
        ("部件明细", LINE_COLS),
        ("审批记录", APPROVAL_COLS),
        ("修改日志", LOG_COLS),
    ):
        ws = wb.create_sheet(name)
        ws.append(cols)
        headers[name] = {c: i + 1 for i, c in enumerate(cols)}
    # 报价总览：单行数据（第 2 行）
    ws = wb["报价总览"]
    ws.append([
        _to_cell(getattr(doc, _OV[c][0]), _OV[c][1]) if c in _OV else ""
        for c in OVERVIEW_COLS
    ])
    # 部件明细 / 审批记录 / 修改日志：逐行追加（日志只增不改，全量重写既有行）
    ws = wb["部件明细"]
    for ln in doc.lines:
        ws.append([
            _to_cell(getattr(ln, _LN[c][0]), _LN[c][1]) if c in _LN else ""
            for c in LINE_COLS
        ])
    ws = wb["审批记录"]
    for a in doc.approvals:
        ws.append([_to_cell(getattr(a, _AP[c][0]), _AP[c][1]) for c in APPROVAL_COLS])
    ws = wb["修改日志"]
    for g in doc.logs:
        ws.append([_to_cell(getattr(g, _LG[c][0]), _LG[c][1]) for c in LOG_COLS])
    _write_derived(wb, headers, dp)
    # spec §9：表内注明派生列由程序计算（批注，不影响单元格值）
    wb["报价总览"].cell(row=1, column=headers["报价总览"]["整机底价"]).comment = Comment(_DERIVED_NOTE, "pc-quote-flow")
    wb["部件明细"].cell(row=1, column=headers["部件明细"]["件底价"]).comment = Comment(_DERIVED_NOTE, "pc-quote-flow")
    return wb


def save(doc: QuoteDoc, path: Path, stamp: LogEntry) -> None:
    """原子保存：logs.append(stamp)、version+=1、modifier/modify_time 取自 stamp、
    重算派生列与哈希；写 .tmp → 旧文件 os.replace 为 .bak → tmp os.replace 为 path。

    stamp 由调用方传入且每次保存必须独立（不复用对象）；save 同步 stamp.version
    为最新版本，保证盖章九字段中的文件版本正确（红线4）。
    """
    path = Path(path)
    doc.version += 1
    stamp.version = doc.version
    doc.logs.append(stamp)
    doc.modifier = stamp.operator
    doc.modify_time = stamp.time
    dp = _price(doc)
    doc.content_hash = content_hash(doc)
    wb = _build_workbook(doc, dp)
    tmp = path.with_suffix(".tmp")
    wb.save(tmp)
    wb.close()
    if path.exists():
        os.replace(path, path.with_suffix(".bak"))
    os.replace(tmp, path)


def load(path: Path) -> tuple[QuoteDoc, list[str]]:
    """读入四表 → QuoteDoc；缺表/缺列/空键行 → StoreError（中文指明表/列/行）。

    读入后重算派生列（打开即重算，spec §9）；哈希不一致 → warnings 追加
    「文件曾在程序外被修改」，且仅此时（并且非 .bak）才把派生列原子回写原路径：
    干净 load 零写盘；.bak 永不改写（备份字节原样）；回写遇 OSError（占用/只读）
    降级为警告，仍返回已读 doc。回写只刷派生列，不动哈希/版本/日志（留痕不丢）。
    """
    path = Path(path)
    # 以二进制流打开：.bak 备份同为 xlsx 内容，绕过 openpyxl 的扩展名限制（可恢复上一版）
    with path.open("rb") as fh:
        wb = openpyxl.load_workbook(fh)
    for name in SHEETS:
        if name not in wb.sheetnames:
            wb.close()
            raise StoreError(f"缺少工作表：{name}")
    headers: dict = {}
    for name, cols in (
        ("报价总览", OVERVIEW_COLS),
        ("部件明细", LINE_COLS),
        ("审批记录", APPROVAL_COLS),
        ("修改日志", LOG_COLS),
    ):
        hdr = [c.value for c in wb[name][1]]
        missing = [c for c in cols if c not in hdr]
        if missing:
            wb.close()
            raise StoreError(f"工作表「{name}」缺少列：{'、'.join(missing)}")
        headers[name] = {c: hdr.index(c) + 1 for c in cols}
    # 报价总览（第 2 行）→ QuoteDoc 输入字段
    ws = wb["报价总览"]
    ov = {
        attr: _from_cell(ws.cell(row=2, column=headers["报价总览"][col]).value, kind)
        for col, (attr, kind) in _OV.items()
    }
    doc = QuoteDoc(**ov)
    # 明细/审批/日志：整行全空 → 跳过（尾部格式行是常态）；
    # 键列空但该行其余任一单元格非空 → StoreError（防静默截断丢数据，日志表同样严格）
    line_rows: list[int] = []  # 部件明细各数据行的实际 Excel 行号（回写派生列用）
    for name, spec, cls, key in (
        ("部件明细", _LN, QuoteLine, "部件名"),
        ("审批记录", _AP, ApprovalRecord, "轮次"),
        ("修改日志", _LG, LogEntry, "时间"),
    ):
        ws = wb[name]
        h = headers[name]
        target = {"部件明细": doc.lines, "审批记录": doc.approvals, "修改日志": doc.logs}[name]
        for rownum, row in enumerate(ws.iter_rows(min_row=2), start=2):
            if all(c.value is None or c.value == "" for c in row):
                continue
            first = row[h[key] - 1].value
            if first is None or first == "":
                wb.close()
                raise StoreError(
                    f"工作表「{name}」第 {rownum} 行「{key}」为空，但该行其他单元格非空；"
                    f"请补全键列或整行清空后重新打开"
                )
            target.append(cls(**{
                attr: _from_cell(row[h[col] - 1].value, kind)
                for col, (attr, kind) in spec.items()
            }))
            if name == "部件明细":
                line_rows.append(rownum)
    warnings: list[str] = []
    dirty = doc.content_hash != content_hash(doc)
    if dirty:
        warnings.append("文件曾在程序外被修改")
    # 打开即重算恒发生（spec §9）；持久修复仅在外部改动时落盘，且 .bak 永不改写
    dp = _price(doc)
    if dirty and path.suffix != ".bak":
        tmp = path.with_suffix(".tmp")
        try:
            _write_derived(wb, headers, dp, line_rows)
            wb.save(tmp)
            os.replace(tmp, path)
        except OSError:
            warnings.append("派生列已重算，但文件被占用或只读，未能写回；请关闭 Excel 后重新打开或保存")
            try:
                tmp.unlink(missing_ok=True)  # 尽力清理孤儿 tmp，失败不抛
            except OSError:
                pass
    wb.close()
    return doc, warnings
