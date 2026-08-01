# Release Notes v0.1.0(2026-08-01)

> 盘后诊股室 MVP 首版

## 🎯 主要功能

### 后端(30 个 API 端点)

- **交易管理**:录入 / 列表 / 更新 / 删除 流水;卖出超额 422 校验
- **持仓聚合**:加权平均成本 + 已实现盈亏 + 今日盈亏 + 浮动盈亏(新浪/腾讯行情主备)
- **计算器**:加仓/减仓/做T/清仓 4 类场景,21 档盈亏热力图
- **诊断评分**(P4):5 维度(集中度/价格/间隔/市场/板块)各 20 分,纯函数 + 10 组手算 fixture 100% 覆盖
- **AI 评语**(P4):DeepSeek / MiniMax / 豆包 3 Provider 切换 + 真实 API 调用 + 脱敏(只传 6 项字段,无价格/金额)
- **SSE 实时推送**:trade.scored / trade.commented / trade.failed 事件流(30s 心跳 + 失败降级)
- **止损**(P5):同 code 唯一设置 + 4 端点 + 触发 API 同日幂等
- **截图识别**(P8):PaddleOCR 懒加载 + 本地规则优先 + LLM 兜底 + JSON 粘贴降级
- **年账单后端**(P6,v0.2 预留):cost_engine 聚合年内 realized_pnl / 胜率 / Top5

### 前端(4 个页面)

- **首页** `/`:4 宫格总览 + 持仓卡(今日盈亏/浮动盈亏)+ 止损按钮 + 截图入口 + Onboarding
- **流水** `/transactions`:录入表单 + 评分徽章(5 档色 + 滚动动效)+ SSE 实时订阅 + 详情弹窗(评语反馈/脱敏 tooltip/A/B 重生成)
- **计算器** `/calculator`:实时计算 + 21 档盈亏热力图
- **设置** `/settings`:LLM Provider / API Key / 截图识别

## 📊 测试覆盖

- **后端 197 tests 全绿**:scorer 37 + diagnose 11 + LLM 27 + EventBus 9 + llm_api 7 + prompt 4 + screenshot 26 + stop_loss+feedback 14 + annual 8 + 其他
- **P4.8 端到端验收**:10 笔交易全部评分落库(100% ≥ 95% 目标)
- **TypeScript 严格**:tsc --noEmit ✅
- **Next.js 构建**:4 页 + 动态路由 ✅

## 🔒 隐私

- LLM Key Fernet 加密入库,前端从不接收明文
- 评语仅传 6 项脱敏字段(代码/方向/股数分桶/日期/占比/名称),无价格无金额
- 截图原图只存本地 uploads/,LLM 只接收 OCR 文本

## 🐛 修复的 Bug

- `trade_scores` / `watchlist` 仓储按主键 `id` 查 `trade_code` 的 2 个同源老 bug(P2.1 遗留,自选股判定从未生效)
- 前端 axios baseURL 缺 `/api` 前缀(Day 2 起所有页面从未真正连上后端)
- `scorer._interval_score` 期望 dict 但 ORM 对象传入 → 评分静默失败

## 📋 已知限制(MVP)

- 单机使用,无鉴权
- Alembic 迁移未启用(用 create_all,正式版切 Alembic 见 §6.4)
- 止损离场按钮暂仅关闭弹窗(v0.2 接入交易 API)
- 年账单仅后端,前端推迟到 v0.2
- 截图识别仅上传 + 确认流程,批量 / 编辑表单 v0.2

## 🔗 API 文档

详见 `docs/api-contract/api-changelog.md`(v0.1.0 ~ v0.1.8 共 8 个版本)