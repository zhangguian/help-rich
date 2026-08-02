# Release Notes v0.4.2(2026-08-02)

## 🎯 v0.4 产品转型:从"记账工具"到"买股看股工具"

> 用户拍板修正产品定位:核心是**帮小白股民看自选/持仓涨跌、分析 K 线、看多看空、放量缩量、通道、企稳点、给出操作建议**;记账向功能降级保留。

- 首页重写为 **三区盯盘工作台**:左盯盘列表(自选+持仓)→ 中 K 线(日/周/月/60分)→ 右上操作提示 + 右下 AI 对话,点击即三区联动
- **UI 全面升级 Liquid Glass**:纯黑 void 单主题、玻璃面板(blur 40px + inset 顶光)、emerald 霓虹交互强调、Plus Jakarta Sans + JetBrains Mono 自托管字体、全站动效铁律(切换必有动效)
- **AI 只翻译不计算**:MA/量比/通道/支撑压力/企稳 全部确定性算法(`ta_service`);LLM 仅做白话解读,失败自动降级纯指标,页面永不空白
- **AI 分析**:看多/看空/中性大徽章 + 5 指标卡 + 支撑压力价位 + 企稳理由 + 风险提示,一键重新分析
- **AI 对话**:单轮问答助手,自动结合你的持仓成本回答("我 60 块的成本,现在该止损吗?")
- **顶 tab 收编**:板块资金(含 🔔 异动 SSE toast 订阅)与 7×24 快讯收进工作台中间区
- **设置页「🕰 历史工具」分区**:年账单 / 风险报告 / 调仓 / Provider 占比 / 计算器 / 流水 / 持仓健康 / 板块资金独立页 8 个记账向页面统一收编,代码数据保留
- **测试 294 → 325 全绿**(+31:指标层 17 + AI 解读 14);端到端实测 analysis 返回真实 LLM 解读(bullish)、chat 真实回答、quotes/positions/watchlist 全通

---

# Release Notes v0.3.0(2026-08-02)(历史版本)

> 买股工具室 v0.2 二期完成版 — **v0.2-roadmap 排班 8 个 Day 全部完成**

## 🎯 概览

相对 v0.2.0 的累计变更(MVP → v0.3.0):
- 后端 32 → **46 个 API 端点**
- 前端 4 → **10 个页面 + 持仓管理 client 化 + 一键清仓 Modal + SSE 订阅 toast**
- 测试 208 → **294 tests 全绿**(+86)
- 持仓架构从"流水聚合视图" → **持仓主数据表**(关键设计哲学翻转)
- 产品名:盘后诊股室 → **买股工具室**
- 新增 2 个真实数据源(新浪 K 线 / 新浪板块资金排行 + 7×24 快讯)
- 0 mock 残留(测试基础设施 mock ≠ 生产 mock)

## 🆕 v0.3.0 主要功能(按 roadmap Day 排序)

### Day 1 — P9 vision LLM 接入(2h)
- **MiniMax `abab-v-chat` 多模态**:OCR 失败时 fallback 到视觉识别(base64 data URL → JSON 输出)
- `BaseLLM.chat_with_image()` / `supports_vision` 抽象;非视觉 Provider 抛 NotImplementedError
- `screenshot_service` 自动选择:OCR → vision → paste-JSON 三级降级

### Day 2 — P6.2~6.4 年账单前端(4h)
- `/annual-report/[year]` 页:4 宫格(已实现盈亏 / 盈利 / 亏损 / 胜率)+ Top5 最赚 + Top5 最亏
- 首页 / 反思卡 / 计算器 / 风险报告 多处入口
- `no_transactions` 提示(v0.4.0):无流水时引导"导入持仓或录入流水"

### Day 3 — A1 持仓 K 线图(4h)
- `lightweight-charts@4`(~200KB)替代自研 SVG
- `PositionDetailModal` 集成:K 线 + 资金流 SSE
- 持仓详情弹窗内可看日 K / 实时资金流推送

### Day 4 — P-stop-loss-v2 一键清仓 API(2h) — 新增 Day 7
- `POST /api/positions/{code}/clear` body `{price, note?}`:自动 sell 流水覆盖全部股数 → recalc_position 联动删除持仓行
- 前端 [🛑 一键清仓] 按钮 + 确认 Modal(实时盈亏预估)
- **修复 recalc bug**:`aggregate_positions` 严格校验+过滤导致 sell 后负股数失算;加双开关 `(strict, keep_zero)`

### Day 5 — A2 资金流订阅(3h) — 半成补完
- 单只资金流被公司网络 blocked(东财 RST / 网易 502 / 腾讯 param error / 同花顺限流),所有免费源不可用
- **板块异动订阅补完**:`sector_fund_flow_service._detect_alerts` 纯函数(净额绝对变化 ≥ 1 亿 / 领涨股切换 / 新进榜 三规则)
- `start_sector_scheduler` 后台 60s 拉 fenlei=0 → publish `sector_fund_flow_alert`
- `GET /api/sector-fund-flow/events?fenlei=` SSE 端点(按 fenlei 过滤)
- 前端 `/sector-fund-flow` 页加 [🔔 订阅异动] 开关 + 异动列表 + toast

### Day 6 — C1 风险敞口(3h)
- `risk_service.calc_risk()`:单股集中度 + HHI 指数 + 板块分散 + 风险评分 0~100
- `GET /api/risk-report` 端点 + `/risk-report` 页:4 宫格 + 警告区 + 单股集中度条形图 + 板块分布
- v0.4.0 后端到端验证:3 只持仓(茅台 100@1500 + 平安 1000@12 + 宁德 200@200) → total=3, market=20.2 万, top=74.26%, HHI=5942, level=高, 2 条警告

### Day 7 — P-privacy Alembic + A4 调仓(已完成)

**P-privacy Alembic 切换**:
- `uv add alembic==1.13.3` + `migrations/` 初始化 + `env.py` 读 DATABASE_URL env var
- 4 个迁移:initial + fund_flow + kline + positions
- `lifespan` 改 `subprocess.run -m alembic upgrade head`(同步,绕开 Windows asyncio 子进程限制)
- 测试环境自动建表
- v0.4.0 修复 kline head multiple heads 问题

**A4 智能调仓建议**:
- 4 规则启发式:`reduce`(单股 >30% 占 15%) / `add`(持仓 <3 只) / `diversify`(同板块 ≥3) / `alert`(top1 >50%)
- `GET /api/rebalance-suggestion` + `/rebalance` 页

### Day 8 — A3 多 Provider 占比月度(1h)
- `GET /api/provider-stats/monthly?year=2026`:12 个月 Provider / status 分布
- `GET /api/provider-stats/summary?year=2026`:年度汇总(柱状图友好)
- `/provider-stats` 页:年度柱状图 + 月度明细表格 + Provider 颜色映射

### 持仓主数据化(横跨 v0.4.0) — 核心重构

**问题**:软件初衷是"管理和复盘持仓",但持仓只是流水聚合视图,截图导入持仓被拒 → 真实持仓无法进入系统。

**设计哲学翻转**(v0.4.0):
- `positions` 表 = **主数据**(手动录入 / 截图导入 / 流水同步)
- `transactions` 流水 = **事件记录**(复盘用)
- 持仓 = **导入基准(delta) + 全部流水聚合**
- delta 运行时推导,**不落库**(capture_delta 变更前 → 变更流水 → recalc_position 变更后传 delta)

**关键修正**:`recalc_position` 原实现有数学死结(delta + flow 恒等式 + 流水入库后不可推导),**两段式 capture_delta + recalc_position** 是正确解。

**新增/变更端点**:
- `POST /api/positions` 手动录入/覆盖单只持仓(每股成本价口径)
- `DELETE /api/positions/{code}` 删除持仓(**联动删除该股全部流水**,防 recalc 复活)
- `GET /api/holdings-health` 持仓体检(真实持仓 + 实时行情 + calc_risk)
- `POST /api/screenshot/{id}/confirm`(holdings/position 类型)→ 改为导入持仓主数据(原 422 `HOLDINGS_NOT_PERSISTED` 删除)

**前端**:
- 首页持仓区 client 化 `PositionsSection`(添加 / 删除 / CustomEvent `positions-updated` 自动刷新)
- `ScreenshotPreview` 持仓可编辑核心字段(shares/price/cost_price)+ 确认导入
- `/holdings-health` 页

### 产品改名(横跨 v0.4.0)
- **盘后诊股室 → 买股工具室**(副标题 → 个人股票投资辅助工具)
- 18 个文件 + 34 处替换
- PowerShell 写入默认带 BOM,已用 `UTF8Encoding($false)` 修复

### 真实数据源接入(v0.3.2 起)
- **0 mock 残留**(`grep -r "mock" backend/app` 仅 mock 注释)
- 新浪 `quotes.sina.cn` K 线(`CN_MarketDataService.getKLineData`)
- 新浪 `MoneyFlow.ssl_bkzj_bk` 板块资金排行
- 新浪 `MoneyFlow.ssl_bkzj_ssggzj` 单只资金流排行(用于手动触发)
- 新浪 `zhibo.sina.com.cn/api/zhibo/feed` 7×24 快讯(JSONP + 纯 JSON 双格式兼容)
- 数据源不可用 502 `DATA_SOURCE_UNAVAILABLE`(友好提示,无 fallback)

## 🐛 修复的关键 Bug

| # | Bug | 修复 |
|---|---|---|
| 1 | screenshot confirm 静默忽略 holdings/position 类型 | 改为导入持仓主数据(v0.4.0) |
| 2 | 持仓是流水聚合视图,真实持仓无法导入 | 持仓主数据化(v0.4.0 核心重构) |
| 3 | `recalc_position` 恒等式(delta + flow 永不变化) | 两段式 capture_delta + recalc(v0.4.0) |
| 4 | 卖出超额请求无业务校验 | 读持仓表实时校验(v0.4.0) |
| 5 | `_detect_alerts` 测试阈值方向错 | 修测试断言(v0.4.1) |
| 6 | `border-bd-subtle` 错误类名(板块资金页) | 改 `border-border-def`(v0.4.1) |
| 7 | `text-up` 错误用做错误提示色 | 改 `text-down`(v0.4.1) |
| 8 | /risk-report /rebalance 字段名 snake_case 不匹配 camelCase 拦截器 | 改 camelCase + 用 `decimalFormat` 处理数字(v0.4.1) |
| 9 | v0.4.0 commit 漏 add 一批改动文件 | 后续 commit 一次性补全 + 注释说明(v0.4.1) |
| 10 | 风险敞口页面运行时报错 `data.total_market_value.toFixed` undefined | 接口统一 camelCase(v0.4.1) |

## 📊 测试覆盖

**后端 294 tests 全绿**(从 v0.2.0 的 208 增加 86 条):
- v0.3.2 真实数据源 23 条(K 线 + 资金流 + 板块)
- v0.3.3 调仓建议 9 条
- v0.3.4 板块资金 + 快讯 9 条
- v0.4.0 持仓主数据化 17 条(test_positions_v040)
- v0.4.1 板块异动 + 一键清仓 13 条
- 其他 bug 修复 15 条

**端到端验收**:
- 持仓粘贴 JSON → 一键导入 → 3 只入库 → 体检 → 删除联动 全通
- 一键清仓 600519 100@1450 → 清仓 @1500 → realized=5000.00
- 风险报告 3 只 → top=74.26%, HHI=5942, level=高

## 🔒 隐私

- LLM Key Fernet 加密入库,前端从不接收明文
- 评语仅传 6 项脱敏字段(代码/方向/股数分桶/日期/占比/名称),无价格无金额
- 截图原图只存本地 `uploads/`,LLM 只接收 OCR 文本(不传图片)
- 用户可粘贴外网 vision 模型 JSON(豆包/GPT-4V),数据不上传第三方

## 🚀 启动脚本

`scripts/dev.ps1` 一键启动 / 停止开发服务(PowerShell 5.1+ 兼容):

```powershell
powershell -File scripts/dev.ps1                # 默认 start
powershell -File scripts/dev.ps1 -Action start
powershell -File scripts/dev.ps1 -Action stop
powershell -File scripts/dev.ps1 -Action restart
powershell -File scripts/dev.ps1 -Action status
```

## 📋 已知限制

- 单机使用,无鉴权(单机自用)
- 止损离场真实化(已通过一键清仓 API 落地,但 StopLossAlert 仍仅提示,未自动触发清仓)
- 单只资金流推送 blocked(公司网络限流;板块异动推送已补)
- 引导视频 / 截图示例 / 多语言(i18n) 推迟到 v0.4+ 锦上添花期
- DeepSeek 等 LLM Key 过期会导致 failed 降级(用户应切到有效 provider)

## 🔗 API 文档

详见 `docs/api-contract/api-changelog.md`(v0.1.0 ~ v0.4.1 共 14 个版本)