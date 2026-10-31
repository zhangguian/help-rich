# ADR-0006: 不引入 akshare;秒级盯盘走「服务端轮询 + SSE 推送」

## 状态
已采纳(2026-10-29)

## 背景

两个诉求撞在一起:

1. **评估 akshare**:官方文档站(`akshare.akfamily.xyz/tutorial.html`)被 Cloudflare 质询拦截,
   需要换源取一手材料;同时要判断它能不能替代本项目手搓的爬虫
   (`app/data/sina.py` / `tencent.py` / `market_snapshot.py` / `sector_constituents.py`)。
2. **"我需要秒级盯盘"**:需要分清"真秒级"与"伪秒级" —— A 股行情分 Level-1(3 秒快照)
   与 Level-2(逐笔 Tick,毫秒级)两档,两者协议、延迟、成本差异很大。

本 ADR 记录:实测证据、档位选择、以及随之落地的链路改造。

## 一、AKShare 评估(2026-10-29 实测)

### 1.1 它是什么

- PyPI 最新版 **1.20.2**(2026-10-28 发布),MIT,要求 **Python ≥ 3.11**(本项目 venv 是 3.11.14 ✅)。
- 定位:**把各家财经网站的爬虫封装成 `ak.xxx()` 返回 pandas DataFrame** 的开源库
  (东财/新浪/同花顺/巨潮/雪球/财联社…)。它**没有自己的数据**,全部靠抓上游网页。
- 1.20.x 新增**离线接口注册表**:`ak.search("可转债 实时行情")` 关键词检索接口名、
  `ak.interface_info("bond_cb_jsl")` 查参数与输出列 —— 对"盘点可用接口"本身很有用。
- 依赖足迹:`pandas>=2.0`、`lxml`、`beautifulsoup4`、`curl_cffi>=0.13.0`、`html5lib`、
  `xlrd`、`openpyxl`、`jsonpath`、`tabulate`、`tqdm`、`decorator`、`mini-racer`(V8,非 Linux)。

### 1.2 本项目现状

- `backend/pyproject.toml` **没有 akshare**(也没有 pandas)→ 当前 venv 里 `import akshare` 直接
  `ModuleNotFoundError`。(全局 Python 3.13 上有个 1.18.62,与项目 venv 无关。)
- ADR-0005(2026-08-01)已因"底层走东财、被限流"把 akshare 排除,决策是"akshare 已装,留作后续功能"。
- `plans/backend-architecture.md` §5.4 / §5.5.2 / §5.8 已为它预留完整位置
  (`data/akshare_client.py`、`asyncio.to_thread` 包装、精确锁版本、单点封装、失败率监控),
  但规划中的 `data/eastmoney.py` / `akshare_client.py` / `chain.py` 至今都不存在。

### 1.3 实测证据

**端点矩阵**(本机,公司网络):

| 端点 | 用途 | 结果 | 延迟 |
|---|---|---|---|
| `hq.sinajs.cn/list=多代码` | 新浪批量实时 | ✅ 稳定 | 0.60s |
| `qt.gtimg.cn/q=多代码` | 腾讯批量实时 | ✅ 稳定 | 0.56s |
| `push2.eastmoney.com/.../stock/get`(无 ut) | 单标的实时 | ✅ 曾通 | 1.04s |
| `push2.eastmoney.com/.../ulist.np/get`(无 ut) | 多标的批量 | ✅ 曾通 | 0.70s |
| `push2.eastmoney.com/.../clist/get`(无 ut) | 全市场列表 | ⚠️ 曾通后被限流 | 0.51s → RST |
| `push2his.eastmoney.com/.../kline/get`(无 ut) | 历史 K 线 | ⚠️ 曾通后被限流 | 1.15s → RST |
| `push2ex.eastmoney.com/getTopicZTPool` | 涨停池 | ✅ 通 | 10.8s |
| `datacenter-web.eastmoney.com/api/data/v1/get` | 沪深港通/北向 | ✅ 通 | 0.61s |
| **任何带 `ut=bd1d9ddb…` 的请求** | akshare 东财系 | ❌ **被 RST** | — |
| 通达信 TDX `119.147.212.81:7709` / `123.125.108.23:7709` | pytdx Tick | ❌ TCP 不通 | — |
| 同花顺 `q.10jqka.com.cn` | akshare 涨停池备源 | ❌ 401 | — |

**根因定位**(三轮对照实验):

1. 同 URL 同参数,**只改 `ut` 有无** → 带 `ut` 必 RST,去掉 `ut` 必通
   (`ut` 并非接口必需参数,去掉后返回完整数据 `total=5926`)。
2. 换 UA / 加 Referer → **不解决**(UA 矩阵全灭)→ 不是 UA/TLS 指纹问题。
3. 换 `trust_env`(绕环境代理)→ **不解决**(本机无代理环境变量)。
4. 高频访问后 → `push2` / `push2his` **整域 RST**,而 `push2ex` / `datacenter-web` /
   新浪 / 腾讯同期正常 → 拦截是**域级 + 突发触发**,不是全面封锁。

**akshare 自身实测**(全局 Python 3.13 + akshare 1.18.62 + pandas 3.0.3):
`stock_zh_a_spot_em` / `stock_board_industry_name_em` / `stock_board_industry_cons_em` /
`stock_zh_index_spot_em` 全部 `ConnectionError (RemoteDisconnected)`;
注入浏览器 UA + Referer 后**依然全灭**。源码取证:东财系共 **19 文件 / 53 处 `ut` 字面量**,
5 个令牌值(`bd1d9ddb…`×30、`7eea3edc…`×11、`b2884a39…`×7、`f057cbcb…`×4、`8dec03ba…`×1);
akshare 内部 `request_with_retry` **不带任何浏览器头**。

### 1.4 判定

| 维度 | 结论 |
|---|---|
| 可用性 | ❌ 东财系(akshare 的主力价值)在本网络被 `ut` 令牌拦截 + 突发整域限流 |
| 依赖成本 | ❌ 往极简 venv 塞 pandas/lxml/bs4/curl_cffi/mini-racer(V8) |
| 收益 | ⚠️ 它"省掉自己写爬虫"的价值在**我们这里本来就不成立** —— 新浪/腾讯行情、资金流、快讯、领涨股、申万行业成分、全市场快照均已手搓且稳定 |
| 维护 | ⚠️ 社区库,上游改版即挂,还要额外做"精确锁版本 + 单点封装 + 失败率监控"三件套 |

**结论:不引入 akshare。** 将来若确需东财数据,走**东财原生 HTTP 封装**
(不带 `ut`、低频、连通性门禁),而不是拖 akshare 进来。

## 二、秒级盯盘:档位选择

| 档位 | 协议 | 典型延迟 | 成本 | 本项目可用性 |
|---|---|---|---|---|
| ms 级 Tick | WebSocket 推送(efinance / AllTick) | ≤200ms | AllTick 付费;efinance 走东财 WS(实测受限) | ❌ 排除 |
| 逐笔成交 | 通达信 TCP(pytdx) | ms 级 | 免费 | ❌ 端口不通 |
| **3 秒快照** | HTTP 轮询(新浪/腾讯) | 2~3s | 免费 | ✅ **本项目目标档** |
| 1s K 线快照 | akshare/东财全市场 `clist` | ~1s | 免费但重(5500+ 只/次) | ⚠️ 突发限流 + 无 pandas |

**决定:做 3 秒快照档(Level-1)。** 盯盘看板 + 价格预警不需要逐笔;
"秒级"在本项目 = **端到端 ≤3s 的价格刷新**,不是 Tick。
产品内统一表述"3 秒快照",不写"秒级实时"(避免把伪秒级说成真秒级)。

**为什么不上 ms 级**:AllTick 免费层不含 Tick 推送;efinance 底层仍是东财(实测整域限流);
pytdx 的通达信服务器端口不通;且本项目的判定层吃的是价格档位,不是每一笔。

## 三、真正卡住"秒级"的不是数据源

| # | 位置 | 改造前 | 影响 |
|---|---|---|---|
| B1 | `services/quote_service.py` | `QUOTE_TTL = 300` 统一缓存 | 盘中价格最旧滞后 5 分钟 |
| B2 | `app/(app)/page.tsx` | 报价**只在首屏**拉一次(`useEffect` 依赖 `[]`) | 首屏之后价格不再更新 |
| B3 | `modules/alert/scheduler.py` / `useStopLossChecker.tsx` | 告警 60s 一轮;止损前端 15s 轮询 + 5 分钟缓存价 | 止损触达延迟分钟级 |

所以实施重点是**把已有数据源接成"服务端单例轮询 + SSE 推送 + 热路径零缓存"**,而不是换库。

## 四、决策

1. **不引入 akshare**(证据见 §1.3)。
2. **秒级口径 = 3 秒快照(Level-1)**,不做 ms 级 Tick(理由见 §2)。
3. **主源新浪、备源腾讯,维持不变**;新增 `QuoteService.get_quotes_fresh()` 作为
   **热路径**(跳过 5 分钟缓存),原 `get_quote` / `get_quotes` 行为**完全不变**
   (研究/历史路径继续吃 300s 缓存)。
4. **服务端单例轮询器**(`app/services/quote_poller.py`):盘中 2s 一轮拉
   自选 ∪ 持仓,写内存快照,经 `event_bus` 广播;连续失败退避 2→5→10→30s 封顶;
   无人订阅且无 REST 命中时降到 15s;非交易时段**完全停拉**。
5. **SSE 端点** `GET /api/quotes/stream`:首帧推当前快照(含 `stale` 与更新时间),
   后续推增量;`?codes=` 可过滤;30s 心跳。
6. **前端**:新增 `useQuoteStore`(zustand)+ `useQuoteStream`(SSE 订阅,断线降级 REST 轮询
   `?fresh=true`);列表行**按代码单只订阅** → 只有变价的那一行重渲染。
   降级**必须可逆**:断线时**保留** EventSource(浏览器自己会重连),收到帧即停轮询并回切;
   刷新后即便带着降级标记也照样建立 SSE —— 否则降级会变成"一次后端重启就再也回不来"的闩锁。
7. **止损检查**主路径改为**实时价驱动**(订阅 store),15s 轮询降为兜底;
   服务端告警扫描同样改走 fresh 路径(否则用 5 分钟缓存价判触达,最多晚 5 分钟才响)。

## 五、后果

- ✅ 盘中价格端到端 ≤3s 更新;止损触达从分钟级降到秒级
- ✅ 单一真源(服务端),前端不再各自轮询 → 公司网络出口压力降一个量级
- ✅ 研究路径的历史口径**不受影响**(300s 缓存原样保留)
- ✅ 失败可辨:`stale=true` + 最后更新时间,前端显式提示,不装作新鲜
- ⚠️ 非交易时段后端轮询器不拉 → 此时列表显示 REST 兜底价(5 分钟缓存),
  这是**刻意的口径**(非交易时段没有"实时"可言)
- ⚠️ 报价快照只覆盖"自选 ∪ 持仓";其它代码(如详情页临时查一只)仍走 REST
- ⚠️ 东财能力(北向资金 / 真实板块 K 线 / 个股→行业映射)**尚未封装**:
  实测 `datacenter-web` 可用但 `push2` 突发即被限流,属机会性依赖,
  需要时按"不带 ut + 低频 + 连通性门禁"单独封装(见 `docs/v0.5-roadmap.md`)

## 六、验收

- 后端:全量 `pytest` 0 failed(基线 1742 → 1760);架构边界测试通过
- 后端:`/api/quotes/stream` 首帧 + 增量 + 心跳实测正常(真实 uvicorn + 真实新浪,
  增量帧每 **2.0s** 一拍)
- 前端:`tsc` 0 错误、`next build` 绿
- 前端真机(Chromium,2026-10-29 收盘后用**可控行情源**在网络边界制造价格变化,
  生产代码零改动):
  - **端到端时延**:独立客户端实测服务端帧间隔 **2.001s**;浏览器原生 EventSource 探针
    自测帧龄 **1–2ms**;应用 DOM 显示的帧号 = 快照时刻的最新帧(与原生页**对照法**测得
    差值 ≈ 0)→ 端到端 ≤3s 成立
  - **降级**:SSE 被断开(`net::ERR_EMPTY_RESPONSE`)→ 连续 3 次失败后自动切 REST 轮询
    (每 **3s**,`fresh=true` 跳过 5 分钟缓存);后端恢复后 **1.7s** 内自动回切 SSE,
    轮询随即停止
  - **console**:零 error / 零 warn
- 验收中发现并修掉两个前端缺陷(均已回归验证):
  1. 降级时 `close()` 掉 EventSource → 降级变成**不可逆闩锁**(一次后端重启,整个会话
     都回不到 SSE);改为保留 EventSource,靠浏览器自动重连回切
  2. 页面刷新后若带着降级标记就**不再建立 SSE** → 同样回不来;改为标记只决定
     "要不要同时开 REST 兜底",不决定"要不要连流"

## 参考

- `ADR-0005-quote-source-and-stock-code.md`(主备源决策,依然有效)
- `plans/backend-architecture.md` §5.4 / §5.8(akshare 章节 → 已评估不采用)
- PyPI `akshare` 元数据(1.20.2,2026-10-28);akshare 源码 `ut` 令牌统计
