"""exports 三种隔离导出测试（task-6-brief Step 1）：附录A虚构夹具 + 附录B期望值。

红线5：客户报价单不含成本/供应商/链接/确认价/实际价/订单号（含隐藏列/批注/属性）；
审批文件含全部内部字段+审批摘要；采购单不含客户报价/利润/底价。
brief 六测试名与最小断言逐字照抄；另加裁定 R20② 空明细守卫钉死测试（不放宽 brief 断言）。
导出文件一律写 tmp_path（红线1：真实数据永不入库）；盖章用 identity.make_stamp 新鲜对象。
"""
from datetime import datetime
from decimal import Decimal as D

import openpyxl
import pytest

from pc_quote_flow import exports, identity, model, pricing, store, tax


def lines(dicts: list[dict]) -> list[model.QuoteLine]:
    """夹具 dict → QuoteLine（price→unit_price，保留原始票种）。"""
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
    """参照 test_review.make_doc：虚构配置B + markup10 默认口径。

    brief：CPU 行设 supplier/link，供隔离断言用。
    """
    defaults = dict(
        customer="示例客户",
        quote_date="2026-11-18",
        valid_until="2026-12-31",
        creator="虚构操作员",
        mode="markup",
        unified_rate=D("0.10"),
    )
    defaults.update(kw)
    doc = model.QuoteDoc(config_name=name, lines=lines(line_dicts), **defaults)
    doc.lines[0].supplier = "虚构供应商"
    doc.lines[0].link = "https://example.com/item"
    return doc


def sales_stamp(action: str, summary: str, version: int, when: datetime = datetime(2026, 11, 18, 14, 5, 0)) -> model.LogEntry:
    """销售客服盖章（identity.make_stamp，九字段齐全；now 固定便于断言时间）。"""
    prof = identity.Profile(name="虚构销售", role="销售客服", machine="XU-PC", win_account="xuni")
    return identity.make_stamp(prof, view="销售视图", action=action, summary=summary, version=version, now=when)


_INFO_LABELS = {"配置名", "客户名", "报价日期", "有效期至", "整机报价", "导出人", "导出时间", "来源版本", "审批状态"}


def info_map(ws) -> dict:
    """信息行（两列键值）→ dict，只认信息标签，不受明细表影响。"""
    return {r[0]: r[1] for r in ws.iter_rows(values_only=True) if r[0] in _INFO_LABELS}


def all_cell_texts(wb) -> list[str]:
    """所有 sheet 所有非空单元格文本（隔离扫描用）。"""
    return [
        str(c.value)
        for ws in wb.worksheets
        for row in ws.iter_rows()
        for c in row
        if c.value is not None
    ]


# ---- brief 六测试（名与最小断言逐字 task-6-brief:18）----


def test_customer_isolation_scan(cfg_b_lines, tmp_path):
    # 配置B markup10 导出 → 所有 sheet 所有单元格+隐藏属性+批注+core properties 无内部 token
    doc = make_doc("虚构配置B", cfg_b_lines)
    doc.version = 3
    cpu = doc.lines[0]
    cpu.confirm_price = D("980")
    cpu.actual_price = D("970")
    cpu.order_no = "虚构订单号"
    cpu.note = "虚构内部备注"
    path = tmp_path / "b_客户.xlsx"
    exports.export_customer(doc, path, sales_stamp("导出客户报价单", "虚构：导出", doc.version))
    wb = openpyxl.load_workbook(path)
    assert set(wb.sheetnames) == {"客户报价单"}
    forbidden = [
        # 内部字样（红线5 + R20⑪：成本/底价/供应商/发票/链接/确认价/实际价/订单号）
        "成本", "底价", "供应商", "发票", "链接", "确认价", "实际价", "订单号",
        # 内部值（供应商名/链接/成本 1000/底价 4130/利润 365.49/确认价/实际价/订单号/备注）
        "虚构供应商", "https://example.com/item", "1000.00", "1000", "4130", "365.49",
        "980", "970", "虚构订单号", "虚构内部备注",
    ]
    for t in all_cell_texts(wb):
        for w in forbidden:
            assert w not in t, f"客户报价单泄漏内部信息：{w!r} in {t!r}"
    # 无批注/无隐藏 sheet/无隐藏行列/无定义名称（R20⑪）
    for ws in wb.worksheets:
        assert ws.sheet_state == "visible"
        assert all(not d.hidden for d in ws.column_dimensions.values())
        assert all(not d.hidden for d in ws.row_dimensions.values())
        for row in ws.iter_rows():
            for c in row:
                assert c.comment is None
    assert len(wb.defined_names) == 0
    # 文档属性中性：不含内部字样与内部值
    for v in vars(wb.properties).values():
        if isinstance(v, str):
            for w in forbidden:
                assert w not in v, f"文档属性泄漏：{w!r} in {v!r}"
    # 对外内容仍在：信息行整机报价 + 明细表（部件名/型号/数量/件报价）
    ws = wb["客户报价单"]
    info = info_map(ws)
    assert info["整机报价"] == "4543.00" and info["来源版本"] == "3"
    assert [c.value for c in ws[10]] == ["部件名", "型号", "数量", "件报价"]
    assert ws.max_row == 19  # 8 信息行 + 1 空行 + 1 表头 + 9 明细
    wb.close()


def test_below_floor_confirm_flow(cfg_b_lines, tmp_path):
    # unified_rate=-0.05 → 报价低于底价：未确认 raise NeedsConfirmation；确认后放行
    doc = make_doc("虚构配置B", cfg_b_lines, unified_rate=D("-0.05"))
    path = tmp_path / "b_客户.xlsx"
    with pytest.raises(exports.NeedsConfirmation, match="低于底价"):
        exports.export_customer(doc, path, sales_stamp("导出客户报价单", "虚构：导出", doc.version))
    # R20⑩：未确认时 doc 零改动、无日志、无文件
    assert doc.status == "询价" and doc.logs == [] and doc.last_export_type == ""
    assert not path.exists()
    stamp = sales_stamp("导出客户报价单", "虚构：确认导出", doc.version)
    exports.export_customer(doc, path, stamp, confirmed=True)
    assert doc.status == "已报价"  # 状态仍变已报价
    assert len(doc.logs) == 1 and doc.logs[-1] is stamp  # R20① 一条日志不双重 append
    assert "低于底价确认导出" in stamp.summary
    assert stamp.action == "导出客户报价单"  # 询价→已报价常规流转，无前缀
    assert doc.last_export_type == "客户报价单" and path.exists()


def test_approval_full_fields(cfg_b_lines, tmp_path):
    # 导出含四表+审批摘要，LINE_COLS 全在，摘要含 4130.00/4543.00/365.49/130.00
    doc = make_doc("虚构配置B", cfg_b_lines, valid_until="2099-12-31")
    doc.version = 3
    path = tmp_path / "b_审批.xlsx"
    stamp = sales_stamp("导出审批文件", "虚构：提交审批", doc.version)
    exports.export_approval(doc, path, stamp)
    wb = openpyxl.load_workbook(path)
    assert wb.sheetnames == store.SHEETS + ["审批摘要"]
    assert [c.value for c in wb["部件明细"][1]] == store.LINE_COLS
    # 总览带导出人/时间/来源版本（brief）
    ov = wb["报价总览"]
    ov_hdr = {c.value: i + 1 for i, c in enumerate(ov[1])}
    assert ov.cell(row=2, column=ov_hdr["最近导出人"]).value == "虚构销售"
    assert ov.cell(row=2, column=ov_hdr["导出时间"]).value == "2026-11-18T14:05:00"
    assert ov.cell(row=2, column=ov_hdr["版本号"]).value == 3
    # 审批摘要：两列键值，报价侧 13 字段逐行一项（R20④）＋R45 采购侧汇总
    # （空行＋节标题＋8 字段＝10 行），含表头共 24 行；全部值断言不放宽
    rows = list(wb["审批摘要"].iter_rows(values_only=True))
    assert rows[0] == ("字段", "值") and len(rows) == 24
    assert rows[14] == (None, None) and rows[15] == ("采购侧汇总（确认价口径，B.5）", None)
    kv = dict(rows[1:])
    assert kv["整机底价"] == "4130.00" and kv["整机报价"] == "4543.00"
    assert kv["利润额(不含税)"] == "365.49" and kv["普票增值税影响"] == "130.00"
    assert kv["加成率"] == "10.00" and kv["毛利率"] == "9.09"
    assert kv["普票件数"] == "1"
    assert kv["最高件率件"] == "CPU（散片）:10.00" and kv["最低件率件"] == "CPU（散片）:10.00"
    assert kv["低于底价"] == "否" and kv["已过期"] == "否"
    assert kv["有效期至"] == "2099-12-31" and kv["版本"] == "3"
    # 修改日志含本次导出记录（内部文件允许日志）；询价→待审批非常规仅前缀留痕
    log_last = [c.value for c in wb["修改日志"][wb["修改日志"].max_row]]
    assert "导出审批文件" in log_last[6]
    wb.close()
    assert doc.status == "待审批"
    assert len(doc.logs) == 1 and doc.logs[-1] is stamp


def test_purchase_no_quote_cols(cfg_b_lines, tmp_path):
    # 采购单表头与单元格不含"整机报价"/"利润"/"底价"字样，含链接与订单号列
    doc = make_doc("虚构配置B", cfg_b_lines)
    cpu = doc.lines[0]
    cpu.confirmed = True
    cpu.confirm_price = D("980")
    cpu.confirm_invoice = "京东专票"
    cpu.order_no = "虚构订单号123"  # 已有值也恒留空（R20⑦）
    cpu.actual_price = D("970")
    path = tmp_path / "b_采购.xlsx"
    stamp = sales_stamp("导出采购单", "虚构：采购", doc.version)
    exports.export_purchase(doc, path, stamp)
    wb = openpyxl.load_workbook(path)
    assert wb.sheetnames == ["采购单"]
    ws = wb["采购单"]
    for t in all_cell_texts(wb):
        for w in ("报价", "利润", "底价"):
            assert w not in t, f"采购单泄漏：{w!r} in {t!r}"
    hdr = [c.value for c in ws[8]]
    assert hdr == ["部件名", "型号", "数量", "含税成本单价", "确认价", "发票类型", "供应商", "平台", "商品链接", "订单号", "实际成交价", "备注"]
    h = {c: i + 1 for i, c in enumerate(hdr)}
    assert ws.cell(row=9, column=h["商品链接"]).value == "https://example.com/item"
    assert ws.cell(row=9, column=h["供应商"]).value == "虚构供应商"
    assert ws.cell(row=9, column=h["发票类型"]).value == "专票"  # 确认优先+京东专票归一化
    assert ws.cell(row=9, column=h["确认价"]).value == "980"
    assert ws.cell(row=9, column=h["含税成本单价"]).value == "1000"
    for r in range(9, 18):  # 订单号/实际成交价恒留空（即便 doc 有值）
        assert ws.cell(row=r, column=h["订单号"]).value in (None, "")
        assert ws.cell(row=r, column=h["实际成交价"]).value in (None, "")
    # 无批注/无隐藏 sheet（R20⑪）
    assert ws.sheet_state == "visible"
    for row in ws.iter_rows():
        for c in row:
            assert c.comment is None
    wb.close()
    assert doc.status == "询价"  # 不改状态
    assert len(doc.logs) == 1 and doc.logs[-1] is stamp and stamp.action == "导出采购单"
    assert doc.last_export_type == "采购单"


def test_status_and_provenance(cfg_b_lines, tmp_path):
    # customer→已报价、approval→待审批；last_export_by==stamp.operator；信息行含来源版本
    doc = make_doc("虚构配置B", cfg_b_lines)
    doc.version = 3
    s1 = sales_stamp("导出客户报价单", "虚构：导出", doc.version)
    p1 = tmp_path / "b_客户.xlsx"
    exports.export_customer(doc, p1, s1)
    assert doc.status == "已报价" and doc.version == 3  # R20⑧ 不 save 不递增版本
    assert doc.last_export_by == s1.operator == "虚构销售"
    assert doc.last_export_time == s1.time == "2026-11-18T14:05:00"
    assert doc.last_export_type == "客户报价单"
    assert len(doc.logs) == 1 and doc.logs[-1] is s1
    wb = openpyxl.load_workbook(p1)
    info = info_map(wb["客户报价单"])
    assert info["来源版本"] == "3" and info["导出人"] == "虚构销售" and info["导出时间"] == s1.time
    wb.close()
    # approval：已报价→待审批非常规，仅前缀留痕不拦截（红线2）
    s2 = sales_stamp("导出审批文件", "虚构：提交审批", doc.version, datetime(2026, 11, 18, 15, 0, 0))
    p2 = tmp_path / "b_审批.xlsx"
    exports.export_approval(doc, p2, s2)
    assert doc.status == "待审批" and s2.action == "非常规流转：导出审批文件"
    assert doc.last_export_type == "审批文件" and doc.last_export_by == s2.operator
    assert doc.last_export_time == s2.time
    assert len(doc.logs) == 2 and doc.logs[-1] is s2
    wb = openpyxl.load_workbook(p2)
    assert wb["报价总览"].cell(row=2, column=6).value == 3  # 版本号列=来源版本
    wb.close()
    # purchase：不改状态，溯源更新
    s3 = sales_stamp("导出采购单", "虚构：采购", doc.version, datetime(2026, 11, 18, 16, 0, 0))
    p3 = tmp_path / "b_采购.xlsx"
    exports.export_purchase(doc, p3, s3)
    assert doc.status == "待审批" and doc.last_export_type == "采购单"
    assert doc.last_export_by == s3.operator and doc.last_export_time == s3.time
    assert len(doc.logs) == 3 and doc.logs[-1] is s3 and s3.action == "导出采购单"
    wb = openpyxl.load_workbook(p3)
    info = info_map(wb["采购单"])
    assert info["来源版本"] == "3" and info["审批状态"] == "未提交"
    wb.close()
    # R20⑧/⑨：只写导出文件本身，无 .tmp/.bak（不调 store.save）
    assert {p.name for p in tmp_path.iterdir()} == {"b_客户.xlsx", "b_审批.xlsx", "b_采购.xlsx"}


def test_round_to_yuan(cfg_b_lines, tmp_path):
    # apply_reverse 到 4555.55 后 round_to_yuan 导出 → 整机报价 4556，无明细表
    doc = make_doc("虚构配置B", cfg_b_lines)
    pricing.apply_reverse(doc, D("4555.55"), "markup", tax.TaxProfile())
    path = tmp_path / "b_客户.xlsx"
    exports.export_customer(doc, path, sales_stamp("导出客户报价单", "虚构：取整导出", doc.version), round_to_yuan=True)
    wb = openpyxl.load_workbook(path)
    ws = wb["客户报价单"]
    assert info_map(ws)["整机报价"] == "4556"  # ROUND_HALF_UP 到元
    assert ws.max_row == 8  # R20③ 省略整个明细表，只留信息行
    assert all("部件名" not in t for t in all_cell_texts(wb))
    wb.close()
    assert doc.status == "已报价" and len(doc.logs) == 1


# ---- 裁定 R20② 钉死测试（不放宽 brief 断言）----


def test_empty_lines_guard(tmp_path):
    # 空明细三入口 ValueError（镜像 pricing.apply_reverse 先例），doc 零改动、无文件
    for fn, label in (
        (exports.export_customer, "客户报价单"),
        (exports.export_approval, "审批文件"),
        (exports.export_purchase, "采购单"),
    ):
        doc = model.QuoteDoc(config_name="虚构空单")
        path = tmp_path / f"empty_{label}.xlsx"
        with pytest.raises(ValueError, match=f"部件明细为空，无法导出{label}"):
            fn(doc, path, sales_stamp("导出", "虚构", 0))
        assert doc.logs == [] and doc.status == "询价" and not path.exists()


# ---- R45：审批文件「审批摘要」sheet 补采购侧汇总（报价侧 13 行不变）----


def test_approval_file_procurement_summary(cfg_b_lines, tmp_path):
    # CPU 确认价 2000 普票 → 审批摘要含采购侧汇总（确认后底价/真实利润/警告标记），报价侧不变
    doc = make_doc("虚构配置B", cfg_b_lines)
    doc.lines[0].confirm_price = D("2000")
    doc.lines[0].confirm_invoice = "普票"
    path = tmp_path / "b_审批.xlsx"
    exports.export_approval(doc, path, sales_stamp("导出审批文件", "虚构：提交审批", doc.version))
    wb = openpyxl.load_workbook(path)
    kv = {r[0]: r[1] for r in wb["审批摘要"].iter_rows(values_only=True)}
    # 采购侧汇总（确认价口径，B.5；审批阶段实际价未填）
    assert kv["确认后底价"] == "5260.00"
    assert kv["确认成本合计(含税)"] == "5000.00"
    assert kv["有效不含税成本"] == "4654.87"
    assert kv["真实利润(不含税)"] == "-634.51"
    assert kv["报价时预期利润(不含税)"] == "365.49"
    assert kv["利润侵蚀"] == "是"
    assert kv["负利润警告"] == "是"
    assert kv["报价低于确认后底价"] == "是"
    # 报价侧 13 字段仍在且不变（红线5：审批文件含全部内部数据）
    assert kv["整机底价"] == "4130.00" and kv["整机报价"] == "4543.00"
    wb.close()
