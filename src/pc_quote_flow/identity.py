"""操作人身份（Task 5）：自报姓名 + Windows账户/机器名锚点，事后追责而非权限门禁。

身份是"自报姓名 + Windows账户/机器名锚点"（spec 操作人身份与留痕 v4）：
role 校验只是数据卫生，不限制视图、不拦截任何操作（红线2）。
profile.json 存本机 %APPDATA%/pc-quote-flow/，不进报价文件（红线1：真实配置不入库）。
盖章每次生成新 LogEntry（九字段齐全）；日志只增不改（红线4）。
"""
import getpass
import json
import os
import socket
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from pc_quote_flow.model import LogEntry, QuoteDoc

ROLES: list[str] = ["采购", "销售客服", "管理层"]


@dataclass
class Profile:
    """操作人档案：姓名+角色+机器名+Windows账户（每台电脑登记一次，设置里可改）。"""

    name: str
    role: str
    machine: str
    win_account: str


def windows_account() -> str:
    """当前 Windows 登录账户（身份锚点，非权限凭据）。"""
    return getpass.getuser()


def machine_name() -> str:
    """机器名：优先 COMPUTERNAME 环境变量，回退 socket.gethostname()。"""
    return os.environ.get("COMPUTERNAME", socket.gethostname())


def profile_dir(base: Path | None = None) -> Path:
    """档案目录：默认 %APPDATA%/pc-quote-flow（Windows-only）；base 传入时直接用 base。"""
    if base is None:
        return Path(os.environ["APPDATA"]) / "pc-quote-flow"
    return base


def load_profile(base: Path | None = None) -> Profile | None:
    """读 profile.json；不存在/解析失败/缺字段/非str/非法role 一律 None，绝不抛异常。"""
    try:
        data = json.loads((profile_dir(base) / "profile.json").read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        keys = ("name", "role", "machine", "win_account")
        if any(not isinstance(data.get(k), str) for k in keys):
            return None
        if data["role"] not in ROLES:
            return None
        return Profile(
            name=data["name"],
            role=data["role"],
            machine=data["machine"],
            win_account=data["win_account"],
        )
    except (OSError, ValueError):
        # OSError：文件不存在/不可读；ValueError：JSON 解析失败（含编码错误）
        return None


def save_profile(p: Profile, base: Path | None = None) -> None:
    """写 profile.json（UTF-8、ensure_ascii=False、indent=2）；非法 role → ValueError。

    本机配置非报价数据，不做原子写（裁定 YAGNI）；自动创建目录。
    """
    if p.role not in ROLES:
        raise ValueError(f"非法角色：{p.role!r}（可选：{'、'.join(ROLES)}）")
    d = profile_dir(base)
    d.mkdir(parents=True, exist_ok=True)
    (d / "profile.json").write_text(
        json.dumps(asdict(p), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def make_stamp(
    p: Profile,
    view: str,
    action: str,
    summary: str,
    version: int,
    now: datetime | None = None,
) -> LogEntry:
    """生成新盖章（每次新对象，不复用）：九字段齐全，time 本地朴素秒级。

    version 由调用方传入（当前文件版本，下次 save 才 +1）。
    """
    if now is None:
        now = datetime.now()
    return LogEntry(
        time=now.isoformat(timespec="seconds"),
        operator=p.name,
        role=p.role,
        machine=p.machine,
        win_account=p.win_account,
        view=view,
        action=action,
        summary=summary,
        version=version,
    )


def switch_operator(doc: QuoteDoc, new_p: Profile, view: str) -> LogEntry:
    """切换操作人并留痕：旧操作人取最近日志（logs 空则回退 creator/modifier）。

    只 append 新 stamp，绝不改既有日志行（红线4）；version=doc.version 当前值。
    """
    if doc.logs:
        last = doc.logs[-1]
        old_name, old_role = last.operator, last.role
    else:
        old_name, old_role = (doc.creator or doc.modifier or ""), ""
    stamp = make_stamp(
        new_p,
        view=view,
        action="切换操作人",
        summary=f"{old_name}({old_role})→{new_p.name}({new_p.role})",
        version=doc.version,
    )
    doc.logs.append(stamp)
    return stamp
