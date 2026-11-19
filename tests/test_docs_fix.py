# -*- coding: utf-8 -*-
"""终审修复波 D 组（文档/外观）回归：T10M2 venv 去硬编码 / T10M3 selftest 命令
git-bash 可执行口径 / N1 税率宣称如实。钉死修复后的文档口径，防回退。"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _read(rel):
    return (REPO / rel).read_text(encoding="utf-8")


def test_readme_venv_portable():
    """T10M2：public 仓不得硬编码本机绝对 Python 路径；uv venv --python 3.11 可复现。"""
    t = _read("README.md")
    assert "C:/Users/admin" not in t
    assert "uv venv --python 3.11 .venv" in t


def test_readme_selftest_gitbash_syntax():
    """T10M3：README 开发期自检命令用正斜杠 exe 路径＋$TEMP 日志路径（git-bash 语境），
    不得残留 cmd 专用 `type %TEMP%` 或反斜杠 exe 路径。"""
    t = _read("README.md")
    assert "dist/pc-quote-flow.exe --selftest" in t
    assert "dist\\pc-quote-flow.exe" not in t
    assert "$TEMP/pc-quote-flow-selftest.log" in t
    assert "type %TEMP%" not in t


def test_uat_selftest_gitbash_syntax():
    """T10M3：UAT ⓪ 可选预检命令正斜杠＋退出码双 shell 注明（cmd %errorlevel% / git-bash $?）。"""
    t = _read("docs/uat-checklist.md")
    assert "dist/pc-quote-flow.exe --selftest" in t
    assert "dist\\pc-quote-flow.exe" not in t
    assert "echo $?" in t
    assert "%errorlevel%" in t  # cmd 口径保留但须注明


def test_readme_tax_rate_claim_honest():
    """N1：税率 v1 固定 13%（dialogs.py 只读），README 不得宣称『税率可配置』。"""
    t = _read("README.md")
    assert "税率/纳税人身份可配置" not in t
    assert "v1 固定 13%" in t
