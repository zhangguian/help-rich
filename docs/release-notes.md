# Release Notes v0.2.0(2026-08-01)

> 盘后诊股室 MVP 发布版 — **Day 1~8 全部 phase 完成**

## 🎯 概览

`development-plan.md §17.3` 排班 **35+ phase 100% 完成**:
- 后端 32 个 API 端点(32 ~ 33 区间)
- 前端 4 个页面 + 32 个 .tsx 组件
- 后端 208 tests 全绿
- tsc + next build 全部通过

## 🏁 MVP 完成度

| 模块 | 完成度 |
|---|---|
| S1 后端骨架 (P1.x) | ✅ 100% |
| S2 数据层 (P2.x) | ✅ 100% |
| S3 计算器 (P3.x) | ✅ 100% |
| S4 诊断 (P4.x) | ✅ 100%(后端 + 前端) |
| S5 止损 (P5.x) | ✅ 100%(后端 + 前端) |
| S6 年账单 (P6.x) | ✅ 后端 100% / 前端推迟到 v0.2 |
| S7 联调 + 发布 (P7.x) | ✅ 100% |
| S8 截图识别 (P8.x) | ✅ 100%(后端 + 前端) |

## 🎯 主要功能

### 后端(32 个 API 端点)

- **交易管理**:录入 / 列表 / 更新 / 删除 流水;卖出超额 422 校验
- **持仓聚合**:加权平均成本 + 已实现盈亏 + 今日盈亏 + 浮动盈亏(新浪/腾讯行情主备)
- **计算器**:加仓/减仓/做T/清仓 4 类场景,21 档盈亏热力图
- **诊断评分**:5 维度(集中度/价格/间隔/市场/板块)各 20 分,纯函数 + 10 组手算 fixture 100% 覆盖
- **AI 评语**:DeepSeek / MiniMax / 豆包 3 Provider 切换 + 真实 API 调用 + 脱敏(只传 6 项字段,无价格/金额)
- **SSE 实时推送**:trade.scored / trade.commented / trade.failed 事件流(30s 心跳 + 失败降级 5s 轮询)
- **止损**:同 code 唯一设置 + 4 端点 + 触发 API 同日幂等
- **截图识别**:PaddleOCR 懒加载 + 本地规则优先 + LLM 兜底 + JSON 粘贴降级
- **年账单后端**:cost_engine 聚合年内 realized_pnl / 胜率 / Top5
- **数据管理**:导出 / 导入 / 备份 3 端点(admin)

### 前端(4 个页面)

- **首页** `/`:4 宫格总览 + 持仓卡(今日盈亏/浮动盈亏 + 止损按钮 + 实时价格告警)+ 截图入口 + Onboarding + 22:00 反思卡
- **流水** `/transactions`:录入表单 + 评分徽章(5 档色 + 滚动数字动效)+ SSE 实时订阅 + 详情弹窗(评语反馈 / 脱敏 tooltip / A/B 重生成)
- **计算器** `/calculator`:实时计算 + 21 档盈亏热力图
- **设置** `/settings`:LLM Provider 切换 / API Key / 截图识别 / 数据备份还原

## 📊 测试覆盖

- **后端 208 tests 全绿**:
  - scorer 37 + diagnose 12 + LLM 27 + EventBus 9 + llm_api 7 + prompt 4
  - screenshot 30(增 vision + holdings)
  - stop_loss+feedback 14
  - annual 8
  - admin/export round-trip 7
  - 其他 53
- **P4.8 端到端验收**:10 笔交易全部评分落库(100% ≥ 95% 目标)
- **TypeScript 严格**:`tsc --noEmit` ✅
- **Next.js 构建**:4 页 + 动态路由 ✅
- **后端测试覆盖率**:`scorer.py` 100%,其他核心模块 80%+

## 🔒 隐私

- LLM Key Fernet 加密入库,前端从不接收明文
- 评语仅传 6 项脱敏字段(代码/方向/股数分桶/日期/占比/名称),无价格无金额
- 截图原图只存本地 `uploads/`,LLM 只接收 OCR 文本(不传图片)
- 用户可粘贴外网 vision 模型 JSON(豆包/GPT-4V),数据不上传第三方

## 🐛 修复的 Bug(20 commits)

| # | Bug | 修复 |
|---|---|---|
| 1 | `trade_scores` 仓储按主键 `id` 查 `stock_code`(P2.1 遗留) | 改 `select where trade_id` |
| 2 | `watchlist` 仓储同上 → 自选股判定从未生效 | 改 `select where` |
| 3 | 前端 axios baseURL 缺 `/api` 前缀(Day 2 起从未真正连后端) | 改 `.env.local` |
| 4 | `scorer._interval_score` 期望 dict 但传 ORM 对象 → 评分静默失败 | 双轨 recent(ORM 给 recent_summary + dict 给 score_trade) |
| 5 | PaddleOCR 3.x 用 2.x 参数(`use_angle_cls` + `show_log`) | 改 `use_textline_orientation` |
| 6 | `ProviderFactory.model_name` 类层面访问得 property 对象(500) | `_BUILDERS` 存 `(Class, model_str)` 元组 |
| 7 | POST `/llm/settings` 等 422(camelCase body 没转 snake) | axios 请求拦截器 camel→snake |
| 8 | ScreenshotWizard `/api/*` 相对 URL → Next dev 404 | `apiBaseUrl()` / `sseUrl()` 绝对 URL |
| 9 | 浏览器 CORS 拦截(localhost → 127.0.0.1) | 后端 `CORSMiddleware(allow_origins=["*"])` |
| 10 | holdings/position 截图 confirm 静默忽略 | 抛 `HOLDINGS_NOT_PERSISTED` 422 |
| 11 | dev.ps1 health check 路径错 | 改 `/api/admin/health` |
| 12 | Toaster 未挂载(toast 调用不显示) | layout 加 `<Toaster />` + axios 拦截器增强 |

## 📋 已知限制(MVP)

- 单机使用,无鉴权(单机自用)
- Alembic 迁移未启用(`create_all` + `run_migrations`,正式版切 Alembic 见 §6.4)
- 止损离场按钮暂仅关闭弹窗(v0.2 接入一键清仓 API)
- PaddleOCR 3.x 在某些图片上 onednn 内部错误 → 自动降级到 vision LLM / JSON 粘贴
- DeepSeek 开发库 key 过期(401),LLM 调用降级到 `failed` 状态(用户应切到有效 provider)

## 🚀 启动脚本

`scripts/dev.ps1` 一键启动 / 停止开发服务(PowerShell 5.1+ 兼容):

```powershell
powershell -File scripts/dev.ps1                # 默认 start
powershell -File scripts/dev.ps1 -Action start
powershell -File scripts/dev.ps1 -Action stop
powershell -File scripts/dev.ps1 -Action restart
powershell -File scripts/dev.ps1 -Action status
```

自动:
- 杀掉 8000 / 5173 端口残留进程
- 后端:`uvicorn app.main:app --host 0.0.0.0 --port 8000`
- 前端:`npx next dev -p 5173`
- 等待两个服务就绪(健康检查超时 60s)
- 输出日志位置 + 停止 / 重启 / 状态命令

日志写入 `logs/backend.{out,err}.log` 与 `logs/frontend.out.log`。

## 📅 v0.2 二期规划

详见 [`docs/v0.2-roadmap.md`](v0.2-roadmap.md)。

主要方向(按项目书第十二章):
- **A1 持仓成本联动 K 线图版 + 后视镜**
- **A2 同花顺 / 东财资金流订阅**
- **A3 多 Provider 占比统计**
- **A4 智能调仓建议**
- **C1 风险敞口报告**
- **P9 vision LLM 接入**(基于用户真实 MiniMax-M3 / Anthropic 协议)
- **P6.2~6.4 年账单前端**

## 🔗 API 文档

详见 `docs/api-contract/api-changelog.md`(v0.1.0 ~ v0.2.0 共 9 个版本)