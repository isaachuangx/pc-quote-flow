"""入口：python -m pc_quote_flow [--selftest] [file.xlsx]。

--selftest 无 GUI 自检（R22⑦）；退出码 0=通过 / 1=失败。
"""
from .ui.app import main

if __name__ == "__main__":
    raise SystemExit(main())
