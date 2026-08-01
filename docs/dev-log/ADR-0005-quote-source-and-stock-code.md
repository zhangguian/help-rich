# ADR-0005: 行情数据源用新浪主 + 腾讯备;stock_code 统一带市场后缀

## 状态
已采纳(2026-08-01,P3.5)

## 背景

P3.5(股票选择 + 行情)按 `backend-arch §5.4` 的规划,MVP 用**东财原生 HTTP**(`eastmoney.py`)做实时行情,akshare 做全市场列表。实测发现:

1. **东财 push2his.eastmoney.com 被公司网络限流**:首次请求成功,后续全部 `Remote end closed connection`(curl / httpx / urllib 三种客户端、多次重试均失败,0.15s 即断连)
2. **akshare 底层也走东财**(`stock_zh_a_spot_em` 就是调 push2 系列),同样被限流
3. **新浪 `hq.sinajs.cn` 与腾讯 `qt.gtimg.cn` 实测稳定可用**(200 OK,GBK 编码,字段完整)

同时,`data-source-guide §1.1` 规定项目统一内部格式为 `600519.SH` 风格,但 DB 的 `stock_code` 字段一直是纯 6 位数字(旧 schema `min_length=6, max_length=6`),导致行情(需要市场后缀才能映射 sh/sz 前缀)无法关联持仓。

## 决策

1. **实时行情:新浪为主,腾讯为备**(`app/data/sina.py` + `app/data/tencent.py`),`QuoteService`(服务层)按 主→备 降级,5 分钟 JSON 缓存(原子写)。东财客户端不写(在受限网络下不可用,且新浪/腾讯已覆盖需求)。
2. **全市场列表:暂不实现**。MVP 的股票输入只需要 6 位代码 + 名称,`normalize_code()` 按前缀推断市场,不需要全市场列表。akshare 已装,留作后续功能。
3. **stock_code 统一为带后缀格式**:新增 `app/core/stock_code.py` 的 `normalize_code()`,schema 校验时规范化(接受 `600519` / `600519.SH` / `sh600519`);启动时 `db_migrations.py` 幂等迁移存量数据(纯 6 位 → 补后缀)。

市场推断规则(6/9→SH,0/1/2/3→SZ,4/8→BJ)。

## 后果

- ✅ 行情 API 在受限网络下可用,持仓今日盈亏/浮动盈亏端到端打通
- ✅ `normalize_code` 一处定义,录入/筛选/行情全链路复用
- ✅ 迁移幂等,重复启动无副作用
- ⚠️ 东财(字段最全,K 线等)后续在不受限网络下可重新加入,DataSource 抽象已预留
- ⚠️ `phase-completion-log` 注记:akshare 装包成功但运行时受限,非 P3.5 验收的阻塞项

## 参考

- `plans/data-source-guide.md` §1.1(代码格式)/ §1.2(新浪字段)
- `plans/backend-architecture.md` §5.4(akshare)/ §5.5(UnifiedQuote)/ §5.6(缓存)
- 实测记录:新浪/腾讯 curl 200,东财 0.15s 断连
