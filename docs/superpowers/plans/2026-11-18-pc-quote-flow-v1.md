# pc-quote-flow v1 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现设计文档 v4 定义的装机报价流转工具 v1：增值税底价/利润率报价计算、三种隔离导出、管理层审阅、操作人留痕、采购回写，打包 Windows 单文件 exe。

**Architecture:** 纯 Python 分层：计算核心（money/tax/pricing，Decimal 精确）→ 数据模型与状态（model/states）→ xlsx 持久化（store，原子保存+哈希+只增日志）→ 身份（identity）→ 导出与审阅（exports/review）→ PySide6 界面（ui/，三视图纯 UI 切换无权限）。数据载体为程序自有格式 xlsx，打开即重算派生列。

**Tech Stack:** Python 3.11 / PySide6 / openpyxl / pytest + pytest-qt / PyInstaller / uv

**Spec:** `docs/superpowers/specs/2026-11-18-pc-quote-flow-design.md`（v5；**附录B 数学计算逻辑规范为唯一计算口径**，执行者必须同时阅读）

## Global Constraints

- Python 3.11（本机 `C:/Users/admin/AppData/Local/Programs/Python/Python311/python.exe`）；venv 用 uv 创建；依赖走清华镜像 `https://pypi.tuna.tsinghua.edu.cn/simple`。
- 依赖：openpyxl>=3.1、PySide6>=6.8；dev：pytest>=8、pytest-qt>=4.4、pyinstaller>=6。
- 金额一律 `Decimal`，`ROUND_HALF_UP` 舍入到分（0.01）；中间量全精度；**整机报价 = 舍入后件报价之和**；底价显示到分；件报价由**全精度**件底价计算（非显示舍入值）。**规范附录B（数学计算逻辑规范）为唯一数学口径**，含期望值总表 B.7。
- 税务（一般纳税人 13%）：专票（含京东专票，输入时归一化为"专票"）件底价贡献 = 含税单价×数量；普票 = 含税单价×数量×1.13；B = S + P×1.13；C = S/1.13 + P；底价应缴增值税 = P×0.13。
- 加成模式 Q = B×(1+r)；毛利率模式 Q = B÷(1−m)；加成率 = (Q−B)/B；毛利率 = (Q−B)/Q；利润额(不含税) = (Q−B)/1.13。百分比显示保留 2 位小数。
- 含税成本列 = 单价；一切按 单价×数量 行总价计算。
- **无权限门禁**：低于底价 → 红色警告 + 导出前一次确认 + 日志，绝不阻止操作；审批状态不做门禁；视图任意切换。
- 三种导出严格隔离：客户报价单不含成本/供应商/链接/确认价/实际价/订单号（含隐藏列、批注、文档属性）；审批文件含全部内部字段+审批摘要；采购单不含客户报价/利润/底价。
- 日志只增不改；盖章字段 = 时间+操作人(姓名+角色)+机器名+Windows账户+视图+动作+变更摘要+文件版本。
- **真实数据永不入库**：测试与样例只用附录A虚构配置A/B；`data/`、`exports/`、`*_客户_*.xlsx`、`*_审批_*.xlsx` 已 gitignore。
- 保存原子化：临时文件 + os.replace，上一版留 `.bak`；内容哈希检测程序外改动。
- UI 文案、README、注释、提交说明用中文；提交信息用 feat/fix/test/chore 前缀；每任务至少一次提交。
- 测试命令统一：仓库根目录下 `.venv/Scripts/python.exe -m pytest tests/... -v`；GUI 测试 `QT_QPA_PLATFORM=offscreen`（conftest 设置）。
- **每任务完成门禁（用户要求，规范 §14）**：每个任务的"提交"步骤前必须先跑——① 全量回归 `pytest tests/ -v` 全绿；② `python -m pc_quote_flow --selftest`（Task 8 起）；③ 独立数学交叉核对 `.venv/Scripts/python.exe scripts/verify_math.py` 全 PASS（Task 3 起；脚本不导入程序计算函数，按附录B.7 独立 Decimal 重算比对程序输出）；④ 任何失败先排障修复再重跑全部门禁，全绿才提交，门禁结果记入提交说明（如"门禁: 42 passed, selftest OK, 数学核对 12/12"）。下文各任务不再逐一重复。

## Review Focus

1. 普票行 数量>1 且单价带小数（99.99×3）→ 底价/报价按行总价算、舍入不漂移（Task 3 测试钉死：floor 338.97 / quote **372.86**——件报价用全精度底价 338.9661 计算，不是显示值 338.97，见规范附录B.6 例7）。
2. 文件被 Excel 手改（改成本/删列/删表）后打开 → 派生列重算+外部改动警告留痕；缺表缺列友好报错不崩溃不丢数据（Task 4）。
3. 低于底价导出客户报价单 → 警告+一次确认+日志但可导出；导出文件任何角落（隐藏列/批注/属性）无内部字段（Task 6）。
4. 同一文件先后被两人保存（旧覆新）→ 版本号递增、日志可查、`.bak` 可恢复（Task 4）。
5. 反算写回时存在单项利润率覆盖 → 覆盖清除、统一率反解、尾差由最大底价件吸收使合计精确等于目标价、写日志（Task 3：4555.55 → CPU 件 1246.44）。

## 文件结构

```
pc-quote-flow/
├── pyproject.toml                  # 元数据+依赖+pytest 配置（src 布局，editable 安装）
├── src/pc_quote_flow/
│   ├── __init__.py / __main__.py   # 包入口；python -m pc_quote_flow [--selftest]
│   ├── money.py                    # fen() 舍入到分、pct2() 百分比显示
│   ├── tax.py                      # TaxProfile、发票归一化、件底价贡献、不含税成本
│   ├── model.py                    # QuoteLine/QuoteDoc/ApprovalRecord/LogEntry 数据类
│   ├── states.py                   # 状态图与流转记录（记录不拦截）
│   ├── pricing.py                  # 件/整机报价、四数、反算写回、实际利润重算
│   ├── store.py                    # xlsx 读写、原子保存、备份、哈希、版本、日志
│   ├── identity.py                 # profile.json、Windows 锚点、盖章、切换操作人
│   ├── exports.py                  # 三种导出+隔离+溯源+状态联动
│   ├── review.py                   # 审批摘要、审批结论写回
│   └── ui/                         # app.py 主窗口/selftest；sales_view/purchase_view/review_view；dialogs.py；table_model.py
├── tests/                          # conftest.py（虚构夹具）+ 每模块一个测试文件 + test_ui.py
├── scripts/verify_math.py          # 独立数学交叉核对（不导入程序计算函数，重算规范附录B.7 比对程序输出，可生成验证报告）
├── samples/                        # make_samples.py + 虚构配置A/B.xlsx + README（虚构声明）
├── packaging/                      # pc-quote-flow.spec + build.py
└── docs/                           # superpowers/specs|plans + uat-checklist.md
```

---

### Task 1: 脚手架 + money/tax + 虚构夹具

**Files:**
- Create: `pyproject.toml`, `src/pc_quote_flow/__init__.py`, `src/pc_quote_flow/money.py`, `src/pc_quote_flow/tax.py`, `tests/conftest.py`, `tests/test_tax.py`

**Interfaces:**
- Produces:
  - `money.fen(x: Decimal) -> Decimal`（ROUND_HALF_UP 到 0.01）；`money.pct2(x: Decimal) -> Decimal`（= fen(x*100)，百分比显示）
  - `tax.TaxProfile(rate: Decimal = Decimal("0.13"))`（dataclass；v1 仅一般纳税人，预留字段）
  - `tax.normalize_invoice(s: str) -> str`（"京东专票"/"专票"→"专票"；"普票"/"普通发票"→"普票"；其余 ValueError）
  - `tax.floor_contrib(unit_price: Decimal, qty: int, invoice: str, p: TaxProfile) -> Decimal`（全精度：专票 price×qty；普票 price×qty×(1+rate)）
  - `tax.cost_excl(unit_price: Decimal, qty: int, invoice: str, p: TaxProfile) -> Decimal`（专票 price×qty/(1+rate)；普票 price×qty）
  - conftest 夹具 `cfg_a_lines() / cfg_b_lines() -> list[dict]`，键：name, model, qty, price(str), invoice；值 = 附录A 两表全部 9 行（A：CPU盒装2000/主板1000/内存32G套条800京东专票/固态500G600京东专票/机械2TB900/电源650W300/散热双塔100/机箱80/风扇120mm20，全专票；B：CPU散片1000普票/主板1000/内存16G400京东专票/固态500G600/机械1TB500京东专票/电源650W300/散热双塔100/机箱80/风扇120mm20，其余专票）

- [ ] **Step 1: 建 venv 与 pyproject**

```bash
cd C:/Users/admin/Desktop/pc-quote-flow
uv venv --python "C:/Users/admin/AppData/Local/Programs/Python/Python311/python.exe" .venv
```

pyproject.toml：`[project] name="pc-quote-flow" version="0.1.0" requires-python=">=3.11" dependencies=["openpyxl>=3.1","PySide6>=6.8"]`；`[project.optional-dependencies] dev=["pytest>=8","pytest-qt>=4.4","pyinstaller>=6"]`；`[build-system] setuptools`；`[tool.setuptools.packages.find] where=["src"]`；`[tool.pytest.ini_options] testpaths=["tests"]`。然后：

```bash
uv pip install --python .venv/Scripts/python.exe --index-url https://pypi.tuna.tsinghua.edu.cn/simple -e ".[dev]"
```

- [ ] **Step 2: 写失败测试** `tests/test_tax.py`

```python
from decimal import Decimal as D
from pc_quote_flow import tax, money

def test_appendix_a_totals(cfg_a_lines):
    p = tax.TaxProfile()
    floors = [tax.floor_contrib(D(l["price"]), l["qty"], tax.normalize_invoice(l["invoice"]), p) for l in cfg_a_lines]
    assert money.fen(sum(floors)) == D("5800.00")
    assert money.fen(sum(tax.cost_excl(D(l["price"]), l["qty"], tax.normalize_invoice(l["invoice"]), p) for l in cfg_a_lines)) == D("5132.74")

def test_appendix_b_totals(cfg_b_lines):
    # 同法：B == 4130.00，C == 3654.87，P×0.13 == 130.00
    ...

def test_normalize_jd_special():
    assert tax.normalize_invoice("京东专票") == "专票"

def test_fen_rounding():
    assert money.fen(D("338.9661")) == D("338.97")
```

（test_appendix_b_totals 按 A 的模式写全断言：4130.00 / 3654.87 / 130.00。）

- [ ] **Step 3: 运行确认失败**：`.venv/Scripts/python.exe -m pytest tests/test_tax.py -v` → FAIL（模块不存在）
- [ ] **Step 4: 实现 money.py / tax.py**（签名见 Interfaces；算法即 Global Constraints 公式）
- [ ] **Step 5: 运行确认通过**：同上 → PASS（4 项）
- [ ] **Step 6: 提交**：`git add pyproject.toml src tests && git commit -m "feat: 脚手架与税务计算核心（附录A虚构夹具）"`

### Task 2: 数据模型 + 状态记录

**Files:**
- Create: `src/pc_quote_flow/model.py`, `src/pc_quote_flow/states.py`, `tests/test_states.py`

**Interfaces:**
- Consumes: 无（纯数据类）
- Produces:
  - `model.QuoteLine`（dataclass）：name:str, model:str="", qty:int=1, unit_price:Decimal=D(0), invoice:str="专票", supplier:str="", platform:str="", link:str="", confirmed:bool=False, confirm_price:Decimal|None=None, confirm_invoice:str|None=None, item_rate:Decimal|None=None, quote_adjust:Decimal=D(0), actual_price:Decimal|None=None, actual_invoice:str|None=None, purchase_date:str="", order_no:str="", note:str=""
  - `model.QuoteDoc`：config_name:str, customer:str="", quote_date:str="", valid_until:str="", status:str="询价", version:int=0, creator:str="", modifier:str="", modify_time:str="", mode:str="markup"（"markup"|"margin"）, unified_rate:Decimal=D(0), lines:list[QuoteLine], approvals:list[ApprovalRecord], logs:list[LogEntry], approval_status:str="未提交", approver:str="", approval_time:str="", approval_opinion:str="", last_export_by:str="", last_export_time:str="", last_export_type:str="", content_hash:str="", note:str=""
  - `model.ApprovalRecord`：round:int, time:str, approver:str, role:str, machine:str, win_account:str, conclusion:str, opinion:str
  - `model.LogEntry`：time:str, operator:str, role:str, machine:str, win_account:str, view:str, action:str, summary:str, version:int
  - `states.STATES = ["询价","已报价","客户已确认","待审批","采购中","已完成","已废弃"]`
  - `states.TRANSITIONS: dict[str, set[str]]` = {询价:{已报价,已废弃}, 已报价:{客户已确认,询价,已废弃}, 客户已确认:{待审批,已报价,已废弃}, 待审批:{采购中,已报价,已废弃}, 采购中:{已完成,待审批,已废弃}, 已完成:{已废弃}, 已废弃:set()}
  - `states.can_transition(frm: str, to: str) -> bool`
  - `states.transition(doc: QuoteDoc, to: str, stamp: LogEntry) -> None`：置 doc.status；**非常规流转不拦截**，stamp.action 前缀"非常规流转"；logs.append(stamp)

- [ ] **Step 1: 写失败测试** `tests/test_states.py`：test_valid_path（询价→已报价→客户已确认→待审批→采购中→已完成 每步 can_transition True 且 logs 递增）；test_reject_back（待审批→已报价 True）；test_irregular_not_blocked（询价→已完成：can_transition False，transition 仍生效且日志 action 含"非常规流转"）；test_discard_anywhere（除已废弃外任意状态→已废弃 True）；test_log_append_only（transition 前后 logs[:n] 不变）
- [ ] **Step 2: 运行确认失败** → FAIL
- [ ] **Step 3: 实现 model.py / states.py**（dataclass 字段顺序即 Interfaces；默认值用 field(default_factory=list)）
- [ ] **Step 4: 运行确认通过** → PASS（5 项）
- [ ] **Step 5: 提交**：`git commit -m "feat: 数据模型与状态记录（记录不拦截）"`

### Task 3: pricing 报价计算（四数/单项/反算写回/实际利润）

**Files:**
- Create: `src/pc_quote_flow/pricing.py`, `tests/test_pricing.py`

**Interfaces:**
- Consumes: `money.fen/pct2`、`tax.floor_contrib/cost_excl/TaxProfile`、`model.QuoteLine/QuoteDoc`
- Produces:
  - `pricing.line_quote(floor: Decimal, rate: Decimal, mode: str) -> Decimal` = fen(floor×(1+rate))（markup）或 fen(floor÷(1−rate))（margin）
  - `pricing.DocPricing`（dataclass）：line_floors:list[Decimal], line_quotes:list[Decimal], floor:Decimal, quote:Decimal, profit_excl:Decimal, markup:Decimal, margin:Decimal（floor=fen(Σ全精度件底价)；quote=Σline_quotes；profit_excl=fen((quote−floor)/1.13)；markup/margin 全精度）
  - `pricing.price_doc(lines: list[QuoteLine], mode: str, unified_rate: Decimal, p: TaxProfile) -> DocPricing`：件率 = item_rate if not None else unified_rate；line_quotes[i] = line_quote(全精度件底价, 件率, mode) + quote_adjust[i]
  - `pricing.reverse_rate(quote: Decimal, floor: Decimal, mode: str) -> Decimal`：markup → quote/floor−1；margin → 1−floor/quote（全精度）
  - `pricing.apply_reverse(doc: QuoteDoc, target: Decimal, mode: str, p: TaxProfile) -> str`：doc.unified_rate = reverse_rate(target, 当前整机底价, mode)；doc.mode = mode；清除全部 item_rate=None、quote_adjust=0；重算后尾差 drift = target − Σ件报价 加到**底价最大件**的 quote_adjust；返回日志摘要（含"反算写回"与"尾差调整"字样及 drift 值）
  - `pricing.ActualsResult`（dataclass）：cost_excl:Decimal, floor:Decimal, real_profit:Decimal, expected_profit:Decimal, eroded:bool, negative:bool
  - `pricing.actuals(doc: QuoteDoc, p: TaxProfile) -> ActualsResult`：每件有效价 = actual_price or confirm_price or unit_price（发票同链 fallback）；C'=Σcost_excl、floor'=Σfloor_contrib（fen）；real_profit = fen(doc当前整机报价/1.13 − C'全精度)；expected_profit = 报价时口径 fen((quote−floor)/1.13)（quote/floor 取 price_doc 用 unit_price 口径）；eroded = real<expected；negative = real<0

- [ ] **Step 1: 写失败测试** `tests/test_pricing.py`（夹具 dict → QuoteLine 的辅助函数放本文件顶部）

```python
def test_appendix_b_markup10(cfg_b_lines):
    dp = pricing.price_doc(lines(cfg_b_lines), "markup", D("0.10"), tax.TaxProfile())
    assert dp.floor == D("4130.00") and dp.quote == D("4543.00")
    assert dp.profit_excl == D("365.49") and money.pct2(dp.margin) == D("9.09")

def test_appendix_b_margin10(cfg_b_lines):
    # quote 4588.89 / profit 406.10 / pct2(margin) 10.00
    ...

def test_appendix_a_both_modes(cfg_a_lines):
    # markup10: 6380.00 / 513.27 / 9.09；margin10: 6444.44 / 570.30 / 10.00
    ...

def test_item_override(cfg_b_lines):
    ls = lines(cfg_b_lines); ls[0].item_rate = D("0")
    dp = pricing.price_doc(ls, "markup", D("0.12"), tax.TaxProfile())
    assert dp.line_quotes == [D(x) for x in ["1130.00","1120.00","448.00","672.00","560.00","336.00","112.00","89.60","22.40"]]
    assert dp.quote == D("4490.00") and dp.profit_excl == D("318.58") and money.pct2(dp.markup) == D("8.72")

def test_rounding_99_99_qty3():
    ln = model.QuoteLine(name="测试件", qty=3, unit_price=D("99.99"), invoice="普票")
    dp = pricing.price_doc([ln], "markup", D("0.10"), tax.TaxProfile())
    assert dp.line_floors == [D("338.97")] and dp.line_quotes == [D("372.86")]  # Review Focus 1：全精度 338.9661×1.1=372.86271→372.86

def test_apply_reverse_absorbs_drift(cfg_b_lines):
    doc = model.QuoteDoc(config_name="B", lines=lines(cfg_b_lines), mode="markup", unified_rate=D("0.10"))
    doc.lines[0].item_rate = D("0")
    summary = pricing.apply_reverse(doc, D("4555.55"), "markup", tax.TaxProfile())
    dp = pricing.price_doc(doc.lines, doc.mode, doc.unified_rate, tax.TaxProfile())
    assert dp.quote == D("4555.55") and dp.line_quotes[0] == D("1246.44")
    assert all(l.item_rate is None for l in doc.lines)
    assert "反算写回" in summary and "尾差" in summary  # Review Focus 5

def test_actuals_erosion(cfg_b_lines):
    doc = model.QuoteDoc(config_name="B", lines=lines(cfg_b_lines), mode="markup", unified_rate=D("0.10"))
    doc.lines[0].actual_price = D("1050"); doc.lines[0].actual_invoice = "普票"
    a = pricing.actuals(doc, tax.TaxProfile())
    assert a.cost_excl == D("3704.87") and a.floor == D("4186.50")
    assert a.real_profit == D("315.49") and a.expected_profit == D("365.49")
    assert a.eroded and not a.negative

def test_actuals_negative(cfg_b_lines):
    # actual_price 2000 普票 → real_profit −634.51，negative True
    ...
```

（省略号处按注释断言写全；reverse_rate 另测：markup reverse_rate(4543,4130)==D(370)/D(4130) 全精度相等。）

- [ ] **Step 2: 运行确认失败** → FAIL
- [ ] **Step 3: 实现 pricing.py**（公式见 Global Constraints 与 Interfaces；apply_reverse 的尾差吸收规则：drift 加到底价最大件，其余 quote_adjust=0）；同时创建 `scripts/verify_math.py` 初版：**不导入 pc_quote_flow.pricing/tax**，用 Decimal 按规范附录B.7 独立重算并调用程序输出逐项比对（本任务覆盖底价/四数/单项覆盖/反算写回/实际利润/数量舍入用例），打印逐项 PASS/FAIL 与汇总，失败退出码 1
- [ ] **Step 4: 运行确认通过** → PASS（9 项）
- [ ] **Step 5: 门禁+提交**：全量 pytest 与 `scripts/verify_math.py` 全绿后 `git commit -m "feat: 报价计算——四数/单项/反算写回/实际利润重算（门禁: N passed, 数学核对 M/M）"`

### Task 4: store xlsx 持久化 + 虚构样例文件

**Files:**
- Create: `src/pc_quote_flow/store.py`, `tests/test_store.py`, `samples/make_samples.py`, `samples/README.md`
- Generated: `samples/虚构配置A.xlsx`, `samples/虚构配置B.xlsx`

**Interfaces:**
- Consumes: model、pricing.price_doc、money.fen
- Produces:
  - `store.SHEETS = ["报价总览","部件明细","审批记录","修改日志"]`
  - `store.OVERVIEW_COLS = ["配置名","客户名","报价日期","有效期至","状态","版本号","创建人","修改人","修改时间","算法模式","统一利润率","整机底价","整机报价","利润额(不含税)","加成率","毛利率","审批状态","审批人","审批时间","审批意见","最近导出人","导出时间","导出类型","内容哈希","备注"]`
  - `store.LINE_COLS = ["部件名","型号","数量","含税成本单价","发票类型","供应商","平台","商品链接","价格已确认","确认价","确认发票类型","单项利润率","报价尾差调整","件底价","件报价","实际成交价","实际发票类型","采购日期","订单号","备注"]`
  - `store.APPROVAL_COLS = ["轮次","时间","审批人","角色","机器名","Windows账户","结论","意见"]`；`store.LOG_COLS = ["时间","操作人","角色","机器名","Windows账户","视图","动作","变更摘要","文件版本"]`
  - 派生列（load 时重算，save 时写入）：总览 整机底价/整机报价/利润额(不含税)/加成率/毛利率；明细 件底价/件报价
  - `store.HASH_OVERVIEW_FIELDS = ["配置名","客户名","报价日期","有效期至","状态","算法模式","统一利润率","审批状态","审批人","审批时间","审批意见","备注"]`；`store.HASH_LINE_FIELDS` = LINE_COLS 去掉 ["件底价","件报价"]
  - `store.content_hash(doc) -> str`：sha256( json.dumps([总览哈希字段值], [明细各行哈希字段值], [审批记录]), ensure_ascii=False, sort_keys=True, default=str )
  - `store.save(doc: QuoteDoc, path: Path, stamp: LogEntry) -> None`：logs.append(stamp)；version+=1；modifier/modify_time 取自 stamp；重算派生列与哈希；写 `path.with_suffix(".tmp")` → 旧文件 os.replace 为 `.bak` → tmp os.replace 为 path
  - `store.load(path: Path) -> tuple[QuoteDoc, list[str]]`：缺表/缺列 → `store.StoreError`（中文消息指明缺哪个表/列）；读入后重算派生列；哈希不一致 → warnings 追加"文件曾在程序外被修改"
  - `store.StoreError(Exception)`

- [ ] **Step 1: 写失败测试** `tests/test_store.py`：test_roundtrip_a（save→load 后全部输入字段与夹具一致，派生列=5800.00 等）；test_roundtrip_b（4130.00/4543.00/365.49）；test_external_edit_warning（save 后用 openpyxl 直接改明细成本单元格→load：warnings 含"程序外被修改"，派生列按新成本重算）（Review Focus 2）；test_missing_sheet_error（删"部件明细"表→StoreError 消息含"部件明细"）；test_missing_column_error（删"发票类型"列→StoreError）；test_backup_and_version（连续 save 两次→.bak 存在、version==2、logs 只增）（Review Focus 4）；test_hash_stable_over_logs（仅追加日志再 save→load 无外部改动警告）
- [ ] **Step 2: 运行确认失败** → FAIL
- [ ] **Step 3: 实现 store.py**（openpyxl；表头第 1 行、数据第 2 行起；Decimal 以 str 写单元格、读回 Decimal；空值 None↔""/0 按字段类型映射；日期时间 ISO 字符串）
- [ ] **Step 4: 运行确认通过** → PASS（7 项）
- [ ] **Step 5: 生成虚构样例**：samples/make_samples.py 用夹具构造 QuoteDoc（config_name="虚构配置A"/"虚构配置B"，customer="示例客户"，creator="虚构操作员"，mode="markup"，unified_rate=0.10，valid_until="2026-12-31"），store.save 到 samples/；运行 `.venv/Scripts/python.exe samples/make_samples.py`；samples/README.md 声明"全部虚构数字，结构与真实业务一致，真实数据永不入库"
- [ ] **Step 6: 提交**：`git add src tests samples && git commit -m "feat: xlsx持久化（原子保存/备份/哈希/版本）与虚构样例"`

### Task 5: identity 操作人身份

**Files:**
- Create: `src/pc_quote_flow/identity.py`, `tests/test_identity.py`

**Interfaces:**
- Consumes: model.LogEntry
- Produces:
  - `identity.Profile`（dataclass）：name:str, role:str（"采购"|"销售客服"|"管理层"）, machine:str, win_account:str
  - `identity.ROLES = ["采购","销售客服","管理层"]`
  - `identity.windows_account() -> str`（getpass.getuser()）；`identity.machine_name() -> str`（os.environ.get("COMPUTERNAME", socket.gethostname())）
  - `identity.profile_dir(base: Path|None=None) -> Path`：默认 `Path(os.environ["APPDATA"])/"pc-quote-flow"`
  - `identity.load_profile(base: Path|None=None) -> Profile|None`（读 profile.json，不存在/损坏→None）
  - `identity.save_profile(p: Profile, base: Path|None=None) -> None`
  - `identity.make_stamp(p: Profile, view: str, action: str, summary: str, version: int, now: datetime|None=None) -> LogEntry`（time=now.isoformat(timespec="seconds")，默认当前时间）
  - `identity.switch_operator(doc: QuoteDoc, new_p: Profile, view: str) -> LogEntry`：生成 action="切换操作人"、summary="旧姓名(旧角色)→新姓名(新角色)" 的 stamp 并 append 到 doc.logs，返回 stamp

- [ ] **Step 1: 写失败测试** `tests/test_identity.py`：test_profile_roundtrip（tmp_path 作 base，save→load 相等）；test_load_missing_returns_none；test_stamp_fields（make_stamp 后 9 字段齐全，operator==name、role/machine/win_account 来自 Profile）；test_switch_logged（switch_operator 后 logs 长度+1，action=="切换操作人"，summary 含新旧姓名）；test_default_dir_uses_appdata（monkeypatch APPDATA→tmp，profile_dir 在其下）；test_invalid_role_rejected（save_profile role="黑客"→ValueError）
- [ ] **Step 2: 运行确认失败** → FAIL
- [ ] **Step 3: 实现 identity.py**
- [ ] **Step 4: 运行确认通过** → PASS（6 项）
- [ ] **Step 5: 提交**：`git commit -m "feat: 操作人身份登记与盖章（Windows账户锚点）"`

### Task 6: exports 三种导出

**Files:**
- Create: `src/pc_quote_flow/exports.py`, `tests/test_exports.py`

**Interfaces:**
- Consumes: store（SCHEMA/save）、model、pricing.price_doc、states.transition、identity.make_stamp、review.summary

> **执行顺序说明：** 依赖上 exports 需要 review.summary，故实际执行顺序为 Task 1→2→3→4→5→**7(review)→6(exports)**→8→9→10。两任务编号保留不变， Interfaces 互相引用以本文件为准。

- Produces:
  - `exports.NeedsConfirmation(Exception)`
  - `exports.export_customer(doc, path: Path, stamp: LogEntry, confirmed: bool=False, round_to_yuan: bool=False) -> None`：若 price_doc 报价<底价 且 not confirmed → raise NeedsConfirmation（UI 弹一次确认后 confirmed=True 重试，**绝不永久阻止**）；生成单 sheet「客户报价单」：信息行（配置名/客户名/报价日期/有效期至/整机报价/导出人/导出时间/来源版本）+ 明细表（部件名/型号/数量/件报价）；round_to_yuan=True 时整机报价 ROUND_HALF_UP 到元且**省略明细表**；states.transition(doc,"已报价",stamp)；doc.last_export_by/time/type="客户报价单"；源文件 logs 追加导出记录（低于底价时 summary 含"低于底价确认导出"）
  - `exports.export_approval(doc, path, stamp) -> None`：完整复制 store 四表 + 追加 sheet「审批摘要」（review.summary 各字段一行一项）；transition→"待审批"；last_export_type="审批文件"；导出文件总览带导出人/时间/来源版本
  - `exports.export_purchase(doc, path, stamp) -> None`：单 sheet「采购单」：信息行（配置名/客户名/审批状态/导出人/导出时间/来源版本）+ 明细（部件名/型号/数量/含税成本单价/确认价/发票类型(确认优先)/供应商/平台/商品链接/订单号(留空)/实际成交价(留空)/备注）；**不含客户报价/利润/底价列**；不改状态；last_export_type="采购单"
  - 三种导出文件均不含「修改日志」以外泄密路径：客户报价单/采购单为单 sheet；审批文件含日志（内部文件，允许）

- [ ] **Step 1: 写失败测试** `tests/test_exports.py`（各测试先给夹具 doc 的 CPU 行设置 supplier="虚构供应商"、link="https://example.com/item"，供隔离断言用）：test_customer_isolation_scan（配置B markup10 导出→遍历导出文件**所有 sheet 所有单元格**+列隐藏属性+单元格批注+core properties，断言不含供应商名"虚构供应商"、链接"https://example.com/item"、成本值"1000.00"等内部 token；sheet 名集合=={"客户报价单"}）（Review Focus 3）；test_below_floor_confirm_flow（unified_rate=−0.05→export_customer raise NeedsConfirmation；confirmed=True→成功且源 doc.logs 含"低于底价确认导出"，状态仍变已报价）；test_approval_full_fields（导出含四表+审批摘要，LINE_COLS 全在，摘要含 4130.00/4543.00/365.49/130.00）；test_purchase_no_quote_cols（采购单表头不含"整机报价"/"利润"/"底价"字样，含链接与订单号列）；test_status_and_provenance（customer→已报价、approval→待审批；doc.last_export_by==stamp.operator；导出文件信息行含来源版本）；test_round_to_yuan（apply_reverse 到 4555.55 后 round_to_yuan 导出→整机报价 4556，无明细表）
- [ ] **Step 2: 运行确认失败** → FAIL
- [ ] **Step 3: 实现 exports.py**（openpyxl 新建 Workbook；客户报价单信息行用两列键值；导出文件不写公式只写值）
- [ ] **Step 4: 运行确认通过** → PASS（6 项）
- [ ] **Step 5: 提交**：`git commit -m "feat: 三种导出严格隔离+低于底价确认+导出溯源"`

### Task 7: review 审批摘要与结论写回

**Files:**
- Create: `src/pc_quote_flow/review.py`, `tests/test_review.py`

**Interfaces:**
- Consumes: pricing.price_doc/actuals、tax、model、states.transition
- Produces:
  - `review.Summary`（dataclass）：floor, quote, profit_excl, markup, margin（Decimal，率全精度）, ordinary_count:int, ordinary_tax_impact:Decimal, max_rate_line:tuple[str,Decimal], min_rate_line:tuple[str,Decimal], below_floor:bool, expired:bool, valid_until:str, version:int
  - `review.summary(doc, p: TaxProfile, today: date|None=None) -> Summary`：件有效加成率 = 件报价/件底价−1；max/min 取首个极值件（name, 率）；ordinary_tax_impact = fen(P×0.13)；expired = today > valid_until（today 默认 date.today()，valid_until 空→False）
  - `review.record_approval(doc, conclusion: str, opinion: str, stamp: LogEntry, p: TaxProfile) -> None`：conclusion ∉ {"同意","驳回","需调整"} → ValueError；approvals.append(ApprovalRecord(round=len+1, 来自 stamp))；总览审批状态 = 已同意/已驳回/需调整、审批人/时间/意见更新；同意→transition "采购中"；驳回/需调整→transition "已报价"；logs.append(stamp)（action="审批记录"）

- [ ] **Step 1: 写失败测试** `tests/test_review.py`：test_summary_b_values（markup10：floor 4130.00/quote 4543.00/profit 365.49/ordinary_count 1/impact 130.00/below_floor False）；test_summary_extremes_with_override（CPU item_rate=0、其余 0.12→min_rate_line==("CPU（散片）",0 全精度)，max 为首个 0.12 件"主板"）；test_expired（valid_until="2026-11-17"，today=date(2026,11,18)→expired True）；test_approval_agree_then_reject（record 同意→status 采购中、approvals[0].round==1；再 record 驳回→status 已报价、round==2；经 store.save/load 往返后仍在）；test_invalid_conclusion（"随便"→ValueError）
- [ ] **Step 2: 运行确认失败** → FAIL
- [ ] **Step 3: 实现 review.py**
- [ ] **Step 4: 运行确认通过** → PASS（5 项）
- [ ] **Step 5: 提交**：`git commit -m "feat: 审批摘要与审批结论写回（多轮记录）"`

### Task 8: UI 外壳 + 销售视图 + 对话框 + selftest

**Files:**
- Create: `src/pc_quote_flow/__main__.py`, `src/pc_quote_flow/ui/__init__.py`, `src/pc_quote_flow/ui/app.py`, `src/pc_quote_flow/ui/table_model.py`, `src/pc_quote_flow/ui/sales_view.py`, `src/pc_quote_flow/ui/dialogs.py`, `tests/test_ui.py`
- Modify: `tests/conftest.py`（追加 `os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")`）

**Interfaces:**
- Consumes: 全部核心模块
- Produces:
  - `python -m pc_quote_flow [--selftest] [file.xlsx]`；`ui.app.main(argv: list[str]|None=None) -> int`
  - `--selftest`：无 GUI 跑附录A/B pricing 断言 + temp 目录 store 往返，成功 print("SELFTEST OK") 返回 0，失败返回 1
  - `ui.app.MainWindow(path: Path|None=None)`：工具栏（当前操作人标签+切换按钮、打开/保存、视图切换 tabs 销售|采购|审阅、三导出按钮）；四数面板（QLabel：底价/客户报价/利润(不含税)/加成率/毛利率，objectName 依次 lbl_floor/lbl_quote/lbl_profit/lbl_markup/lbl_margin）；利润率输入 txt_rate + 模式 combo_mode（"成本加成"|"销售毛利率"）；明细 QTableView（QuoteTableModel）；警告标签 lbl_warning（低于底价红色可见）
  - `ui.table_model.QuoteTableModel(doc, view: str, p)`：QAbstractTableModel；列按视图过滤（销售视图可隐藏供应商/链接，checkbox 控制）；派生列只读；销售视图可编辑：部件名/型号/数量/含税成本单价/发票类型/供应商/平台/商品链接/单项利润率；setData 后触发重算与刷新信号
  - `ui.dialogs.RegisterDialog`（首次运行 load_profile() is None 时弹出：姓名预填 windows_account()、角色 combo 默认"销售客服"）→ save_profile
  - `ui.dialogs.ReverseDialog(doc, p)`：输入目标价→显示反算加成率/毛利率/利润→「写回」按钮调 apply_reverse+刷新+日志
  - `ui.dialogs.SettingsDialog`：操作人姓名/角色、默认算法、有效期天数（税率 v1 固定 13% 只读显示）
  - 导出按钮 wiring：NeedsConfirmation → QMessageBox.question 一次确认 → confirmed=True 重试；低于底价时 lbl_warning 红色常显但**导出按钮永不 disable**
  - 采购/审阅 tab 本任务放占位 QWidget（Task 9 替换）

- [ ] **Step 1: 写失败测试** `tests/test_ui.py`（pytest-qt qtbot；monkeypatch APPDATA→tmp_path）：test_first_run_registration（MainWindow 构造→RegisterDialog 出现，填"测试客服"/销售客服→profile.json 生成）；test_four_numbers_update（打开 samples/虚构配置B.xlsx，txt_rate 设"10"模式成本加成→lbl_quote=="4543.00"、lbl_profit=="365.49"、lbl_markup=="10.00%"、lbl_margin=="9.09%"）；test_below_floor_warning_not_block（rate −5→lbl_warning 可见且红色样式、导出按钮 isEnabled）；test_reverse_writeback（ReverseDialog 目标 4555.55 写回→doc 整机报价 4555.55）；test_selftest_flag（subprocess 跑 `.venv/Scripts/python.exe -m pc_quote_flow --selftest`→returncode 0 且 stdout 含"SELFTEST OK"）
- [ ] **Step 2: 运行确认失败** → FAIL
- [ ] **Step 3: 实现 ui 各文件与 __main__.py**（PySide6；中文文案；四数刷新统一走 refresh_pricing() 调 price_doc；所有写操作经 make_stamp 记日志）
- [ ] **Step 4: 运行确认通过** → PASS（5 项）；再跑全量 `.venv/Scripts/python.exe -m pytest tests/ -v` 全绿
- [ ] **Step 5: 提交**：`git commit -m "feat: 主窗口/销售视图/登记/反算/设置对话框与selftest"`

### Task 9: 采购视图 + 审阅视图

**Files:**
- Create: `src/pc_quote_flow/ui/purchase_view.py`, `src/pc_quote_flow/ui/review_view.py`, `tests/test_ui_views.py`
- Modify: `src/pc_quote_flow/ui/app.py`（替换占位 tab）

**Interfaces:**
- Consumes: QuoteTableModel、pricing.actuals、review.summary/record_approval、identity
- Produces:
  - `ui.purchase_view.PurchaseView(doc, p)`：可编辑列 确认价/确认发票类型/实际成交价/实际发票类型/采购日期/订单号；商品链接列双击 → QDesktopServices.openUrl；双底价标签 lbl_floor_at_quote / lbl_floor_confirmed（确认价口径 floor_contrib，未确认件用成本价）；确认后底价 > 客户报价 → lbl_warning 红字"已低于底价，请按公司流程审批"（不阻止任何操作）；顶部审批状态只读标签；真实利润面板（actuals：real_profit/expected_profit，eroded→提示、negative→红色）
  - `ui.review_view.ReviewView(doc, p)`：全列只读（model flags 去 ItemIsEditable）；审批摘要块（summary 各字段标签）；修改日志 QTableView；「填写审批意见」按钮 → ApprovalDialog（结论 combo 同意|驳回|需调整 + 意见输入）→ record_approval + 刷新；「对照打开」按钮 → QFileDialog 选第二份文件开新 MainWindow
  - `ui.dialogs.ApprovalDialog`

- [ ] **Step 1: 写失败测试** `tests/test_ui_views.py`（测试先给 CPU 行设置 link="https://example.com/item"）：test_purchase_link_opens（monkeypatch QDesktopServices.openUrl 捕获 URL，双击链接单元格→捕获==夹具链接）；test_confirmed_floor_hint（CPU 确认价 2000 普票→lbl_floor_confirmed=="5260.00"，lbl_warning 可见含"请按公司流程审批"，导出按钮仍 enabled）；test_review_readonly（ReviewView 模型 flags 无 ItemIsEditable）；test_approval_dialog_writes（ApprovalDialog 选"同意"填意见→doc.status=="采购中"、approvals 长度 1、logs 含"审批记录"）；test_erosion_hint（CPU 实际价 1050→真实利润标签"315.49"、侵蚀提示可见）
- [ ] **Step 2: 运行确认失败** → FAIL
- [ ] **Step 3: 实现两视图 + ApprovalDialog + app.py 接线**
- [ ] **Step 4: 运行确认通过** → PASS（5 项）+ 全量测试绿
- [ ] **Step 5: 提交**：`git commit -m "feat: 采购视图（核价/回写/侵蚀提示）与审阅视图（摘要/审批/对照）"`

### Task 10: 打包 + 仓库卫生 + UAT 清单

**Files:**
- Create: `packaging/pc-quote-flow.spec`, `packaging/build.py`, `docs/uat-checklist.md`
- Modify: `README.md`（运行方式章节）

**Interfaces:**
- Consumes: `--selftest`（Task 8）
- Produces: `dist/pc-quote-flow.exe`（单文件、windowed）。`--selftest`：源码模式打印 stdout 并给退出码；exe 模式以退出码表达结果（0=通过）并写日志到 `%TEMP%/pc-quote-flow-selftest.log`（Task 8 实现两种输出，exe 验证用退出码）

- [ ] **Step 1: 写 spec 与 build.py**：PyInstaller onefile、name="pc-quote-flow"、windowed、入口 `src/pc_quote_flow/__main__.py`、datas 无（样例不打包）、hiddenimports 按 PySide6/openpyxl 需要；build.py 用 venv python 调 `python -m PyInstaller packaging/pc-quote-flow.spec --distpath dist --workpath build -y`
- [ ] **Step 2: 构建**：`.venv/Scripts/python.exe packaging/build.py`（预计数分钟）→ dist/pc-quote-flow.exe 存在
- [ ] **Step 3: exe 自检**：`dist/pc-quote-flow.exe --selftest; echo $?` → 退出码 0（Review：若 windowed 无 stdout，以退出码为准）
- [ ] **Step 4: 仓库卫生检查**：`git grep -nE "7893|6574\.04|6616\.04|2547|2008|1549|1199|8080|6715|2630|2180|1085|1550" -- .` → **零匹配**（真实价格特征值）；`git ls-files | grep -E "^(data|exports)/"` → 空；samples/ 与 tests/ 只含虚构值
- [ ] **Step 4b: 数学验证报告（人工核算依据）**：扩展 `scripts/verify_math.py` 覆盖附录B.7 全部 12 用例，运行生成 `docs/math-verification-report.md`（独立重算 vs 程序输出逐项对照表+结论）入库，供用户/财务人工核算
- [ ] **Step 5: 写 UAT 清单** `docs/uat-checklist.md`（中文，用户 GUI 验收用）：⓪对照 docs/math-verification-report.md 与规范附录B.7 期望值总表做人工核算（用户/财务）①双击 exe 登记姓名角色 ②打开 samples/虚构配置B.xlsx 核对四数 4543.00/365.49/10.00%/9.09% ③改利润率−5 看红色警告、导出客户报价单弹确认、确认后导出成功 ④用 Excel/WPS 打开导出的客户报价单确认无成本/供应商/链接 ⑤导出审批文件→审阅视图看摘要→填"同意"→状态采购中 ⑥采购视图点链接、填确认价 2000 看"请按公司流程审批"提示、回写实际价 1050 看真实利润 315.49 与侵蚀提示 ⑦查修改日志每步盖章（姓名/角色/机器/Windows账户/视图/版本）⑧保存后 .bak 存在 ⑨反算 4555.55 写回合计精确
- [ ] **Step 6: README 更新运行方式 + 提交**：`git commit -m "chore: PyInstaller打包、UAT清单与仓库卫生检查"`；`git push origin main`
- [ ] **Step 7: 用户 UAT + 人工数学核算**：agent 备好 exe、样例路径与数学验证报告，用户按清单真人验收（GUI 部分）并按附录B.7 人工核算；**两者都通过**后打 tag `v0.1.0` 并 push tag

---

## 验收对照（spec §12 → 任务）

1→T1/T3/T4；2→T3；3→T6/T8；4→T6；5→T6/T7；6→T7/T9；7→T3/T9；8→T4；9→T10；10→T10；11→T4/T5/T6/T8。
