"""打包脚本：用当前 venv 的 python 调 PyInstaller 构建单文件 windowed exe。

用法（仓库根，git-bash）：.venv/Scripts/python.exe packaging/build.py
产物：dist/pc-quote-flow.exe（build/ 与 dist/ 已被 .gitignore 排除，不入库）。
构建失败（PyInstaller 非零退出或缺产物）→ 本脚本以非零退出码结束。
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    spec = ROOT / "packaging" / "pc-quote-flow.spec"
    cmd = [
        sys.executable, "-m", "PyInstaller",
        str(spec),
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(ROOT / "build"),
        "-y",
    ]
    print("执行：" + " ".join(cmd), flush=True)
    proc = subprocess.run(cmd, cwd=ROOT)
    if proc.returncode != 0:
        print(f"构建失败：PyInstaller 退出码 {proc.returncode}")
        return proc.returncode
    exe = ROOT / "dist" / "pc-quote-flow.exe"
    if not exe.is_file():
        print("构建失败：未找到 dist/pc-quote-flow.exe")
        return 1
    print(f"构建成功：{exe}（{exe.stat().st_size / 1024 / 1024:.1f} MiB）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
