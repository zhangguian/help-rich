# ADR-0001:用 `modules/<domain>` 渐进替换分层目录

- 状态:**Accepted**
- 日期:2026-10-17
- 取代:无(这是第一份 ADR)
- 影响范围:`backend/app/{api,services,repositories}` → `backend/app/modules/<domain>/`

## 背景

当前后端按**技术分层**组织:

```
app/api/           # 38 个 router
app/services/      # 用例编排
app/repositories/  # 数据访问
app/models/        # ORM
app/core/          # 配置 / 日志 / 成本引擎
```

这套结构在项目早期(1.3 万行)是清晰的,但随着阶段 1–5 的功能落地,它开始拖累改动:

### 已经出现的具体症状

1. **找一个功能的全部代码要跨 4 个目录**。
   举例:价格提醒这一个功能横跨
   `api/price_alerts.py` → `services/price_alert/{engine,service,scheduler}.py`
   → `repositories/price_alert_repo.py` → `models/orm.py`。
   而多智能体是 `api/multi_agent.py` + `services/multi_agent/*`。
   功能越多,这个"横跨 4 处"的比例越高。

2. **子系统命名无法自解释**。
   `services/notify/`、`services/paper_trading/`、`services/multi_agent/`
   已经是**按业务命名的子目录**,和 `services/screener_service.py`、
   `services/ta_service.py` 这类**按技术命名的平铺文件**混在同一层。
   前者其实已经是模块化,只是位置不对。

3. **依赖方向靠人记**。
   `api → services → repositories → models` 是靠约定维持的,
   2026-10 才补上 AST 守卫(`tests/test_architecture_boundaries.py`)。
   有了守卫之后才发现,同层 import 在写代码时极容易发生(本次开发中
   `api/accounts.py` 直连 repository、`api/notify.py` 直连 repo
   都是先写错、再被守卫抓出来)。

4. **改一个子系统的测试找不到一起**。
   测试按文件名组织(`test_price_alert_engine.py`、
   `test_scoring_weights.py`),而不是按子系统聚合。

## 决策

**采用 `modules/<domain>/`,渐进迁移,不搞一次性大重构。**

每个业务域自成一个模块,模块内保留分层,模块之间只能通过公开接口交互:

```
app/modules/<domain>/
├── api.py            # FastAPI router(该域的全部端点)
├── service.py        # 用例编排
├── repository.py     # 数据访问
├── schemas.py        # Pydantic 出入参
├── models.py         # ORM(可选;跨域共享的表仍留在 app/models/orm.py)
└── tests/            # 该域的测试
```

## 约束

1. **一个模块只能有一个 router**,注册在 `app/main.py`,不允许跨域 import 对方的 `api.py`。
2. **跨域调用只能走对方的 `service.py` 公开函数/类**,禁止 `from modules.x import repository`。
3. **共享表留在 `app/models/orm.py`**。`klines`、`positions`、`transactions` 等
   被多个域使用,强行拆分收益小于风险。
4. **迁移以域为单位**,一个域迁完、测试绿了再迁下一个。
5. **迁移期双写禁止**。不允许同时存在 `app/api/price_alerts.py`
   和 `modules/price_alert/api.py` 两份路由。

## 迁移顺序

按「依赖深度 × 改动风险」排序,**从叶子往根迁**:

| 批次 | 域 | 理由 |
| --- | --- | --- |
| 1 | `screener` | 依赖少(行情/评分),被依赖也少,适合打样 |
| 1 | `portfolio` | 持仓+流水,阶段5 已加 account_id,是当前最热的域 |
| 1 | `market` | 行情/K线/市场概览,底层但边界清晰 |
| 2 | `alert`、`notify` | 阶段 1 新增,代码新、改动小 |
| 2 | `paper_trading` | 阶段 3 新增,与 portfolio 有意隔离,边界清楚 |
| 3 | `analysis`(含 `multi_agent`、`workflow_agent`) | 阶段 4 新增,复杂度最高,放最后 |

## 迁移状态

| 批次 | 域 | 状态 | 落地内容 |
| --- | --- | --- | --- |
| 1 | `screener` | ✅ 已迁移 | `api.py` `service.py` `repository.py` `llm_prompt.py` `scoring.py` `weight_service.py` `weight_repository.py`(原 `scoring_weights.py`) |
| 1 | `portfolio` | ✅ 已迁移 | `api_positions.py` `api_transactions.py` `service.py` `repository.py` `account_service.py` `account_repository.py` |
| 2 | `alert` | ✅ 已迁移 | `api.py` `engine.py` `service.py` `scheduler.py` `repository.py` |
| 2 | `notify` | ✅ 已迁移 | `api.py` `base.py` `channels.py` `config_service.py` `config_repository.py` `dedupe.py` `service.py` |
| 2 | `paper_trading` | ✅ 已迁移 | `api.py` `service.py` `scheduler.py` `repository.py` |
| 3 | `analysis`(含 `multi_agent`、`workflow_agent`) | ✅ 已迁移 | `api.py`(深度分析)`workflow_api.py`(盘前简报)`contracts.py` `prompts.py` `service.py`(多智能体)`workflow.py` `workflow_scheduler.py` |
| 3 | `market` | ⏳ 待迁 | **未做**。`quote_service` / `sector_fund_flow_service` 被 22 个文件引用,单次改动面过大 |

> **首批落地的实际范围是 screener + portfolio 两个域,批次 2 补齐 alert / notify / paper_trading,
> 批次 3 合域 analysis。** 已迁 6 个域,`app/api/` 从 27 个文件降到 23 个,`app/services/` 只剩扁平工具服务 + `backtest/`。
> market 域至今未迁:`quote_service` 是全项目最被依赖的服务(22 个引用点),
> 把它和 API 一起搬动会把「机械重构」变成「高风险重构」。
> 按本 ADR「一个域迁完、测试绿了再迁下一个」的约束,宁可少迁一个,也不留下半绿状态。

### 批次 2 的收获:守卫抓到一个真实的跨域违规

迁移 `alert` 时,原本 `modules/alert/service.py` 直接 import 了
`app.modules.notify.base`(DTO)和 `app.modules.notify.config_repository`(仓储),
被 `test_modules_do_not_import_other_domains_internals` 当场拦下。

修复方式不是放宽守卫,而是**把职责收回 notify 自己**:

- `NotifyService.notify()` 的 `configs` 参数改为 `None` 语义 = "本服务自行解密取配置"
  (新增私有 `_load_configs()`,读失败按未配置处理而非抛错)。
  alert 只传 `configs=None`,不再知道 notify 的配置存在哪。
- 新增 `NotifyService.enabled_channels()` 与 `send_to_enabled(message)`,
  让 workflow 也只需一次调用就能"推给用户启用的所有渠道"。
- `modules/notify/service.py` 末尾再导出 `NotifyMessage` / `NotifyLevel` / `NotifyResult` 等 DTO,
  让 `service` 成为该域**唯一**的跨域入口。

这正是 ADR 里"跨域只能走 service"想要的效果:边界不是靠自觉,
而是写错就会变红;红了之后答案往往是把逻辑放回它该在的地方。

### 批次 3 的收获:合域会让模块名撞车

`multi_agent/service.py` 和 `workflow_agent/service.py` 合进 `analysis` 后,
后者改名为 `workflow.py`(否则两个 `service.py` 直接冲突)。
连带把测试里的 `from app.modules.analysis import service as svc_mod`
改成 `... import workflow as svc_mod` —— 机械替换 import 路径时,
**被合并的包内的相对位置会变**,必须逐个核对语义而不只是让 import 能跑通。

## 迁移脚本

`backend/_rewrite_imports.py` 是一次性工具,用于批量改写 import 路径。
**注意**:它用 `Path(__file__).resolve().parents[0]` 定位 `backend/`
(不是 `parents[1]`,那会指向仓库根,导致脚本静默扫描不到任何文件而
"零改动 + 无残留"假成功)。迁移下一批前可复用,但需同步更新 `REPLACEMENTS`。

PowerShell 的 `Set-Content -Encoding UTF8` 会写入 **BOM**,导致
`ast.parse` 抛 `SyntaxError: invalid non-printable character U+FEFF`,
`tests/test_architecture_boundaries.py` 会因此全灭。批量改写请用 Python。

## 后果

### 正面

- 改一个功能只在一个目录内,`git log --follow` 能看到完整演进史。
- 模块边界可被守卫直接检查(比现在的"层"更容易判定:同名即越界)。
- 未来若要按域拆服务(选股服务/持仓服务),目录结构已经就位。

### 负面(必须承认)

- **迁移期成本真实存在**。本 ADR 落地本身不改任何运行时行为,
  但首批三个域的移动会产生不小的 diff,需要逐个域验证。
- **`app/models/orm.py` 继续膨胀**。共享表不动是有意为之的取舍,
  代价是 ORM 层会继续变大。这个代价被显式接受:拆 ORM 的风险远大于收益。
- **两层概念并存**。迁移完成前,`app/api/` 与 `modules/` 会同时存在,
  新人需要先看本文件才知道该往哪放代码。

## 护栏

- `tests/test_architecture_boundaries.py` 增加两条规则:
  - `modules/<a>/` 不得 import `modules/<b>/` 的非 `service` 模块
  - `modules/` 内不得 import 顶层 `app.api.*`
- 每个域迁完后,更新 `docs/roadmap.md` 的迁移状态表。
- 迁移期间,新增功能**一律进 `modules/`**,不再往 `app/services/` 平铺。
