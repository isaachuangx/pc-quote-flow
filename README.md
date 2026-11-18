# pc-quote-flow 装机报价流转工具

面向组装电脑销售公司的 Windows 轻量本地程序：**自动算增值税口径底价 → 按利润率算客户报价 → 管理层审阅辅助 → 采购执行回写**。数据载体是 Excel(.xlsx) 文件，微信/邮件照传；没装程序的电脑用 Excel/WPS 也能看数、存档。

> **定位边界**：本程序是流程优化辅助工具，只做计算、展示、流转记录与审阅辅助。**报价审批、折扣权限由高管理层/公司 ERP 流程决定，程序不做审批决策、不做强制拦截、不做权限控制**。低于底价仅红色警告 + 导出确认提示 + 日志留痕。

## 业务流程

```
询价定价(采购) → 销售报价(销售/客服) → 客户确认
   → 导出审批文件 → 管理层用程序审阅(辅助判断报价合理性)
   → 采购执行(采购操作员核价/下单/回写实际成交价) → 完成
```

## 核心功能

- **底价自动计算**：专票按含税价、普票按含税价×1.13（一般纳税人 13%，普票进项不可抵扣）；税率/纳税人身份可配置。
- **两种利润算法**：成本加成（默认）与销售毛利率，开关切换；统一利润率与单项利润率并存；支持反算（输入谈妥价→反解利润率，可写回）。
- **四数同屏**：客户报价 / 利润额（不含税）/ 加成率 / 销售毛利率。
- **三种导出严格隔离**：客户报价单（脱敏，不带成本/供应商/链接）、审批文件（全部内部数据+合理性摘要）、采购单（确认价+发票+链接+订单号栏）。
- **管理层审阅视图**：只读全字段 + 审批摘要（底价/报价/利润/两率/普票税额影响/单项利润率分布/是否低于底价/有效期）+ 修改日志；可记录审批结论与意见（写回文件，仅记录不门禁）。
- **操作人身份绑定**：每台电脑本机登记姓名+角色（Windows 账户作锚点），每次保存/导出/修改自动盖章，日志只增不改；导出文件带导出人与来源版本。
- **采购回写**：实际成交价/实际发票类型回写后重算真实利润，侵蚀提示（不阻止操作）。
- **状态记录**：询价→已报价→客户已确认→待审批→采购中→已完成，可回退可废弃，全部留痕。

## 技术栈

Python 3.11+ / PySide6 / openpyxl / Decimal 精确计算 / PyInstaller 打包单文件 exe（Windows 10/11 双击即用）。

## 数据卫生（重要）

**本仓库只包含代码、文档与虚构样例。真实报价数据（供应商价格、客户信息）永不入库**：

- 真实工作文件放 `data/`（已 .gitignore 排除）；
- `samples/` 与测试夹具全部为虚构数字（结构与真实业务一致）；
- 仓库暂为 public，日后可随时转 private（GitHub Settings → Danger Zone）。

## 文档

- 设计文档（v5，数学口径见附录B）：[docs/superpowers/specs/2026-11-18-pc-quote-flow-design.md](docs/superpowers/specs/2026-11-18-pc-quote-flow-design.md)
- 实现计划：[docs/superpowers/plans/2026-11-18-pc-quote-flow-v1.md](docs/superpowers/plans/2026-11-18-pc-quote-flow-v1.md)
- 数学验证报告（独立重算对照，供人工核算）：[docs/math-verification-report.md](docs/math-verification-report.md)
- GUI 用户验收清单：[docs/uat-checklist.md](docs/uat-checklist.md)

## 运行方式

### 方式一：单文件 exe（推荐，双击即用）

1. 构建（仓库根，git-bash）：`.venv/Scripts/python.exe packaging/build.py`
   → 产物 `dist/pc-quote-flow.exe`（单文件、windowed；`build/`、`dist/` 不入库）。
2. 双击 `dist/pc-quote-flow.exe`：首次运行登记姓名+角色，随后打开/新建 .xlsx 报价文件。
3. 命令行自检（可选）：`dist\pc-quote-flow.exe --selftest`——windowed 无控制台输出，
   以退出码表达结果（0=通过），同样输出写 `%TEMP%\pc-quote-flow-selftest.log`（末行 SELFTEST OK）。

### 方式二：源码运行（开发/调试）

```bash
# 建 venv 并装依赖（uv + Python 3.11，清华镜像）
uv venv --python "C:/Users/admin/AppData/Local/Programs/Python/Python311/python.exe" .venv
uv pip install --python .venv/Scripts/python.exe --index-url https://pypi.tuna.tsinghua.edu.cn/simple -e ".[dev]"

# 运行（可选直接打开文件）
.venv/Scripts/python.exe -m pc_quote_flow [file.xlsx]

# 无 GUI 自检（附录A/B 断言 + store 往返；stdout 打印，退出码 0=通过）
.venv/Scripts/python.exe -m pc_quote_flow --selftest

# 全量测试 / 独立数学核对 / 生成数学验证报告
.venv/Scripts/python.exe -m pytest tests/ -q
.venv/Scripts/python.exe scripts/verify_math.py
.venv/Scripts/python.exe scripts/verify_math.py --report docs/math-verification-report.md
```

## 状态

设计已确认（v5），v0.1.0 功能实现完成（Task 1–10）。发布闸门：用户/财务按附录B.7
人工核算 + GUI UAT（docs/uat-checklist.md）通过后打 tag `v0.1.0`（见 AGENTS.md §4）。
