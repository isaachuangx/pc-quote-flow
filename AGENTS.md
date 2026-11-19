# AGENTS.md — pc-quote-flow 仓库级开发规则

任何 AI 代理或人类开发者在本仓库工作，必须先阅读并遵守本文件。
口径优先级：**数学计算以设计文档附录B为唯一权威**；流程规则以本文件为准；任务细节见实现计划。

## 0. 开工前必读

1. 设计文档 v5：`docs/superpowers/specs/2026-11-18-pc-quote-flow-design.md`
   ——重点：§1 定位边界、§8 与附录A/B（计算规则与算例）、§13 已定案决定、§14 质量门禁。
2. 实现计划：`docs/superpowers/plans/2026-11-18-pc-quote-flow-v1.md`——按任务顺序执行，不跳步。
3. 本文件。

## 1. 红线（违反即停下纠正，不得变通）

1. **真实报价数据永不入库**。测试/样例/文档只用附录A虚构配置A/B；`data/`、`exports/`、`*_客户_*.xlsx`、`*_审批_*.xlsx` 已被 .gitignore 排除。推送前跑卫生检查（§2 第4步）。
2. **程序不做审批决策、不强制拦截、不做权限控制**。低于底价 = 红色警告 + 导出前一次确认 + 写日志，绝不 disable 任何操作；审批状态只是记录，不是门禁；视图是纯 UI 切换。
3. **金额一律 Decimal**，ROUND_HALF_UP 舍入到分；中间量全精度；件报价由全精度件底价计算；整机报价 = 舍入后件报价之和。
4. **修改日志只增不改**；每次写操作盖章：操作人(姓名+角色)+机器名+Windows账户+视图+时间+版本。
5. **三种导出严格隔离**：客户报价单不含成本/供应商/链接/确认价/实际价/订单号（含隐藏列、批注、文档属性）；审批文件含全部内部数据；采购单不含客户报价/利润/底价。
6. **不得擅改数学口径**。认为公式或测试期望值有误时，先对照附录B核算，在提交说明中写明依据；禁止为凑绿而放宽断言、跳过测试或删除测试。

## 2. 质量门禁（闭环核心规则）

**触发条件——命中任意一条，必须跑完整门禁：**

| 编号 | 触发场景 |
|---|---|
| T1 | 每完成一个功能/模块/任务的实现 |
| T2 | **任何 bug 修复之后**（含测试、UAT、自检中发现的 bug，无论改动多小） |
| T3 | 每次 git commit / push 之前 |
| T4 | 打包 exe / 打发布标签之前 |
| T5 | **每次优化/构建完成、进入 UAT 之前**：对照新代码与运行逻辑评估 `docs/uat-checklist.md` 是否仍匹配，不匹配先更新清单再交用户验收 |

**门禁步骤（按序执行，全绿才算通过）：**

1. 全量回归：`.venv/Scripts/python.exe -m pytest tests/ -v`（跑**全部**已实现模块的测试，不只是本次改动的）
2. 程序自检：`.venv/Scripts/python.exe -m pc_quote_flow --selftest`（Task 8 起可用；之前跳过并在提交说明注明）
3. 独立数学交叉核对：`.venv/Scripts/python.exe scripts/verify_math.py`（Task 3 起可用；脚本**不导入程序计算函数**，按附录B.7 期望值总表独立 Decimal 重算，与程序输出逐项比对）
4. 仓库卫生：`git grep -nE "7893|6574\.04|6616\.04|2547|2008|1549|1199|8080|6715|2630|2180|1085|1550" -- src tests samples README.md docs/superpowers/specs` 必须**零匹配**（扫描代码/测试/样例/README/设计文档；本文件与计划文件因含特征值清单本身而排除）；`git ls-files | grep -E "^(data|exports)/"` 必须为空

**排障循环：** 任一步失败 → 定位根因 → 修复 → **从第 1 步重跑全部门禁**（不是只重跑失败那步）→ 全绿才退出循环。修一个 bug 引入另一个 bug 时，循环继续，直到整体全绿。

**bug 修复标准流程（TDD）：**
① 先写一个**复现该 bug 的失败测试**（确认红）→ ② 修复代码（确认绿）→ ③ 跑完整门禁（T2+T3）→ ④ 提交，说明写清：bug 现象、根因、修法、门禁结果。

**记录：** 每次提交说明末尾附门禁结果，例：
`fix: 反算尾差吸收件选错（门禁: 48 passed, selftest OK, 数学核对 12/12, 卫生 0 匹配）`

**UAT 清单同步（T5 展开）：** 代码、业务流程、视图编辑权、导出字段任一发生变化后，进入 UAT 前必须复核 `docs/uat-checklist.md`：① 阶段顺序是否仍贴合真实业务流（询价→采购确认成本货源→销售报价→客户确认→采购执行核实确认价→合并审批→下单回写→完成）；② 每步「谁/哪个 tab/填哪列/期望数字」是否与现码一致；③ 清单须按业务阶段串成一条端到端场景，不得只堆功能点。不匹配则先改清单再交用户验收。

## 3. 开发流程与环境

- **TDD**：每个任务先按计划写失败测试，确认红，再实现，确认绿。
- **小步提交**：每任务至少一次提交；前缀 feat/fix/test/docs/chore，说明用中文。
- **子代理模式（本项目采用）**：控制者每任务派发一个子代理；派发文本必须要求子代理读本文件 + 设计文档 + 对应任务。子代理返回后，控制者必须**亲自重跑门禁核实**（子代理自报 ≠ 事实），审查代码后再派下一个。
- **环境**：Windows + git-bash（POSIX 语法）；venv 在 `.venv`（uv + Python 3.11）；依赖走清华镜像 `https://pypi.tuna.tsinghua.edu.cn/simple`；GUI 测试 `QT_QPA_PLATFORM=offscreen`（conftest 已设）；给原生工具（git/python/node）传 `C:/...` 正斜杠路径，勿用 `/c/...`。
- **网络**：github.com 网页被阻断，git 走 SSH（全局 insteadOf 已配），gh CLI 已登录；push 失败先重试再诊断，不要擅自改 remote 协议或凭据。

## 4. 发布条件（v0.1.0）

构建完成 → 生成 `docs/math-verification-report.md` → **用户/财务按附录B.7 人工核算通过** + **GUI UAT（docs/uat-checklist.md）通过** → 才打 tag `v0.1.0`。在此之前任何"完成"都只是任务级完成，不是发布。

## 5. 常用命令速查

| 用途 | 命令（仓库根目录，git-bash） |
|---|---|
| 建 venv | `uv venv --python "C:/Users/admin/AppData/Local/Programs/Python/Python311/python.exe" .venv` |
| 装依赖 | `uv pip install --python .venv/Scripts/python.exe --index-url https://pypi.tuna.tsinghua.edu.cn/simple -e ".[dev]"` |
| 全量测试 | `.venv/Scripts/python.exe -m pytest tests/ -v` |
| 程序自检 | `.venv/Scripts/python.exe -m pc_quote_flow --selftest` |
| 数学核对 | `.venv/Scripts/python.exe scripts/verify_math.py` |
| 打包 | `.venv/Scripts/python.exe packaging/build.py` |
| 推送 | `git push origin main`（SSH 自动重写） |
