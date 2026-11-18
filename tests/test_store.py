"""store xlsx 持久化测试（task-4-brief Step 1）：附录A虚构夹具 + 附录B期望值。

数学口径以设计文档附录B为唯一权威（AGENTS.md 红线6）；派生列=pricing.price_doc 输出。
哈希口径（brief）：排除版本号/日志/派生列 → 仅追加日志再 save 不触发外部改动警告。
每次 save 用独立 fresh stamp（T2 Minor-2：不复用同一 stamp 对象）。
"""
from decimal import Decimal as D

import openpyxl
import pytest

from pc_quote_flow import model, store


def lines(dicts: list[dict]) -> list[model.QuoteLine]:
    """夹具 dict → QuoteLine（保留原始票种，归一化在 tax 内部完成）。"""
    return [
        model.QuoteLine(
            name=l["name"],
            model=l["model"],
            qty=l["qty"],
            unit_price=D(l["price"]),
            invoice=l["invoice"],
        )
        for l in dicts
    ]


def make_doc(name: str, line_dicts: list[dict], **kw) -> model.QuoteDoc:
    defaults = dict(
        customer="示例客户",
        quote_date="2026-11-18",
        valid_until="2026-12-31",
        creator="虚构操作员",
        mode="markup",
        unified_rate=D("0.10"),
    )
    defaults.update(kw)
    return model.QuoteDoc(config_name=name, lines=lines(line_dicts), **defaults)


def stamp(action: str) -> model.LogEntry:
    """每次调用返回独立 stamp（九字段齐全；version 由 save 同步为最新版本）。"""
    return model.LogEntry(
        time="2026-11-18T10:00:00",
        operator="虚构操作员",
        role="销售客服",
        machine="XU-PC",
        win_account="xuni",
        view="销售视图",
        action=action,
        summary="虚构摘要",
        version=0,
    )


def cell(path, sheet: str, col: str, row: int = 2):
    """按中文列头读单元格原始值（Decimal 以 str 写入，读回应为 str）。"""
    wb = openpyxl.load_workbook(path)
    ws = wb[sheet]
    headers = [c.value for c in ws[1]]
    v = ws.cell(row=row, column=headers.index(col) + 1).value
    wb.close()
    return v


def test_roundtrip_a(cfg_a_lines, tmp_path):
    doc = make_doc(
        "虚构配置A",
        cfg_a_lines,
        status="已报价",
        approval_status="已同意",
        approver="虚构管理层",
        approval_time="2026-11-18T14:05:00",
        approval_opinion="虚构意见：利润率合理",
        last_export_by="虚构客服",
        last_export_time="2026-11-18T10:33:00",
        last_export_type="客户报价单",
        note="虚构整单备注",
    )
    # 覆盖全部可选输入字段（不影响 price_doc 派生值：确认/实际/供应商等不参与报价计算）
    ln = doc.lines[0]
    ln.model = "虚构型号"
    ln.supplier = "虚构供应商"
    ln.platform = "虚构平台"
    ln.link = "https://example.invalid/item/1"
    ln.confirmed = True
    ln.confirm_price = D("1950")
    ln.confirm_invoice = "专票"
    ln.actual_price = D("1980")
    ln.actual_invoice = "京东专票"
    ln.purchase_date = "2026-11-20"
    ln.order_no = "XU-DING-0001"
    ln.note = "虚构件备注"
    doc.approvals.append(
        model.ApprovalRecord(
            round=1,
            time="2026-11-18T14:05:00",
            approver="虚构管理层",
            role="管理层",
            machine="XU-PC",
            win_account="xuni",
            conclusion="同意",
            opinion="虚构意见：利润率合理",
        )
    )
    path = tmp_path / "a.xlsx"
    store.save(doc, path, stamp("创建文件"))
    loaded, warnings = store.load(path)
    assert warnings == []
    # 全部输入字段与夹具一致（明细/审批逐字段 dataclass 相等）
    assert loaded.lines == doc.lines
    assert loaded.approvals == doc.approvals
    for f in (
        "config_name", "customer", "quote_date", "valid_until", "status",
        "creator", "mode", "unified_rate", "approval_status", "approver",
        "approval_time", "approval_opinion", "last_export_by",
        "last_export_time", "last_export_type", "note",
    ):
        assert getattr(loaded, f) == getattr(doc, f), f
    assert loaded.version == 1
    assert loaded.modifier == "虚构操作员"
    assert loaded.modify_time == "2026-11-18T10:00:00"
    assert loaded.logs == doc.logs
    # 派生列（B.6 例8 / B.7 行2）：save 时以 str 写入单元格
    assert cell(path, "报价总览", "整机底价") == "5800.00"
    assert cell(path, "报价总览", "整机报价") == "6380.00"
    assert cell(path, "报价总览", "利润额(不含税)") == "513.27"
    assert cell(path, "报价总览", "加成率") == "10.00"
    assert cell(path, "报价总览", "毛利率") == "9.09"
    assert cell(path, "部件明细", "件底价", row=2) == "2000.00"
    assert cell(path, "部件明细", "件报价", row=2) == "2200.00"


def test_roundtrip_b(cfg_b_lines, tmp_path):
    doc = make_doc("虚构配置B", cfg_b_lines)
    path = tmp_path / "b.xlsx"
    store.save(doc, path, stamp("创建文件"))
    loaded, warnings = store.load(path)
    assert warnings == []
    assert loaded.lines == doc.lines
    assert loaded.config_name == "虚构配置B"
    # 派生列（B.6 例1/例2 / B.7 行4/5）
    assert cell(path, "报价总览", "整机底价") == "4130.00"
    assert cell(path, "报价总览", "整机报价") == "4543.00"
    assert cell(path, "报价总览", "利润额(不含税)") == "365.49"
    assert cell(path, "报价总览", "加成率") == "10.00"
    assert cell(path, "报价总览", "毛利率") == "9.09"
    # CPU 普票件：f=1000×1.13=1130.00，q=fen(1130×1.1)=1243.00
    assert cell(path, "部件明细", "件底价", row=2) == "1130.00"
    assert cell(path, "部件明细", "件报价", row=2) == "1243.00"


def test_external_edit_warning(cfg_a_lines, tmp_path):
    # Review Focus 2：openpyxl 直接改成本单元格 → load 警告 + 派生列按新成本重算
    doc = make_doc("虚构配置A", cfg_a_lines)
    path = tmp_path / "a.xlsx"
    store.save(doc, path, stamp("创建文件"))
    h1 = cell(path, "报价总览", "内容哈希")
    wb = openpyxl.load_workbook(path)
    ws = wb["部件明细"]
    headers = [c.value for c in ws[1]]
    ws.cell(row=2, column=headers.index("含税成本单价") + 1).value = "2100"
    wb.save(path)
    wb.close()
    loaded, warnings = store.load(path)
    assert any("程序外被修改" in w for w in warnings)
    assert loaded.lines[0].unit_price == D("2100")
    # 打开即重算（spec §9）：B=5800+100=5900.00；Q=6380−2200+2310=6490.00
    assert cell(path, "报价总览", "整机底价") == "5900.00"
    assert cell(path, "报价总览", "整机报价") == "6490.00"
    assert cell(path, "部件明细", "件底价", row=2) == "2100.00"
    assert cell(path, "部件明细", "件报价", row=2) == "2310.00"
    # M3 留痕不丢：回写只刷派生列、不刷哈希单元格 → 外部改动警告持续到下次 save
    assert cell(path, "报价总览", "内容哈希") == h1
    _, warnings2 = store.load(path)
    assert any("程序外被修改" in w for w in warnings2)


def test_missing_sheet_error(cfg_a_lines, tmp_path):
    doc = make_doc("虚构配置A", cfg_a_lines)
    path = tmp_path / "a.xlsx"
    store.save(doc, path, stamp("创建文件"))
    wb = openpyxl.load_workbook(path)
    del wb["部件明细"]
    wb.save(path)
    wb.close()
    with pytest.raises(store.StoreError, match="部件明细"):
        store.load(path)


def test_missing_column_error(cfg_a_lines, tmp_path):
    doc = make_doc("虚构配置A", cfg_a_lines)
    path = tmp_path / "a.xlsx"
    store.save(doc, path, stamp("创建文件"))
    wb = openpyxl.load_workbook(path)
    ws = wb["部件明细"]
    headers = [c.value for c in ws[1]]
    ws.delete_cols(headers.index("发票类型") + 1)
    wb.save(path)
    wb.close()
    with pytest.raises(store.StoreError, match="发票类型"):
        store.load(path)


def test_backup_and_version(cfg_b_lines, tmp_path):
    # Review Focus 4：连续 save 两次 → .bak 存在、version==2、日志只增、旧版可恢复
    doc = make_doc("虚构配置B", cfg_b_lines)
    path = tmp_path / "b.xlsx"
    s1 = stamp("创建文件")
    store.save(doc, path, s1)
    assert doc.version == 1
    assert not path.with_suffix(".bak").exists()  # 首次保存无旧版可备份
    s2 = stamp("保存")
    store.save(doc, path, s2)
    assert doc.version == 2
    bak = path.with_suffix(".bak")
    assert bak.exists()
    # 日志只增不改：两条 save 盖章均在、顺序不变、action 未被叠加前缀（fresh stamp）
    assert doc.logs == [s1, s2]
    assert s1.action == "创建文件" and s2.action == "保存"
    loaded, warnings = store.load(path)
    assert warnings == []
    assert loaded.version == 2
    assert len(loaded.logs) == 2
    assert loaded.logs[0].action == "创建文件" and loaded.logs[0].version == 1
    assert loaded.logs[1].action == "保存" and loaded.logs[1].version == 2
    old, _ = store.load(bak)
    assert old.version == 1 and len(old.logs) == 1  # .bak 可恢复上一版


def test_hash_stable_over_logs(cfg_a_lines, tmp_path):
    # 哈希排除版本号/日志/派生列：仅追加日志再 save → load 无外部改动警告
    doc = make_doc("虚构配置A", cfg_a_lines)
    path = tmp_path / "a.xlsx"
    store.save(doc, path, stamp("创建文件"))
    h1 = cell(path, "报价总览", "内容哈希")
    assert h1
    doc.logs.append(
        model.LogEntry(
            time="2026-11-18T11:00:00",
            operator="虚构客服",
            role="销售客服",
            machine="XU-PC",
            win_account="xuni",
            view="采购视图",
            action="切换视图",
            summary="虚构：仅追加日志",
            version=1,
        )
    )
    store.save(doc, path, stamp("保存"))
    assert cell(path, "报价总览", "内容哈希") == h1
    loaded, warnings = store.load(path)
    assert warnings == []
    assert loaded.content_hash == h1
    assert len(loaded.logs) == 3  # 两次 save 盖章 + 一条手工追加日志，只增


# ---- 修复轮 1（审查 Important-1/Important-2）：空键行严格报错 / 条件回写 ----


@pytest.mark.parametrize(
    "sheet,key_col,rownum",
    [("部件明细", "部件名", 3), ("审批记录", "轮次", 2), ("修改日志", "时间", 2)],
)
def test_blank_key_row_error(cfg_a_lines, tmp_path, sheet, key_col, rownum):
    # I1：清空中间行键单元格（该行其余非空）→ StoreError 指明表名+Excel行号，不得静默截断
    doc = make_doc("虚构配置A", cfg_a_lines)
    if sheet == "审批记录":
        for i in (1, 2):
            doc.approvals.append(
                model.ApprovalRecord(
                    round=i,
                    time=f"2026-11-18T14:0{i}:00",
                    approver="虚构管理层",
                    role="管理层",
                    machine="XU-PC",
                    win_account="xuni",
                    conclusion="同意",
                    opinion="虚构意见",
                )
            )
    path = tmp_path / "a.xlsx"
    store.save(doc, path, stamp("创建文件"))
    if sheet == "修改日志":
        store.save(doc, path, stamp("保存"))  # 两条日志行，清空首行键
    wb = openpyxl.load_workbook(path)
    ws = wb[sheet]
    headers = [c.value for c in ws[1]]
    ws.cell(row=rownum, column=headers.index(key_col) + 1).value = None
    wb.save(path)
    wb.close()
    with pytest.raises(store.StoreError, match=f"{sheet}.*第 {rownum} 行"):
        store.load(path)


def test_fully_blank_rows_skipped(cfg_a_lines, tmp_path):
    # I1：整行全空（中间清空行+尾部格式行）→ 跳过不报错，后续行不截断
    doc = make_doc("虚构配置A", cfg_a_lines)
    path = tmp_path / "a.xlsx"
    store.save(doc, path, stamp("创建文件"))
    wb = openpyxl.load_workbook(path)
    ws = wb["部件明细"]
    for c in ws[3]:  # 清空第 2 条明细整行（含派生列）
        c.value = None
    ws.append([""] * len(store.LINE_COLS))  # 尾部全空行（模拟 Excel 格式行）
    wb.save(path)
    wb.close()
    loaded, warnings = store.load(path)
    assert loaded.lines == doc.lines[:1] + doc.lines[2:]  # 8 件、顺序不变
    assert len(loaded.logs) == 1
    assert any("程序外被修改" in w for w in warnings)  # 内容变化 → 警告并回写
    # 回写派生列须落在实际数据行号上（第 3 行已跳过，不得错位）
    # 去掉主板 1000 后：B=5800−1000=4800.00；Q=6380−1100=5280.00（全专票，已用 Decimal 独立核算）
    assert cell(path, "部件明细", "件底价", row=4) == "800.00"
    assert cell(path, "报价总览", "整机底价") == "4800.00"
    assert cell(path, "报价总览", "整机报价") == "5280.00"


def test_clean_load_no_rewrite(cfg_a_lines, tmp_path):
    # I2-③：干净 load（哈希一致）零写盘——字节/mtime 不变、无 .tmp 孤儿
    doc = make_doc("虚构配置A", cfg_a_lines)
    path = tmp_path / "a.xlsx"
    store.save(doc, path, stamp("创建文件"))
    before, mtime = path.read_bytes(), path.stat().st_mtime_ns
    loaded, warnings = store.load(path)
    assert warnings == []
    assert loaded.lines == doc.lines
    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == mtime
    assert not path.with_suffix(".tmp").exists()


def test_load_bak_never_rewrites(cfg_b_lines, tmp_path):
    # I2-②：load(.bak) 永不改写备份——干净与被手改的备份均字节原样
    doc = make_doc("虚构配置B", cfg_b_lines)
    path = tmp_path / "b.xlsx"
    store.save(doc, path, stamp("创建文件"))
    store.save(doc, path, stamp("保存"))
    bak = path.with_suffix(".bak")
    before, mtime = bak.read_bytes(), bak.stat().st_mtime_ns
    old, warnings = store.load(bak)
    assert warnings == []
    assert old.version == 1 and len(old.logs) == 1
    assert bak.read_bytes() == before
    assert bak.stat().st_mtime_ns == mtime
    # 手改备份：照常警告+内存重算，但备份字节仍原样（取证原样性）
    with bak.open("rb") as fh:
        wb = openpyxl.load_workbook(fh)
    ws = wb["部件明细"]
    headers = [c.value for c in ws[1]]
    ws.cell(row=2, column=headers.index("含税成本单价") + 1).value = "1100"
    wb.save(bak)
    wb.close()
    before2, mtime2 = bak.read_bytes(), bak.stat().st_mtime_ns
    old2, warnings2 = store.load(bak)
    assert any("程序外被修改" in w for w in warnings2)
    assert old2.lines[0].unit_price == D("1100")
    assert bak.read_bytes() == before2
    assert bak.stat().st_mtime_ns == mtime2
    assert not bak.with_suffix(".tmp").exists()


def test_writeback_failure_degrades(cfg_a_lines, tmp_path, monkeypatch):
    # I2-①：回写遇 OSError（Excel 占用/只读）→ 降级警告，仍返回 doc，清理孤儿 .tmp
    doc = make_doc("虚构配置A", cfg_a_lines)
    path = tmp_path / "a.xlsx"
    store.save(doc, path, stamp("创建文件"))
    wb = openpyxl.load_workbook(path)
    ws = wb["部件明细"]
    headers = [c.value for c in ws[1]]
    ws.cell(row=2, column=headers.index("含税成本单价") + 1).value = "2100"
    wb.save(path)
    wb.close()
    before = path.read_bytes()

    def locked(*a, **kw):
        raise PermissionError("模拟：文件被 Excel 占用")

    monkeypatch.setattr(store.os, "replace", locked)
    loaded, warnings = store.load(path)  # 不得抛异常
    assert loaded.lines[0].unit_price == D("2100")
    assert any("程序外被修改" in w for w in warnings)
    assert any("未能写回" in w for w in warnings)
    assert path.read_bytes() == before  # 原文件完好
    assert not path.with_suffix(".tmp").exists()  # 孤儿 tmp 已清理
