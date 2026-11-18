"""PyInstaller 打包入口：等价于 python -m pc_quote_flow（含 --selftest）。

src/pc_quote_flow/__main__.py 使用包内相对导入（from .ui.app import main）。
PyInstaller 把入口脚本当作顶层 __main__ 执行，相对导入无法解析——直接运行
`python src/pc_quote_flow/__main__.py` 同样报 ImportError: attempted relative
import with no known parent package（modulegraph 亦警告 Relative import
outside of package）。故此处以绝对导入复用 __main__.py 暴露的同一 main()，
行为与 python -m pc_quote_flow 完全一致；不改动 Task 8 的入口源码。
"""
from pc_quote_flow.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
