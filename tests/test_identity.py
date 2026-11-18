"""操作人身份测试（Task 5）：档案往返、损坏容错、盖章九字段、切换留痕。

全部使用虚构姓名/机器/账户（红线1：真实报价数据永不入库）；
profile 目录用 tmp_path / monkeypatch APPDATA，真实 profile.json 永不入库。
"""
from datetime import datetime

import pytest

from pc_quote_flow.identity import (
    ROLES,
    Profile,
    load_profile,
    make_stamp,
    profile_dir,
    save_profile,
    switch_operator,
)
from pc_quote_flow.model import LogEntry, QuoteDoc


def test_profile_roundtrip(tmp_path):
    """tmp_path 作 base：save→load 相等；ROLES 逐字（brief:10）。"""
    assert ROLES == ["采购", "销售客服", "管理层"]
    p = Profile(name="张三", role="采购", machine="CAIGOU-01", win_account="zhangsan")
    save_profile(p, base=tmp_path)
    assert load_profile(base=tmp_path) == p


def test_load_missing_returns_none(tmp_path):
    """不存在/损坏一律 None，绝不抛异常（裁定：缺字段/非str/非法role 同样 None）。"""
    assert load_profile(base=tmp_path) is None
    f = tmp_path / "profile.json"
    # JSON 解析失败
    f.write_text("{损坏", encoding="utf-8")
    assert load_profile(base=tmp_path) is None
    # 顶层不是对象
    f.write_text("[1, 2]", encoding="utf-8")
    assert load_profile(base=tmp_path) is None
    # 缺字段
    f.write_text('{"name": "张三"}', encoding="utf-8")
    assert load_profile(base=tmp_path) is None
    # 字段非 str
    f.write_text(
        '{"name": "张三", "role": "采购", "machine": 123, "win_account": "zhangsan"}',
        encoding="utf-8",
    )
    assert load_profile(base=tmp_path) is None
    # role 不在 ROLES
    f.write_text(
        '{"name": "张三", "role": "黑客", "machine": "CAIGOU-01", "win_account": "zhangsan"}',
        encoding="utf-8",
    )
    assert load_profile(base=tmp_path) is None


def test_stamp_fields():
    """make_stamp 后 9 字段齐全：operator==name，role/machine/win_account 来自 Profile。"""
    p = Profile(name="李四", role="销售客服", machine="KEFU-01", win_account="kefu01")
    now = datetime(2026, 11, 18, 10, 32, 5)
    stamp = make_stamp(
        p, view="销售视图", action="保存", summary="统一利润率 8%→10%", version=2, now=now
    )
    assert isinstance(stamp, LogEntry)
    assert stamp.time == now.isoformat(timespec="seconds") == "2026-11-18T10:32:05"
    assert stamp.operator == p.name == "李四"
    assert stamp.role == p.role == "销售客服"
    assert stamp.machine == p.machine == "KEFU-01"
    assert stamp.win_account == p.win_account == "kefu01"
    assert stamp.view == "销售视图"
    assert stamp.action == "保存"
    assert stamp.summary == "统一利润率 8%→10%"
    assert stamp.version == 2
    # now=None 默认当前本地朴素时间（秒级，无微秒/时区）
    s2 = make_stamp(p, view="采购视图", action="导出", summary="虚构导出", version=3)
    t = datetime.fromisoformat(s2.time)
    assert t.microsecond == 0 and t.tzinfo is None
    assert abs((datetime.now() - t).total_seconds()) < 5
    # 盖章惯例：每次返回新对象，不复用
    assert s2 is not stamp


def test_switch_logged():
    """switch_operator 后 logs 长度+1，action=="切换操作人"，summary 含新旧姓名。

    旧操作人取 doc.logs[-1]（裁定）：先盖一条日志钉死旧值来源；
    logs 为空回退 creator/modifier；既有日志只增不改（红线4）。
    """
    doc = QuoteDoc(config_name="虚构配置A", version=3, creator="王五")
    old = Profile(name="张三", role="采购", machine="CAIGOU-01", win_account="zhangsan")
    new = Profile(name="李四", role="销售客服", machine="KEFU-01", win_account="kefu01")
    first = make_stamp(old, view="采购视图", action="保存", summary="虚构保存", version=doc.version)
    doc.logs.append(first)
    before = list(doc.logs)
    stamp = switch_operator(doc, new, view="销售视图")
    assert len(doc.logs) == len(before) + 1
    assert stamp is doc.logs[-1]
    assert stamp.action == "切换操作人"
    assert stamp.summary == "张三(采购)→李四(销售客服)"
    assert stamp.operator == "李四" and stamp.role == "销售客服"
    assert stamp.machine == "KEFU-01" and stamp.win_account == "kefu01"
    assert stamp.view == "销售视图"
    assert stamp.version == doc.version == 3
    # 既有日志行原样保留（对象同一性，红线4）
    assert doc.logs[:1] == before
    assert doc.logs[0] is first
    # logs 为空 → 回退 doc.creator（角色空串）
    doc2 = QuoteDoc(config_name="虚构配置B", version=0, creator="王五")
    s2 = switch_operator(doc2, new, view="销售视图")
    assert s2.summary == "王五()→李四(销售客服)"
    assert len(doc2.logs) == 1
    # creator 空 → 回退 doc.modifier
    doc3 = QuoteDoc(config_name="虚构配置B", version=0, modifier="赵六")
    s3 = switch_operator(doc3, new, view="销售视图")
    assert s3.summary == "赵六()→李四(销售客服)"
    # creator/modifier 均空 → 空姓名空角色
    doc4 = QuoteDoc(config_name="虚构配置B", version=0)
    s4 = switch_operator(doc4, new, view="销售视图")
    assert s4.summary == "()→李四(销售客服)"


def test_default_dir_uses_appdata(tmp_path, monkeypatch):
    """monkeypatch APPDATA→tmp：profile_dir 在其下；默认 base 的 save/load 走同一路径。"""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert profile_dir() == tmp_path / "pc-quote-flow"
    p = Profile(name="王五", role="管理层", machine="BOSS-PC", win_account="boss")
    save_profile(p)
    assert (tmp_path / "pc-quote-flow" / "profile.json").is_file()
    assert load_profile() == p


def test_invalid_role_rejected(tmp_path):
    """save_profile role="黑客" → ValueError（brief 钉死；数据卫生，非权限门禁）。"""
    p = Profile(name="赵六", role="黑客", machine="HACK-PC", win_account="zhaoliu")
    with pytest.raises(ValueError):
        save_profile(p, base=tmp_path)
