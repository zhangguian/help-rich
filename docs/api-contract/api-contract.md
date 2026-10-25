# API 契约文档:买股工具室

**文档版本**:v2.1
**最后更新**:2026-08-01
**对应代码版本**:v0.1.0(MVP)
**对应后端架构**:`backend-architecture.md` v2.1

**Base URL**:`http://localhost:8000`
**API 前缀**:`/api`
**鉴权**:MVP 无鉴权(单机自用)
**数据格式**:JSON,UTF-8

---

## 1. 端点总览

| 方法 | 路径 | 模块 | 说明 |
|---|---|---|---|
| GET | /health | 系统 | 健康检查 |
| GET | /positions | 持仓 | 持仓列表(含今日盈亏) |
| GET | /quotes/{code} | 行情 | 单只实时行情(P3.5 新增) |
| GET | /quotes | 行情 | 批量实时行情,最多 50 只(P3.5 新增) |
| GET | /transactions | 流水 | 流水列表 |
| POST | /transactions | 流水 | 录入交易 |
| PATCH | /transactions/{id} | 流水 | 修改 |
| DELETE | /transactions/{id} | 流水 | 删除 |
| POST | /calculator | 计算器 | 计算新成本 + 21 档 |
| POST | /calculator/review | 计算器 | 交易复核(做 T 方向 / 上限,按品种分流) |
| GET | /stock/{code}/analysis | 个股分析 | 技术指标 + AI 解读 + 行业标签 |
| GET | /stock/{code}/decision | 个股分析 | 确定性决策卡(零 LLM)+ 操作建议六格 + 网格建议 |
| GET | /stock/{code}/decision-advice | 个股分析 | 操作建议白话(按钮触发,LLM 失败退回规则文案) |
| GET | /stock/{code}/industry | 个股分析 | 行业归属(ETF 返回跟踪指数) |
| POST | /diagnose/{trade_id} | 诊断 | 触发评分 + 评语 |
| GET | /diagnose/{trade_id} | 诊断 | 获取评分(轮询降级) |
| POST | /diagnose/{trade_id}/regenerate | 诊断 | A/B 用其他模型重新生成 |
| GET | /stop-losses | 止损 | 止损列表 |
| POST | /stop-losses | 止损 | 设置 / 更新止损 |
| DELETE | /stop-losses/{code} | 止损 | 删除止损 |
| POST | /stop-losses/{code}/triggered | 止损 | 标记触发(幂等) |
| GET | /annual-report/{year} | 年账单 | 年度账单 |
| GET | /watchlist | 自选股 | 自选股列表 |
| POST | /watchlist | 自选股 | 加入 |
| DELETE | /watchlist/{code} | 自选股 | 移除 |
| GET | /events/sse | SSE | 诊断结果推送 |
| GET | /llm/providers | LLM | 可用 provider 列表 |
| GET | /llm/settings | LLM | 当前激活 provider |
| POST | /llm/settings | LLM | 切换 provider |
| GET | /llm/keys | LLM | 3 Provider Key 配置状态 |
| PUT | /llm/keys | LLM | 更新 Key |
| POST | /llm/test | LLM | 测试 Key 连接 |
| POST | /screenshot/upload | 截图 | 上传 + 异步识别 |
| GET | /screenshot/pending | 截图 | 待确认列表 |
| POST | /screenshot/{id}/confirm | 截图 | 用户确认入库 |
| POST | /screenshot/{id}/reject | 截图 | 取消 |
| POST | /screenshot/parse-paste | 截图 | 降级路径解析粘贴 JSON |

---

## 2. 健康检查

### GET /api/health
**目的**:检测后端是否存活

**响应 200**:
```json
{ "status": "ok" }
```

---

## 2.5 行情(P3.5 新增)

### 2.5.1 GET /api/quotes/{code}

**目的**:获取单只实时行情(新浪主 + 腾讯备 + 5 分钟缓存)

**请求参数**:
| 参数 | 类型 | 说明 |
|---|---|---|
| code | str(path) | `600519.SH` / `000001.SZ` / `830799.BJ` |

**响应 200**:
```json
{
  "code": "600519.SH",
  "name": "贵州茅台",
  "current_price": "1350.600",
  "prev_close": "1361.760",
  "open": "1330.030",
  "high": "1355.720",
  "low": "1325.770",
  "change": "-11.160",
  "change_pct": -0.82,
  "volume": 5512752,
  "amount": "7373462605.000",
  "timestamp": "2026-08-01T14:03:52",
  "turnover_pct": null,
  "pe": null,
  "pb": null
}
```

**错误码**:
| code | HTTP | 触发条件 |
|---|---|---|
| — | 422 | 代码格式错误(需 6 位数字 + .SH/.SZ/.BJ) |
| — | 503 | 行情源不可用(新浪 + 腾讯都失败) |

### 2.5.2 GET /api/quotes?codes=600519.SH,000001.SZ

**目的**:批量获取行情,最多 50 只,返回数组。

**错误码**:同上(422 含具体非法代码)。

---

## 3. 交易流水

### 3.1 GET /api/transactions

**目的**:获取流水列表(支持分页 / 筛选)

**查询参数**:
| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| stock_code | str | 否 | 按股票筛选 |
| start_date | date | 否 | 起始日期(包含) |
| end_date | date | 否 | 结束日期(包含) |
| limit | int | 否 | 默认 50,最大 200 |
| offset | int | 否 | 默认 0 |

**响应 200**:
```json
{
  "items": [
    {
      "id": 1,
      "stock_code": "000001",
      "stock_name": "平安银行",
      "action": "buy",
      "shares": 500,
      "price": "10.500",
      "trade_date": "2026-07-30",
      "note": null,
      "score": 72,
      "created_at": "2026-07-30T15:30:00"
    }
  ],
  "total": 1
}
```

**业务说明**:`price` 是字符串(精度保护),前端 `decimalFormat` 显示
**关联**:触发诊断后,`score` 字段填充

### 3.2 POST /api/transactions

**目的**:录入一笔交易

**请求体**:
| 字段 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| stock_code | str | 是 | 6 位数字 | 股票代码 |
| action | enum | 是 | buy / sell | 交易方向 |
| shares | int | 是 | > 0 | 交易股数(整百) |
| price | Decimal | 是 | > 0,3 位小数 | 交易价格 |
| trade_date | date | 是 | YYYY-MM-DD | 交易日期 |
| note | str | 否 | ≤ 200 字 | 备注 |

**示例**:
```json
{
  "stock_code": "000001",
  "action": "buy",
  "shares": 500,
  "price": "10.500",
  "trade_date": "2026-07-30",
  "note": "看好银行板块"
}
```

**响应 201**:
```json
{
  "id": 1,
  "stock_code": "000001",
  "stock_name": "平安银行",
  ...
}
```

**错误码**:
| code | HTTP | 触发条件 | 用户文案 |
|---|---|---|---|
| INVALID_STOCK_CODE | 422 | 股票代码格式错误 | "代码格式错误,核对一下" |
| INSUFFICIENT_SHARES | 422 | 卖出股数超过持仓 | "这只票只剩 X 股了,卖不出 Y 股" |
| INVALID_PRICE | 422 | 价格 ≤ 0 | "价格似乎有问题,核对一下" |
| STOCK_NOT_FOUND | 404 | 股票代码不存在 | "找不到这只股票,核对一下代码" |

**后端副作用**:
1. 同步:写入 `transactions` 表(~5ms)
2. 异步:`BackgroundTasks.add_task(diagnose_service.score_and_notify, trade_id)`
3. SSE 推送 `trade.scored` → `trade.commented`/`trade.failed`

### 3.3 PATCH /api/transactions/{id}
**目的**:修改一笔交易(只能改 note / shares / price,不能改 stock_code / action)

**请求体**(所有字段可选):
```json
{
  "shares": 500,
  "price": "10.500",
  "note": "改备注"
}
```

**响应 200**:同 POST

### 3.4 DELETE /api/transactions/{id}
**目的**:删除一笔交易

**响应 204**:无内容

**业务说明**:删除后,持仓自动重算(`safe_write` 保护)

---

## 4. 持仓

### 4.1 GET /api/positions

**目的**:获取当前持仓列表(由 transactions 实时聚合,P3.5.1 起含行情字段)

**响应 200**:
```json
{
  "items": [
    {
      "stock_code": "000001.SZ",
      "stock_name": "平安银行",
      "shares": 1000,
      "avg_cost": "10.333",
      "total_cost": "10333.00",
      "realized_pnl": "399.90",
      "current_price": "10.500",
      "prev_close": "10.000",
      "today_pnl": "500.00",
      "floating_pnl": "167.00"
    }
  ]
}
```

**字段说明**:
- `shares` / `avg_cost` 来自 transactions 聚合(加权平均)
- `stock_code` 统一为带市场后缀格式(`600519.SH` / `000001.SZ`,P3.5.1 起)
- `current_price` / `prev_close` 来自行情接口(新浪主 + 腾讯备),缓存 5 分钟
- `today_pnl` = `(current_price - prev_close) × shares`(今日盈亏)
- `floating_pnl` = `(current_price - avg_cost) × shares`(浮动盈亏)
- **行情全部失败时**:`current_price` / `prev_close` / `today_pnl` / `floating_pnl` 为 `null`(前端降级显示 "--"),HTTP 仍 200
- 所有金额字段是 **字符串**(精度保护)

**错误码**:
| code | HTTP | 触发条件 |
|---|---|---|
| — | 200 | 行情失败不报错,字段置 null(降级) |

---

## 5. 交易成本计算器

### 5.1 POST /api/calculator

**目的**:试算加仓 / 减仓 / 做T 后新成本 + 21 档盈亏表

**请求体**:
| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| stock_code | str | 是 | 6 位数字或带后缀,如 `600519.SH`(P3.5.1 起统一规范化) |
| action | enum | 是 | buy / sell |
| tx_shares | int | 是 | > 0 |
| tx_price | Decimal | 是 | > 0,3 位小数 |

**响应 200**:
```json
{
  "before": {
    "shares": 1000,
    "cost_price": "10.000",
    "total_cost": "10000.00"
  },
  "after": {
    "shares": 1500,
    "cost_price": "10.333",
    "total_cost": "15500.00",
    "delta_cost": "0.333",
    "realized_pnl": "0"
  },
  "pnl_grid": [
    { "pct": -10, "price": "9.300", "market_value": "13950.00", "pnl": "-1550.00" },
    { "pct": 0, "price": "10.333", "market_value": "15499.50", "pnl": "-0.50" },
    { "pct": 10, "price": "11.366", "market_value": "17049.00", "pnl": "1549.00" }
  ]
}
```

**业务说明**:
- 21 档:`-10%` 到 `+10%`,每 1% 一档,基准 = `after.cost_price`(新成本)
- 加仓算法:加权平均(详见 `core/cost_engine.py`)
- 减仓算法:剩余成本不变,已实现盈亏 = `(tx_price - cost_before) × tx_shares`

**错误码**:
| code | HTTP | 触发条件 |
|---|---|---|
| INSUFFICIENT_SHARES | 422 | 卖出股数超过当前持仓 |
| INVALID_PRICE | 422 | 价格 ≤ 0 |

---

## 6. 单笔交易诊断

### 6.1 POST /api/diagnose/{trade_id}

**目的**:手动触发诊断(通常由 `POST /transactions` 自动触发)

**响应 202**:
```json
{ "trade_id": 1, "status": "pending" }
```

**业务说明**:立即返回,评分通过 SSE 推送

### 6.2 GET /api/diagnose/{trade_id}

**目的**:轮询获取评分(用于 SSE 降级)

**响应 200**:
```json
{
  "trade_id": 1,
  "score": 72,
  "score_breakdown": {
    "集中度": 15,
    "价格合理性": 12,
    "操作间隔": 20,
    "市场环境": 5,
    "板块热度": 20
  },
  "ai_comment": "买入价高于成本 8%,疑似追涨...",
  "ai_status": "success",
  "ai_provider": "deepseek",
  "ai_model": "deepseek-chat",
  "ai_latency_ms": 8200
}
```

**业务说明**:`ai_status` 取值:`pending` / `success` / `failed` / `no_key`(v2.1)

### 6.3 POST /api/diagnose/{trade_id}/regenerate

**目的**:用指定 Provider 重新生成评语(A/B 对比)

**查询参数**:
| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| provider | str | 是 | deepseek / minimax / doubao |

**响应 202**:`{ "trade_id": 1, "status": "pending" }`

---

## 7. 止损

### 7.1 GET /api/stop-losses

**响应 200**:
```json
{
  "items": [
    {
      "stock_code": "000001",
      "stop_loss_price": "9.500",
      "enabled": true,
      "notify_sound": true,
      "notify_desktop": true,
      "notify_vibrate": true,
      "last_triggered_at": null
    }
  ]
}
```

### 7.2 POST /api/stop-losses

**请求体**:
| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| stock_code | str | 是 | 6 位 |
| stop_loss_price | Decimal | 是 | > 0,3 位小数 |
| enabled | bool | 否 | 默认 true |
| notify_sound | bool | 否 | 默认 true |
| notify_desktop | bool | 否 | 默认 true |
| notify_vibrate | bool | 否 | 默认 true |

**响应 201**:同 GET 单条

### 7.3 DELETE /api/stop-losses/{code}
**响应 204**:无内容

### 7.4 POST /api/stop-losses/{code}/triggered
**目的**:标记止损已触发(幂等,同日重复调用 OK)

**请求体**:空

**响应 200**:`{ "ok": true }`

---

## 8. 年度账单

### GET /api/annual-report/{year}

**路径参数**:`year`(2024~2030)

**响应 200**:
```json
{
  "year": 2026,
  "realized_profit": "12500.00",
  "realized_loss": "8200.00",
  "net_pnl": "4300.00",
  "win_rate": 0.62,
  "top5_profit": [...],
  "top5_loss": [...]
}
```

**业务说明**:`win_rate` 是已平仓持仓的盈利笔数 / 总笔数

---

## 9. 自选股

### 9.1 GET /api/watchlist
**响应 200**:`{ "items": [{ "stock_code": "000001", "stock_name": "平安银行", "source": "manual", "added_at": "..." }] }`

### 9.2 POST /api/watchlist
**请求体**:`{ "stock_code": "000001", "stock_name": "平安银行" }`
**响应 201**

### 9.3 DELETE /api/watchlist/{code}
**响应 204**

---

## 10. SSE 推送

### GET /api/events/sse

**响应**:`text/event-stream`

**事件类型**:
```
event: trade.scored
data: {"event":"trade.scored","trade_id":1,"score":72,"breakdown":{...}}

event: trade.commented
data: {"event":"trade.commented","trade_id":1,"comment":"...","provider":"deepseek","model":"deepseek-chat","latency_ms":8200}

event: trade.failed
data: {"event":"trade.failed","trade_id":1,"reason":"DeepSeek 未配置 Key,请到设置页填写"}

event: ping
data: {"event":"ping","ts":1690890000}   ← 前端过滤
```

**业务说明**:
- 单连接全局,前端按 `trade_id` 过滤
- 心跳 30s/次,死连接 60s 自动清理
- 失败 3 次降级为 5s 轮询 `GET /diagnose/{trade_id}`

---

## 11. LLM Provider 管理

### 11.1 GET /api/llm/providers
**响应 200**:
```json
{
  "items": [
    {"name":"deepseek","model":"deepseek-chat","configured":true},
    {"name":"minimax","model":"abab6.5s-chat","configured":false},
    {"name":"doubao","model":"doubao-pro-32k","configured":false}
  ],
  "active": "deepseek"
}
```

### 11.2 GET /api/llm/settings
**响应 200**:`{ "active_provider": "deepseek" }`

### 11.3 POST /api/llm/settings
**请求体**:`{ "active_provider": "minimax" }`
**响应 200**:`{ "active_provider": "minimax" }`

**错误码**:`INVALID_PROVIDER 422`

### 11.4 GET /api/llm/keys(v2.1 新增)
**目的**:获取 3 Provider 的 Key 配置状态(不返回明文)

**响应 200**:
```json
{
  "deepseek": true,
  "minimax": false,
  "doubao": false
}
```

### 11.5 PUT /api/llm/keys(v2.1 新增)
**请求体**(空字符串 = 不修改 / 清空):
```json
{
  "deepseek": "sk-新key-xxx",
  "minimax": "",
  "doubao": ""
}
```

**响应 200**:`{ "ok": true }`

**业务说明**:
- Key 通过 Fernet 加密后存 `llm_api_keys.encrypted_key`
- `FERNET_KEY` 存 `.env`,首次启动自动生成
- PUT 后立即生效,无需重启
- 不返回明文 Key,前端从不接收

### 11.6 POST /api/llm/test(v2.1 新增)
**请求体**:`{ "provider": "deepseek" }`

**响应 200**:`{ "ok": true, "latency_ms": 1200 }`

**错误码**:
| code | HTTP | 触发 | 用户文案 |
|---|---|---|---|
| NO_KEY | 400 | 未配置 Key | "请先在设置页配置 Key" |
| INVALID_KEY | 401 | 401 错误 | "Key 无效,请核对" |
| FORBIDDEN | 403 | 403 错误 | "Key 权限不足" |
| LLM_TIMEOUT | 504 | 超时 | "连接超时,网络可能不稳" |

---

## 12. 截图识别

### 12.1 POST /api/screenshot/upload

**请求**:`multipart/form-data`,字段 `file`(jpg/png/webp,≤ 5MB)

**响应 202**:
```json
{ "record_id": 1, "status": "pending" }
```

**业务说明**:异步识别,完成后 SSE 推送 `screenshot.parsed` 事件

**错误码**:
| code | HTTP | 触发 |
|---|---|---|
| UNSUPPORTED_FORMAT | 415 | 非 jpg/png/webp |
| FILE_TOO_LARGE | 413 | > 5MB |
| OCR_FAILED | 500 | PaddleOCR 异常 |

### 12.2 GET /api/screenshot/pending
**响应 200**:`{ "items": [{ "id": 1, "screenshot_type": "position", "parsed_items": [...], "created_at": "..." }] }`

### 12.3 POST /api/screenshot/{id}/confirm
**请求体**:
```json
{
  "screenshot_type": "position",
  "items": [
    { "stock_code": "000001", "stock_name": "平安银行", "shares": 1000, "price": "10.500", "confidence": 0.95 }
  ]
}
```

**响应 200**:`{ "ok": true, "inserted": 2 }`

### 12.4 POST /api/screenshot/{id}/reject
**响应 200**:`{ "ok": true }`
**业务说明**:删除原图 `~/rich/uploads/{uuid}.jpg`

### 12.5 POST /api/screenshot/parse-paste(降级路径)
**请求体**:
```json
{
  "screenshot_type": "position",
  "items": [...],
  "confidence": 0.9
}
```

**响应 200**:`{ "record_id": 2, "items": [...] }`

---

## 13. 场内 ETF 品种与规则(v0.6 新增)

> 场内 ETF / 场内 LOF 与股票的**交易规则不同**:免印花税、免过户费、无涨跌停限制、
> 跨境/商品类当日可回转(T+0)。本节记录与品种相关的契约差异。
> 完整设计与实测记录见 `docs/etf-rfc.md`(实施规格 v1.0)。

### 13.1 GET /api/stock/{code}/industry

**目的**:标的行业归属(ETF 返回其跟踪指数)

**响应 200**:
```json
{
  "code": "513120.SH",
  "industry": "跟踪中证香港创新药",
  "source": "etf_index",
  "note": "场内 ETF · QDII"
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `code` | string | 规范化代码(带市场后缀) |
| `industry` | string \| null | 股票=行业名;ETF=「跟踪 {指数}」;查不到=null(**不编造**) |
| `source` | string | `baostock`(离线行业表)/ `etf_index`(ETF 品种表)/ `sina`(行情排行榜反查) |
| `note` | string \| null | ETF 附注(形态 · 类别),如「场内 ETF · QDII」;股票为 null |

**错误**:代码格式非法 → 422 `INVALID_STOCK_CODE`

### 13.2 GET /api/stock/{code}/analysis —— 新增三个字段

在既有响应体上新增(节点缓存命中与未命中**两条路径都注入**):

| 字段 | 类型 | 说明 |
|---|---|---|
| `industry` | string \| null | 同 13.1 |
| `industry_source` | string \| null | 同 13.1 的 `source` |
| `industry_note` | string \| null | 同 13.1 的 `note` |

其余字段(含 `indicators` / `ai` / `degraded`)结构不变。

### 13.3 POST /api/calculator 与 POST /api/calculator/review —— 按品种选费用档

**请求体与响应结构不变**,行为按标的品种分流:

| 项 | 股票 | 场内 ETF / LOF |
|---|---|---|
| 费用档 | 印花税 + 过户费 + 佣金 | **免印花税、免过户费**,佣金沿用用户配置 |
| `t_directions.*.t_plus_one_note` | 「A 股 T+1:当天买入的股票当天不能卖出…」 | T+0 品种→「该品种为 T+0(当日可回转):当天买入的份额当天就能卖出…(具体以交易软件显示的品种属性为准)」 |
| `t_directions.forward.max_shares`(正T 上限) | `min(可动T仓 M, 资金可买股数)` | **T+0 品种:只受资金约束** `floor(可用资金 ÷ 买价)` |
| `t_directions.reverse.max_shares`(反T 上限) | 受可动 T 仓约束 | 同左(不变) |

**降级**:代码符合 ETF 格式但**未在品种表内**的标的,按保守口径(T+1 / 股票费率)计算,
并在 `degraded` 中明说「该 ETF 未在品种表内,已按保守口径(T+1 / 股票费率)计算,交易规则可能有偏差」。
**不静默、不假装已知**,也不因此报错。

### 13.4 GET /api/annual-report/{year}

逐笔按标的品种选费用档(ETF 免印花税/过户费);响应结构不变。

### 13.5 错误码

本次**无新增错误码**。表外 ETF 不报错 —— 按保守口径降级 + 明说降级原因。

---

## 13.6 操作决策与操作建议(v0.10 新增)

### 13.6.1 GET /api/stock/{code}/decision

**目的**:确定性决策卡(零 LLM、纯算法、秒出)+ 卡内「操作建议」区。

**响应 200**:
```jsonc
{
  "decision": {
    // —— 既有字段(语义不变)——
    "stock_code": "002185.SZ",
    "verdict": "hold",
    "headline": "现价 16.19 元,等触发:涨到 19.16 元可解套(需涨 5.1%)",
    "role": "解套参考",
    "confidence": "medium",
    "position_status": "loss",
    "actions": [ /* Action[] */ ],
    "stop_loss": { "price": 13.2, "basis": "跌破即止损" },
    "position_pct": "解套优先,减仓不追补",
    "do_not": ["下跌通道中不要抄底"],
    "t_plan": { /* TPlan */ },
    "trend_state": { "phase": "下跌通道·延续", "note": "..." },
    "market_env": { /* MarketContext */ },

    // —— v0.10 新增(纯增量)——
    "grid_plan": {
      "suitable": false,
      "mode": null,
      "reason": "",
      "range_low": null, "range_high": null, "span_pct": null,
      "grids": null, "step_pct": null, "step_price": null,
      "shares_per_grid": null, "capital_per_grid": null,
      "cash_needed": null, "cash_available": null,
      "net_step_pct": null, "roundtrip_fee_pct": null, "fee_basis": null,
      "net_profit_per_grid": null,
      "replace_t_plan": false,
      "risk": "",
      "unsuitable_signals": "下跌通道中不要布网格:越买越套"
    },
    "suggestions": {
      "price":     { "label": "价位", "value": "涨到 19.16 元可解套(需涨 5.1%)" },
      "stop_loss": { "label": "止损", "value": "13.20 元(距现价 -18.5%)" },
      "position":  { "label": "仓位", "value": "解套优先,减仓不追补" },
      "trigger":   { "label": "触发", "value": "涨到 19.16 元(P80 分位)" },
      "timing":    { "label": "时间", "value": "已持有 23 天,回本还需 +5.1%" },
      "avoid":     { "label": "不动", "value": "下跌通道中不要抄底" }
    },
    "advice": {
      "headline": "现价 16.19 元,等触发:涨到 19.16 元可解套(需涨 5.1%)",
      "bullets": ["价位:...", "网格不建议:...", "止损 ... · 仓位 ..."],
      "source": "rule"
    },
    "cost_anchor":    { "cost_basis": 17.02, "current_price": 16.19, "pnl_pct": -4.88,
                        "break_even_gap_pct": 5.12, "distance_to_stop_pct": -18.47,
                        "distance_to_target_pct": null, "risk_reward": null },
    "time_window":    { "holding_days": 23, "source": "transactions", "overdue": true,
                        "overdue_text": "已超 20 天阈值 3 天",
                        "note": "已持有 23 天(自然日,起点=最早一笔流水)" },
    "cost_effect":    { "roundtrip_fee_pct": 0.102, "fee_basis": "default_estimate",
                        "spread_pct": 9.7, "worth_it": true, "note": "..." },
    "instrument_rule":{ "kind": "stock", "t0": false, "notes": ["股票有涨跌幅限制(±10%)", "T+1,..."] },
    "concentration":  { "cost_share_pct": 12.0, "level": "low", "note": "..." },

    "data_quality": { "degraded": ["费用设置未启用,费用按默认档估算"] }
  }
}
```

**约定**:
- `suggestions` 六格**值可为 `null`**(= 该维度数据不足,前端整格不渲染,不显示空框);
- `grid_plan` **始终存在**;不适适时配置类字段一律 `null`,原因写在 `unsuitable_signals`;
- `advice.source` 恒为 `"rule"` —— 决策端点**零 LLM**,白话是规则拼的,不是模型写的;
- 五个维度**只增信息**,不改变 `verdict` / `actions` / `t_plan` 的既有判定。

### 13.6.2 GET /api/stock/{code}/decision-advice

**目的**:把决策事实包翻译成大白话(**按钮触发**,不在首屏自动烧 token)。

**响应 200**:
```json
{
  "advice": {
    "headline": "离回本还差 5.1%,别急着补仓",
    "bullets": ["跌破 13.20 元止损", "涨到 19.16 元再减"],
    "source": "llm",
    "generated_at": "2026-10-25T18:20:31"
  },
  "degraded": []
}
```

**降级**:
- LLM 未配置 / 超时 / 解析失败 → `source="rule"`(退回规则文案),**仍 200**,卡片永不空白;
- K 线完全不可用 → 502 `DATA_SOURCE_UNAVAILABLE`(与 `/decision` 一致);
- 进程内**当日缓存**(key = 代码 + 日期 + headline 摘要),跨日自动失效。

### 13.6.3 GET /api/stock/{code}/analysis(v0.10 变更)

- 响应结构**不变**;AI 不可用时 `ai=null` 行为不变;
- **变更**:提示词追加「决策事实包」(JSON),并加硬规则「数字必须原样引用,冲突时以事实包为准」;
- **不增加网络 IO**:事实包复用本端点已有的 klines / quote / position;
  市场环境**不纳入**事实包(那是 4~5 次外部 HTTP),「大盘普跌时不要加仓」由决策卡承担。

---

## 14. 错误码全局清单

| code | HTTP | 模块 | 用户文案 |
|---|---|---|---|
| INVALID_STOCK_CODE | 422 | 流水 | "代码格式错误,核对一下" |
| INSUFFICIENT_SHARES | 422 | 流水/计算器 | "这只票只剩 X 股了" |
| INVALID_PRICE | 422 | 流水/计算器 | "价格似乎有问题,核对一下" |
| STOCK_NOT_FOUND | 404 | 流水 | "找不到这只股票" |
| LLM_FAILED | 500 | 诊断 | "AI 评语暂时不可用" |
| AKSHARE_FAILED | 503 | 持仓 | "行情源不可用,显示陈旧数据" |
| INTERNAL_ERROR | 500 | 全局 | "服务异常,请重试" |
| INVALID_PROVIDER | 422 | LLM | "Provider 名称无效" |
| NO_KEY | 400 | LLM | "请先在设置页配置 Key" |
| INVALID_KEY | 401 | LLM | "Key 无效,请核对" |
| FORBIDDEN | 403 | LLM | "Key 权限不足" |
| LLM_TIMEOUT | 504 | LLM | "连接超时,网络可能不稳" |
| UNSUPPORTED_FORMAT | 415 | 截图 | "暂只支持 jpg/png/webp 格式" |
| FILE_TOO_LARGE | 413 | 截图 | "图片过大,请压缩后重试" |
| OCR_FAILED | 500 | 截图 | "OCR 失败,可粘贴外网模型输出" |
| INVALID_JSON | 422 | 截图降级 | "JSON 格式错误,请检查" |

---

## 15. 通用约定

### 14.1 时间
- 所有时间戳 ISO 8601 UTC:`2026-07-30T15:30:00`
- 日期:`YYYY-MM-DD`

### 14.2 金额
- **字符串传输**(精度保护)
- 前端用 `decimalFormat()` 工具格式化显示
- 后端 Python 用 `Decimal` 类型

### 14.3 错误响应格式
```json
{
  "code": "INVALID_STOCK_CODE",
  "message": "代码格式错误,核对一下",
  "detail": { "field": "stock_code", "value": "abc" }
}
```

### 14.4 字段命名
- 后端 Pydantic / 数据库:**snake_case**(`stock_code`)
- 前端 TS:**camelCase**(`stockCode`)
- 转换在 axios 拦截器自动完成(`frontend-arch §7.1`)