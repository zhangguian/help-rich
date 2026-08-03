# ETF 改造方案(RFC v0.6)

> **状态**:待评审
> **作者**:产品 + 技术联合
> **目标版本**:v0.6
> **预计工时**:1-1.5 天

---

## 1. 背景

当前项目对**场内 ETF** 已经有数据通路(行情、K 线、AI 解读都跑得通),但**没有为 ETF 优化用户体验**:

- 用户在自选/持仓列表看到 ETF,无法一眼识别
- 切到 ETF 时,行业归属返回 null(ETF 不在 baostock 离线行业表里)
- 三线叠加(个股/大盘/行业)对 ETF 无效,行业线为空
- 用户问"这只 ETF 跟踪什么指数"无法得到回答

**场外基金**(001511 这类)暂不在本次范围,作为 v0.7 计划项。

## 2. 目标

为场内 ETF 用户提供**最小可用**的体验升级:

| 目标 | 验收 |
|---|---|
| 用户一眼看出"这是 ETF" | 自选 / 持仓列表显示 `📊 ETF` 徽章 |
| 切到 ETF 时知道它跟踪什么 | AnalysisPanel 显示"跟踪 X 指数" |
| 行业归属对 ETF 有意义 | `resolve_industry` 返回 `source=etf_index` |
| 不破坏现有股票逻辑 | baostock 命中的股票行业保持不变 |

## 3. 范围

### 3.1 在范围内(P0)

- 新增 `etf_index.json` 静态表(覆盖 5 大类 ~40 只主流 ETF)
- 后端 `resolve_industry` 加 ETF 兜底分支(优先级:baostock → 新浪 → ETF 跟踪指数 → degrade)
- 前端 `isEtf` 辅助函数 + 自选/持仓 `📊 ETF` 徽章
- AnalysisPanel 显示跟踪指数(当 `source='etf_index'`)
- 文档说明 + 后端测试

### 3.2 不在范围内(后续版本)

| 项 | 计划版本 | 备注 |
|---|---|---|
| 场外基金(001511) | v0.7 | 需 .OF 后缀 + 新数据源(天天基金/东财) |
| ETF 持仓股反查(10 大权重) | v0.7 | 数据源 `fundf10.eastmoney.com FundArchivesDatas` |
| 三线叠加补 ETF 指数对比 | v0.7 | 需 `index_code → K 线 secid` 映射 |
| 动态 ETF 列表同步脚本 | v0.7 | 一次性同步,后续增量 |
| 完整 ETF 详情页(规模/费率/折溢价) | v0.8 | 数据源 `fundmobapi.eastmoney.com FundMNFInfo` |

## 4. 现状盘点

### 4.1 场内 ETF 已能工作

| 能力 | 状态 | 备注 |
|---|---|---|
| 自选 / 持仓入库 | ✅ | `stock_code` 字段无类型限制 |
| 实时行情 | ✅ | `SinaClient` / `TencentClient` 已支持(实测 159599.SZ / 501099.SH / 588160.SH) |
| K 线 | ✅ | `KlineCache` 按 stock_code 缓存,新浪/腾讯都能取 |
| 持仓盈亏计算 | ✅ | `shares × current_price` 公式通用 |
| AI 解读(LLM) | ✅ | chat endpoint 不区分股票/ETF |
| 三线叠加 | ⚠️ | 个股/大盘 OK,行业线空(没行业归属) |
| `resolve_industry` | ⚠️ | ETF 返回 `degrade`,UI 显示空白 |

### 4.2 关键代码位置

| 模块 | 文件 | 备注 |
|---|---|---|
| 代码规范化 | `backend/app/core/stock_code.py` | 5→SH / 1→SZ 已支持 ETF |
| 行业兜底 | `backend/app/services/industry_service.py` | 三级兜底,本次加第 4 级 |
| 行业离线表 | `backend/app/data/industry_map.json` | 5536 只股票,不含 ETF |
| 三线叠加 | `backend/app/services/overview_service.py` | `industry` 为空时 sector 数组为空 |
| 前端代码规则 | `frontend/src/lib/stockCode.ts` | 镜像后端规则 |
| 自选 UI | `frontend/src/components/watch/WatchList.tsx` | 加 ETF 徽章 |
| 持仓 UI | `frontend/src/components/positions/PositionSummaryTable.tsx` | 加 ETF 徽章 |
| 分析面板 | `frontend/src/components/advice/AnalysisPanel.tsx` | 显示跟踪指数 |

## 5. 改造方案

### 5.1 新增 ETF 跟踪指数静态表

**文件**:`backend/app/data/etf_index.json`(新建)

**结构**:
```json
{
  "version": "2026-08-03",
  "source": "manual + eastmoney fundmobapi 校验;覆盖 5 大类约 40 只主流 ETF",
  "items": [
    {"code": "510050.SH", "index": "上证 50",       "category": "broad"},
    {"code": "510300.SH", "index": "沪深 300",      "category": "broad"},
    {"code": "510500.SH", "index": "中证 500",      "category": "broad"},
    {"code": "159915.SZ", "index": "创业板指",      "category": "broad"},
    {"code": "588000.SH", "index": "科创 50",       "category": "broad"},
    {"code": "588080.SH", "index": "科创 50",       "category": "broad"},

    {"code": "512480.SH", "index": "国证半导体芯片",  "category": "industry"},
    {"code": "515790.SH", "index": "中证光伏产业",   "category": "industry"},
    {"code": "512760.SH", "index": "国证芯片",       "category": "industry"},
    {"code": "159995.SZ", "index": "国证半导体芯片",  "category": "industry"},
    {"code": "512660.SH", "index": "中证军工",        "category": "industry"},
    {"code": "159825.SZ", "index": "中证农业",        "category": "industry"},
    {"code": "515030.SH", "index": "中证新能源车",    "category": "industry"},
    {"code": "159806.SZ", "index": "中证新能源车",    "category": "industry"},
    {"code": "512170.SH", "index": "中证医疗",        "category": "industry"},
    {"code": "159992.SZ", "index": "中证创新药",      "category": "industry"},
    {"code": "159801.SZ", "index": "中证芯片",        "category": "industry"},
    {"code": "512880.SH", "index": "中证证券",        "category": "industry"},
    {"code": "512000.SH", "index": "中证全指证券公司","category": "industry"},
    {"code": "515220.SH", "index": "中证煤炭",        "category": "industry"},
    {"code": "515210.SH", "index": "中证钢铁",        "category": "industry"},
    {"code": "516970.SH", "index": "中证基建",        "category": "industry"},
    {"code": "159996.SZ", "index": "中证家居家电",    "category": "industry"},

    {"code": "513050.SH", "index": "中概互联",        "category": "qdii"},
    {"code": "513100.SH", "index": "纳斯达克 100",    "category": "qdii"},
    {"code": "513300.SH", "index": "纳斯达克 100",    "category": "qdii"},
    {"code": "513500.SH", "index": "标普 500",        "category": "qdii"},
    {"code": "513880.SH", "index": "日经 225",        "category": "qdii"},
    {"code": "513730.SH", "index": "东南亚科技",      "category": "qdii"},
    {"code": "159941.SZ", "index": "纳斯达克 100",    "category": "qdii"},
    {"code": "513870.SH", "index": "纳斯达克科技",    "category": "qdii"},

    {"code": "518880.SH", "index": "黄金现货",        "category": "commodity"},
    {"code": "518800.SH", "index": "黄金 9999",       "category": "commodity"},
    {"code": "162411.SZ", "index": "标普石油",        "category": "commodity"},
    {"code": "501018.SH", "index": "原油",            "category": "commodity"},
    {"code": "160723.SZ", "index": "嘉实原油",        "category": "commodity"},
    {"code": "160216.SZ", "index": "国泰商品",        "category": "commodity"},

    {"code": "511010.SH", "index": "上证 5 年国债",   "category": "bond"},
    {"code": "511260.SH", "index": "上证 10 年国债",  "category": "bond"},
    {"code": "511880.SH", "index": "银华日利",        "category": "money"},
    {"code": "511990.SH", "index": "华宝添益",        "category": "money"}
  ]
}
```

**5 大类覆盖**:
- **broad**(宽基):6 只 — 上证 50/沪深 300/中证 500/创业板/科创 50
- **industry**(行业/主题):~21 只 — 半导体/光伏/军工/农业/新能源车/医疗/创新药/证券/煤炭/钢铁/基建/家居家电/传媒
- **qdii**(QDII/跨境):~8 只 — 中概/纳指/标普 500/日经 225/东南亚科技
- **commodity**(商品):6 只 — 黄金/原油/石油
- **bond/money**(债券/货币):4 只 — 国债/货币基金

**刷新策略**:
- v0.6 手工维护
- v0.7 跑一次性脚本从 `fundmobapi.eastmoney.com FundMNFInfo?Fcodes=...` 增量同步
- 年度维护成本:< 5 只新增

### 5.2 后端 `resolve_industry` 升级

**优先级**(四级兜底):
1. **baostock** 离线行业表(已有,~5000 只股票)
2. **新浪** 行业排行领涨反查(已有)
3. **🆕 ETF 跟踪指数**(`etf_index.json` 静态表,本 RFC 重点)
4. **degrade**(已有)

**关键改动** `backend/app/services/industry_service.py`:

```python
import json
from pathlib import Path

_ETF_INDEX_PATH = Path(__file__).resolve().parents[1] / "data" / "etf_index.json"
_etf_index_cache: dict[str, dict] | None = None

# 5 大类中文映射
_CATEGORY_LABEL = {
    "broad": "宽基",
    "industry": "行业",
    "qdii": "QDII",
    "commodity": "商品",
    "bond": "债券",
    "money": "货币",
}


def _load_etf_index() -> dict[str, dict]:
    """code → {code, index, category};启动时一次性加载,后续命中内存"""
    global _etf_index_cache
    if _etf_index_cache is None:
        try:
            with open(_ETF_INDEX_PATH, encoding="utf-8") as f:
                data = json.load(f)
            _etf_index_cache = {item["code"]: item for item in data["items"]}
        except FileNotFoundError:
            logger.warning("etf_index.json 不存在,ETF 行业兜底失效")
            _etf_index_cache = {}
    return _etf_index_cache


def _resolve_etf_index(code: str) -> dict | None:
    """ETF 跟踪指数兜底;未命中返回 None"""
    return _load_etf_index().get(code)


async def resolve_industry(code: str) -> dict:
    """四级兜底:baostock → 新浪 → ETF 跟踪指数 → degrade"""
    name = _resolve_local(code)
    if name:
        return {"code": code, "industry": name, "source": "baostock", "note": None}

    name = await _resolve_sina(code)
    if name:
        return {
            "code": code,
            "industry": name,
            "source": "sina",
            "note": "新浪行业排行领涨股命中(离线表未覆盖)",
        }

    etf = _resolve_etf_index(code)
    if etf:
        cat_label = _CATEGORY_LABEL.get(etf["category"], "其他")
        return {
            "code": code,
            "industry": f"跟踪{etf['index']}",
            "source": "etf_index",
            "note": f"场内 ETF · {cat_label}",
        }

    return {
        "code": code,
        "industry": None,
        "source": "degrade",
        "note": "未能识别行业归属,可能是新股/小盘股/非主流品种",
    }
```

**返回示例**:
```json
{
  "code": "510050.SH",
  "industry": "跟踪上证 50",
  "source": "etf_index",
  "note": "场内 ETF · 宽基"
}
```

### 5.3 前端 `isEtf` 辅助函数

**`frontend/src/lib/stockCode.ts`** 新增:

```ts
/** 场内 ETF:5xxxxx.SH(51/56/58 系列)或 1xxxxx.SZ(15/16 系列)
 *  与后端 etf_index.json 覆盖范围不同 — 此函数仅做"代码格式"识别,
 *  实际跟踪指数展示以后端 resolve_industry 的 industry 字段为准 */
export function isEtf(code: string): boolean {
  const c = code.toUpperCase();
  if (c.endsWith('.SH')) return /^5\d{5}\.SH$/.test(c);
  if (c.endsWith('.SZ')) return /^1\d{5}\.SZ$/.test(c);
  return false;
}
```

### 5.4 前端 ETF 徽章

**`frontend/src/components/watch/WatchList.tsx`** (~line 132):
```tsx
<div className="flex items-center gap-1.5">
  <span className="text-sm text-text-pri truncate">
    {it.name ?? it.code}
  </span>
  {isEtf(it.code) && (
    <span
      className="text-[10px] px-1 py-px rounded bg-amber-500/15 text-amber-300 border border-amber-500/30 shrink-0"
      title="场内 ETF · 基金"
    >
      ETF
    </span>
  )}
  {it.inPosition && (
    <span className="text-[10px] px-1 py-px rounded bg-accent-subtle text-accent border border-accent/30">
      持仓
    </span>
  )}
</div>
```

**`frontend/src/components/positions/PositionSummaryTable.tsx`** (line 86 附近):
```tsx
<td className="py-2 px-2">
  <div className="flex items-center gap-1.5">
    <div className="text-text-pri font-semibold font-sans truncate max-w-[10rem]">
      {p.stockName ?? p.stockCode}
    </div>
    {isEtf(p.stockCode) && (
      <span className="text-[10px] px-1 py-px rounded bg-amber-500/15 text-amber-300 border border-amber-500/30 shrink-0">
        ETF
      </span>
    )}
  </div>
  <div className="text-text-ter text-xs">{p.stockCode}</div>
</td>
```

### 5.5 AnalysisPanel 显示跟踪指数

**`frontend/src/components/advice/AnalysisPanel.tsx`** 行业显示位置:

```tsx
{ind.industry && (
  <div className="flex items-center gap-2 flex-wrap">
    <span className="text-xs text-text-ter">行业</span>
    <span
      className={clsx(
        'text-xs px-2 py-0.5 rounded border',
        ind.industrySource === 'etf_index'
          ? 'bg-amber-500/10 text-amber-300 border-amber-500/30'
          : 'bg-white/5 text-text-sec border-white/10',
      )}
    >
      {ind.industry}
    </span>
    {ind.industrySource === 'etf_index' && ind.note && (
      <span className="text-[10px] text-text-ter">{ind.note}</span>
    )}
  </div>
)}
```

### 5.6 后端测试

**`backend/tests/test_industry_service.py`** 新增 `TestEtfIndex` 类:

```python
class TestEtfIndex:
    """ETF 跟踪指数兜底分支(优先级介于新浪与 degrade 之间)"""

    async def test_mainstream_broad_etf_returns_tracking_index(self):
        """510050(上证 50ETF)→ 跟踪上证 50,note 含 '宽基'"""
        r = await resolve_industry("510050.SH")
        assert r["source"] == "etf_index"
        assert r["industry"] == "跟踪上证 50"
        assert "宽基" in r["note"]

    async def test_sz_market_etf(self):
        """159915(创业板 ETF)→ 跟踪创业板指,source=etf_index"""
        r = await resolve_industry("159915.SZ")
        assert r["source"] == "etf_index"
        assert r["industry"] == "跟踪创业板指"

    async def test_industry_etf_category_label(self):
        """512480(半导体 ETF)→ note 含 '行业'"""
        r = await resolve_industry("512480.SH")
        assert r["source"] == "etf_index"
        assert "行业" in r["note"]

    async def test_qdii_etf_category_label(self):
        """513050(中概互联)→ note 含 'QDII'"""
        r = await resolve_industry("513050.SH")
        assert r["source"] == "etf_index"
        assert "QDII" in r["note"]

    async def test_commodity_etf_category_label(self):
        """518880(黄金 ETF)→ note 含 '商品'"""
        r = await resolve_industry("518880.SH")
        assert r["source"] == "etf_index"
        assert "商品" in r["note"]

    async def test_unknown_etf_falls_to_degrade(self):
        """511999.SH(假设不在表内)→ industry=None, source='degrade'"""
        r = await resolve_industry("511999.SH")
        assert r["industry"] is None
        assert r["source"] == "degrade"

    async def test_stock_not_affected(self):
        """600519(茅台) 走 baostock,不被 ETF 路径影响"""
        r = await resolve_industry("600519.SH")
        assert r["source"] == "baostock"
        assert r["industry"]  # 非空
```

## 6. 实施步骤(执行顺序)

| 顺序 | 任务 | 文件 | 工时 |
|---|---|---|---|
| 1 | 新增 ETF 跟踪指数静态表 | `backend/app/data/etf_index.json` | 0.5h |
| 2 | 后端 `resolve_industry` 加 ETF 兜底分支 | `backend/app/services/industry_service.py` | 0.5h |
| 3 | 后端测试 | `backend/tests/test_industry_service.py` | 0.5h |
| 4 | 前端 `isEtf` helper | `frontend/src/lib/stockCode.ts` | 10min |
| 5 | 自选 ETF 徽章 | `frontend/src/components/watch/WatchList.tsx` | 20min |
| 6 | 持仓 ETF 徽章 | `frontend/src/components/positions/PositionSummaryTable.tsx` | 20min |
| 7 | AnalysisPanel 跟踪指数显示 | `frontend/src/components/advice/AnalysisPanel.tsx` | 0.5h |
| 8 | 文档说明 | `docs/release-notes.md` | 10min |
| 9 | 回归测试 + typecheck + build | - | 0.5h |

**总工时**:~3-3.5h(约半天到 1 天)

## 7. 验收标准

### 7.1 自动测试

```bash
cd backend
.venv\Scripts\python.exe -m pytest tests/test_industry_service.py -q
# 预期:原 7 + 新 7 = 14 passed

cd ../frontend
npm run typecheck && npm run build
# 预期:无错
```

### 7.2 手动验证

| 场景 | 操作 | 预期 |
|---|---|---|
| ETF 徽章显示 | 自选加 `510050.SH` | 列表显示 `📊 ETF` 徽章 |
| ETF 跟踪指数 | 切到 510050 → AnalysisPanel | 行业 chip 显示"跟踪上证 50"(amber 配色) + note "场内 ETF · 宽基" |
| 普通股票不受影响 | 切到 `600519.SH` | 行业 chip 显示"白酒"(原配色) |
| 非主流 ETF 兜底 | 切到 `511999.SH`(不在表) | 行业为空,不报错 |
| 深市 ETF | 切到 `159915.SZ` | 显示"跟踪创业板指",note"场内 ETF · 宽基" |
| 行业 ETF | 切到 `512480.SH` | 显示"跟踪国证半导体芯片",note"场内 ETF · 行业" |
| K 线 | ETF 周期切换 | 正常显示 |

## 8. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| ETF 跟踪指数会变(基金转型) | 低 | 中 | 静态表 + `version` 字段,年度更新 |
| 新 ETF 持续新增 | 高 | 低 | v0.6 40 只够用,v0.7 接自动同步 |
| 跟踪指数名和实际有出入(分级基金) | 中 | 中 | 文档注明"以基金公司公告为准";note 文案可发现 |
| `etf_index.json` 加载失败 | 极低 | 中 | try/except + 降级到空 cache,不抛错 |
| 前端 ETF 徽章颜色与持仓徽章混淆 | 中 | 低 | amber 配色 vs accent 配色,加 hover title |
| 分类与实际不符 | 中 | 低 | v0.6 手工校验,v0.7 接自动数据校验 |

## 9. 后续计划(v0.7+)

| 项 | 优先级 | 数据源 | 工作量 |
|---|---|---|---|
| 场外基金持仓 | P0 | 天天基金 / 东财 fund.eastmoney.com | 1-2 周 |
| ETF 持仓股反查(10 大权重) | P0 | `fundf10.eastmoney.com FundArchivesDatas` | 2-3 天 |
| 三线叠加补 ETF 指数对比 | P1 | 静态表 `index_code → secid` | 1 天 |
| ETF 动态同步脚本 | P1 | `fundmobapi.eastmoney.com FundMNFInfo` | 1-2 天 |
| ETF 完整详情页(规模/费率/折溢价) | P2 | 同上 | 3-5 天 |
| ETF 跨市场套利监控(IOPV) | P3 | 实时 IOPV 数据源 | 1-2 周 |

## 10. 附录

### 10.1 数据源参考

| 数据源 | URL | 用途 | 备注 |
|---|---|---|---|
| 场内 ETF 行情 | `https://hq.sinajs.cn/list=sh510050` | 实时报价 | 已有,Sina/Tencent |
| 场内 ETF K 线 | `https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=1.510050&klt=101` | 历史 K 线 | 已有,通过 Sina fallback |
| 场外净值 | `https://hq.sinajs.cn/rn={ts}&list=f_{基金代码}` | 场外基金净值 | 需 Referer,GBK,v0.7 |
| 场外实时估值 | `https://fundgz.1234567.com.cn/js/{基金代码}.js` | 场外基金估值 | JSONP,v0.7 |
| 历史净值 | `https://fund.eastmoney.com/pingzhongdata/{基金代码}.js` | 场外净值曲线 | JS 文本 + 正则,v0.7 |
| 基本信息 | `https://fundmobapi.eastmoney.com/FundMNewApi/FundMNFInfo?Fcodes={代码}` | 基金详情 | v0.7 |
| 十大持仓 | `https://fundf10.eastmoney.com/FundArchivesDatas.aspx?type=jjcc&code={代码}` | ETF 持仓股 | v0.7 |
| 基金排行 | `https://fund.eastmoney.com/data/rankhandler.aspx` | 排行 | v0.7 |

### 10.2 ETF 代码前缀规则

| 前缀 | 市场 | 类型 | 说明 |
|---|---|---|---|
| 50xxxx | SH | 跨境/QDII/商品 | 510050(上证 50)是例外,其他多为跨境 |
| 51xxxx | SH | 宽基/行业/债券 | 510300(沪深 300)/ 511010(国债 5 年) |
| 56xxxx | SH | 行业/主题 | 56xxxx 系列 |
| 58xxxx | SH | 行业/主题 | 588000(科创 50)/ 588080 等 |
| 15xxxx | SZ | 宽基/行业/主题 | 159915(创业板)/ 159995(芯片) |
| 16xxxx | SZ | 行业/主题/商品 | 162411(石油)/ 161725 等 |

### 10.3 关键决策记录

- **Decision 1**:静态表而非实时查询
  - 原因:ETF 跟踪指数变化极慢(基金转型才变),40 只硬编码够用;实时查询 `FundMNFInfo` 增加请求量和复杂度
  - 后续:v0.7 一次性同步脚本
- **Decision 2**:不修改 Position / Watchlist 数据模型
  - 原因:`stock_code` 字段已能容纳 ETF;`shares` 是整数,场内 ETF 100 整数倍,无需改
  - 后续:场外基金再考虑 `Decimal` 化
- **Decision 3**:`industry` 字段返回 `"跟踪{指数}"` 而非仅 `"{指数}"`
  - 原因:让用户立刻知道这是"跟踪"语义,区别于 baostock 的"行业归属"
  - 前端用 amber 配色进一步强化视觉
- **Decision 4**:不实现三线叠加对 ETF 的支持
  - 原因:需要 `index_code → secid` 映射,工作量大;v0.6 聚焦最小可用
  - 后续:v0.7 加

---

**评审要点**:
- [ ] ETF 列表覆盖范围是否足够(可补充具体代码)
- [ ] `industry` 字段返回 `"跟踪{指数}"` 还是 `"{指数}"`?
- [ ] ETF 徽章颜色(amber)是否合适?
- [ ] 是否同时改 `PositionDetailModal`(如存在)?
- [ ] 文档措辞是否清晰?
