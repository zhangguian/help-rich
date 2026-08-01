# 股票数据获取指南(供 Python 项目参考)

> 本文档整理自 go-stock 项目(Go)实际使用的所有数据获取方式,供 Python 项目直接复用。
> 重点:**从哪拉、怎么拉、返回什么、有什么坑**。均为公开 HTTP 接口,Python 用 `requests` 即可调用。
> 最后更新:2026-08-01

---

## 0. 数据源速查表

| 需要的数据 | 推荐数据源 | 难度 | 说明 |
|---|---|---|---|
| 实时行情(个股/指数) | 新浪 `hq.sinajs.cn` | ★☆☆ | 最稳定,免费无鉴权,需 Referer |
| 实时行情(备用) | 腾讯 `qt.gtimg.cn` | ★☆☆ | GBK 编码,字段更全(含五档) |
| K 线(日/周/月/分钟) | 东方财富 `push2his.eastmoney.com` | ★☆☆ | JSON 直出,推荐首选 |
| K 线(备用) | 新浪 `quotes.sina.cn` | ★★☆ | JSONP 格式,需剥壳 |
| 分时数据 | 腾讯 `web.ifzq.gtimg.cn` | ★☆☆ | JSON |
| 全市场股票列表 | 东财 `push2.eastmoney.com/api/qt/clist/get` | ★★☆ | 分页,字段为数字码 |
| 财务数据(F10) | 东财 `datacenter.eastmoney.com` | ★★☆ | reportName 模式 |
| 资金流向 | 新浪 `vip.stock.finance.sina.com.cn` | ★☆☆ | 板块/个股/趋势三种 |
| 龙虎榜/宏观数据 | 东财 `datacenter-web.eastmoney.com` | ★★☆ | reportName 模式 |
| 公告/研报 | 东财 `reportapi.eastmoney.com` 等 | ★★☆ | 三个不同 host |
| 财联社电报 | 网页 `www.cls.cn/telegraph` | ★★★ | API 需 sign 签名,建议爬页面 |
| 新闻(快讯) | 新浪 7x24 / 华尔街见闻 | ★★☆ | 新浪简单,见闻 API 需 UA |
| 热门股/事件 | 雪球 | ★★★ | 需要 cookie,会反爬 |
| 节假日/交易日 | `timor.tech` | ★☆☆ | 免费公开 JSON,强烈推荐 |
| 基金净值/估值 | 新浪 + 天天基金 | ★☆☆ | 场外/场内分开 |
| 美股/港股 | 新浪(行情页爬取) | ★★☆ | 无免费 JSON,需爬 HTML |
| 问财智能选股 | `openapi.iwencai.com` | ★★★ | 需密钥 + 加密请求体 |

---

## 0.1 对应 Go 实现文件索引

需要看本项目 Go 源码里的解析/降级细节时,按数据源查表(`backend/data/` 目录):

| 数据源 | Go 文件 |
|---|---|
| 新浪/腾讯实时、腾讯 K线/分时、东财 clist 全市场、港股列表 | `stock_data_api.go` |
| 新浪 K 线(JSONP) | `sina_kline_api.go` |
| 东财 K 线 | `eastmoney_kline_api.go` |
| 东财 F10 / 数据中心 / 公告 / 研报 / 龙虎榜 | `f10_data_api.go`、`market_news_api.go`(datacenter-web 系) |
| 东财 AI SaaS(研报写作/问答/热搜) | `eastmoney_api.go` |
| 财联社、雪球、新浪资金流、快讯、TradingView 新闻、涨停复盘 | `market_news_api.go` |
| 华尔街见闻 | `wallstreetcn_api.go` |
| 问财 | `iwencai_api.go` |
| 基金(净值/估值/排行/持仓) | `fund_data_api.go`、`fund_kline_api.go` |
| 节假日(timor.tech) | `tool_agent_extra.go`、`tool_agent_parity.go` |
| 涨停异动(push2ex) | `stock_changes_api.go` |

---

## 1. 代码格式约定

### 1.1 股票代码格式

各数据源对代码格式要求不同,统一转换规则:

| 格式示例 | 含义 | 适用数据源 |
|---|---|---|
| `sh600000` / `sz000001` / `bj430300` | 带市场前缀小写 | 新浪、腾讯 |
| `600519.SH` / `000001.SZ` / `830799.BJ` | 带点号大写 | 通达信、本项目的统一内部格式 |
| `1.600519` / `0.000001` / `0.830799` | **secid**(市场码.代码) | 东方财富全部接口 |
| `128.00700` | secid 港股 | 东方财富 |
| `90.BK0475` | secid 板块 | 东方财富 |
| `hk00700` / `gb_aapl` | 港股/美股 | 新浪 |

### 1.2 secid 市场码对照(东财专用)

```
上海 → 1.xxx     深圳 → 0.xxx     北京 → 0.xxx
港股 → 128.xxx   板块 → 90.xxx    美股 → 105/106/107.xxx
```

### 1.3 K 线周期编码对照

| 东财 klt | 新浪 scale | 周期 |
|---|---|---|
| 1 | 1 | 1 分钟 |
| 5 | 5 | 5 分钟 |
| 15 | 15 | 15 分钟 |
| 30 | 30 | 30 分钟 |
| 60 | 60 | 60 分钟 |
| 101 | 240 | 日 K |
| 102 | 1200 | 周 K |
| 103 | — | 月 K |

---

## 2. 实时行情(推荐新浪)

### 2.1 新浪(首选)

```
GET https://hq.sinajs.cn/rn={时间戳}&list={代码列表,逗号分隔}
```

**必带请求头**:`Referer: https://finance.sina.com.cn`(不带会被 403)。

返回为 GBK 编码文本,格式:

```
var hq_str_sh600000="浦发银行,10.500,10.490,10.520,10.550,10.480,...,2026-08-01,15:00:00,00,";
```

逗号分隔字段(标准 A 股):

| 索引 | 含义 |
|---|---|
| 0 | 股票名称 |
| 1 | 今开 |
| 2 | 昨收 |
| 3 | 现价 |
| 4 | 最高 |
| 5 | 最低 |
| 6-7 | 竞买/竞卖价 |
| 8-19 | 买一到买五(价,量 × 5 组) |
| 20-29 | 卖一到卖五(价,量 × 5 组) |
| 30 | 成交股数 |
| 31 | 成交金额 |
| 32 | 日期 |
| 33 | 时间 |

**指数**:代码用 `s_sh000001`(上证)、`s_sz399001`(深证)、`s_sz399006`(创业板),格式为 `var hq_str_s_sh000001="上证指数,3456.78,...";` 名称+数值序列。

**涨跌家数**:`list=s_sh_updn` → 返回格式 `var hq_str_s_sh_updn="1,3360,1684,..."`(第 1 个字段为涨/跌标记,后续为上涨家数、下跌家数等)。

**场外基金净值**:`list=f_000001`(f_ 前缀)。
**场外基金估值**:`list=fu_000001`(fu_ 前缀)。

Python 示例:

```python
import requests

def sina_realtime(codes: list[str]) -> str:
    """codes 例: ['sh600000', 'sz000001']"""
    url = f"https://hq.sinajs.cn/rn={int(__import__('time').time()*1000)}&list={','.join(codes)}"
    resp = requests.get(url, headers={"Referer": "https://finance.sina.com.cn",
                                       "User-Agent": "Mozilla/5.0"})
    resp.encoding = "gb18030"          # 关键:GBK 解码
    return resp.text                    # 每行 var hq_str_xxx="...";
```

### 2.2 腾讯(备用,字段更全)

```
GET https://qt.gtimg.cn/?_={时间戳}&q={代码列表,逗号分隔}
```

返回 GBK 编码,格式 `v_sh600000="1~浦发银行~600000~10.52~10.49~...";`,字段用 `~` 分隔:

| 索引 | 含义 |
|---|---|
| 0 | 未知(固定 1) |
| 1 | 股票名称 |
| 2 | 股票代码 |
| 3 | 现价 |
| 4 | 昨收 |
| 5 | 今开 |
| 6 | 成交量(手) |
| 7 | 外盘 |
| 8 | 内盘 |
| 9-18 | 买一~买五(价,量) |
| 19-28 | 卖一~卖五(价,量) |
| 30 | 时间 |
| 31 | 涨跌额 |
| 32 | 涨跌幅% |
| 33 | 最高 |
| 34 | 最低 |
| 35 | 价格/成交量/成交额 |
| 36 | 成交量 |
| 37 | 成交额(万) |
| 38 | 换手率 |
| 39 | 市盈率 |
| 43 | 振幅 |
| 44 | 流通市值(亿) |
| 45 | 总市值(亿) |
| 46 | 市净率 |

---

## 3. K 线数据

### 3.1 东方财富(首选,JSON 直出)

```
GET https://push2his.eastmoney.com/api/qt/stock/kline/get
     ?secid={secid}         # 如 1.600519
     &klt={周期}            # 101日 102周 103月 1/5/15/30/60分钟
     &fqt={复权}            # 0=不复权 1=前复权 2=后复权
     &end=20500101          # 截止日期,20500101 表示最新
     &lmt={数量}            # 返回条数
     &fields1=f1,f2,f3,f4,f5,f6
     &fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f116
```

返回 JSON:

```json
{
  "rc": 0, "data": {
    "code": "600519", "name": "贵州茅台",
    "klines": [
      "2026-07-01,1500.00,1520.00,1530.00,1495.00,28000,4200000000.00,2.33,1.20,20.00,0.35,..."
    ]
  }
}
```

`klines` 每行是逗号分隔字符串,与 fields2 对应:

| 字段 | 含义 | 字段 | 含义 |
|---|---|---|---|
| f51 | 日期/时间 | f52 | 开盘 |
| f53 | 收盘 | f54 | 最高 |
| f55 | 最低 | f56 | 成交量(手) |
| f57 | 成交额(元) | f58 | 振幅% |
| f59 | 涨跌幅% | f60 | 涨跌额 |
| f61 | 换手率% | f116 | 总市值 |

> 若要复权价(前复权),`fqt=1` 且 fields2 追加 `f113,f114,f115`(后复权收盘/前复权收盘/复权因子)。

Python 示例:

```python
import requests

def em_kline(secid: str, klt: str = "101", limit: int = 500, fqt: str = "0") -> list[dict]:
    params = {
        "secid": secid, "klt": klt, "fqt": fqt,
        "end": "20500101", "lmt": limit,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f116",
        "_": str(int(__import__('time').time() * 1000)),
    }
    r = requests.get("https://push2his.eastmoney.com/api/qt/stock/kline/get",
                     params=params, headers={"User-Agent": "Mozilla/5.0"})
    data = r.json()["data"]
    names = ["date", "open", "close", "high", "low", "volume", "amount",
             "amplitude", "change_pct", "change", "turnover", "total_mv"]
    return [dict(zip(names, row.split(","))) for row in data["klines"]]

print(em_kline("1.600519", limit=5))
```

### 3.2 新浪(备用,JSONP)

```
GET https://quotes.sina.cn/cn/api/jsonp_v2.php/{随机callback}/CN_MarketDataService.getKLineData
     ?symbol={sh600000 格式}
     &scale={周期}     # 240=日 1200=周 1/5/15/30/60=分钟
     &ma=no
     &datalen={数量}   # 最大 1023
```

返回 JSONP:`callback_xxx([{"day":"2026-07-01","open":"1500","high":"1530","low":"1495","close":"1520","volume":"28000"}]);`。
Python 中正则剥掉 `callback_xxx(` 前缀和 `);` 后缀即可。

### 3.3 腾讯(备用,含复权)

```
GET https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sh600000},{周期},{空},{天数},qfq
```

`param` 逗号分隔:代码(小写前缀格式)、周期(`day`日/week周/m1/m5/m15/m30/m60分钟)、空、天数、复权类型(`qfq`前复权)。返回 JSON:

```json
{
  "code": 0, "data": { "sh600000": {
    "qfqday": [["2026-07-01", "10.50", "10.52", "10.55", "10.48", "12000"], "..."]  // 日期 开 收 高 低 量
  }}
}
```

键名随周期/复权变化:日K复权=`qfqday`、日K不复权=`day`、分钟=`m5` 等。

### 3.4 通达信(不推荐 Python 直接实现)

通达信走 gotdx 私有 TCP 协议,需要自己实现协议解析,Python 生态有 `pytdx` 库可以替代,数据源与通达信客户端一致。

---

## 4. 分时数据

```
GET https://web.ifzq.gtimg.cn/appstock/app/minute/query?code={sh600000}
GET https://web.ifzq.gtimg.cn/appstock/app/UsMinute/query?code={美股代码}   # 美股分时
```

返回 JSON:

```json
{
  "code": 0, "data": { "sh600000": {
    "data": {
      "data": ["0930 10.50 1200", "0931 10.51 800", "..."],   // 时间 价格 成交量(手)
      "date": "20260701"
    }
  }}
}
```

---

## 5. 全市场股票列表 / 选股

```
GET https://push2.eastmoney.com/api/qt/clist/get
     ?fs={市场过滤}        # 见下方 fs 常用取值
     &fields=f12,f13,f14,f1,f2,f4,f3,f152,f5,f6,f7,f15,f18,f16,f17,f10,f8,f9,f23,f100,f265
     &fid=f3              # 排序字段(f3=涨跌幅 f62=主力净流入)
     &pn={页码} &pz={每页数,最大100} &po=1 &np=1 &fltt=1&invt=2
```

`fs` 常用取值(逗号分隔多个市场):

```
m:0+t:6+f:!2    深主板      m:0+t:13+f:!2   创业板
m:0+t:80+f:!2   深北交所    m:1+t:2+f:!2    沪主板
m:1+t:23+f:!2   科创板      m:1+t:3+f:!2    沪北交所
```

**字段码对照**(f 开头数字码):

| 字段 | 含义 | 字段 | 含义 |
|---|---|---|---|
| f12 | 代码 | f14 | 名称 |
| f2 | 最新价 | f3 | 涨跌幅% |
| f4 | 涨跌额 | f5 | 成交量(手) |
| f6 | 成交额 | f7 | 振幅% |
| f8 | 换手率% | f9 | 市盈率 |
| f10 | 量比 | f15 | 最高 |
| f16 | 最低 | f17 | 今开 |
| f18 | 昨收 | f20 | 总市值 |
| f21 | 流通市值 | f23 | 市净率 |
| f62 | 主力净流入 | f100 | 行业 |
| f152 | 所属概念 | f265 | 发布时间戳 |

返回 JSON:`{"data": {"total": 5000, "diff": [ {f12: "600519", f14: "贵州茅台", ...} ]}}`。

---

## 6. 财务 / 基本面数据(东财 F10)

```
GET https://datacenter.eastmoney.com/securities/api/data/v1/get
     ?reportName={报表名}
     &columns={字段列表,逗号}
     &filter=(SECUCODE="600519.SH")       # 过滤条件,URL编码
     &pageNumber=1 &pageSize={条数}
     &sortTypes=-1 &sortColumns=REPORT_DATE
     &source=HSF10&client=PC
```

常用 reportName:

| reportName | 内容 |
|---|---|
| `RPT_PCF10_FINANCEMAIN`... | 最新主要财务指标 |
| `RPT_F10_QTR_MAINFINADATA` | 季度主要财务指标 |
| `RPT_HSF10_RES_ORGPREDICT` | 机构盈利预测(EPS/PE) |
| `RPT_HSF10_RESPREDICT_STATISTICS` | 机构预测汇总 |
| `RPT_STOCKVALUATIONTANTILE` | 估值百分位 |
| `RPT_MARGIN_STATISTICS_STOCKS` | 融资融券 |
| `RPT_DATA_BLOCKTRADE` | 大宗交易 |
| `RPT_CUSTOM_DMSK_TREND` | 股东户数趋势 |
| `RPT_BILLBOARD_DAILYDETAILS` | 龙虎榜 |
| `RPT_OPERATEDEPT_TRADE` | 营业部买卖明细 |

> 建议在浏览器打开东财个股 F10 页面(如 `https://emweb.securities.eastmoney.com/pc_hsf10/pages/index.html?type=web&code=600519#/cwfx`),F12 里直接看网络请求拿完整 reportName 和 columns 参数。

**宏观数据**(GDP/CPI/PPI/PMI)用 `datacenter-web.eastmoney.com`:

```
GET https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_...&columns=...
```

---

## 7. 资金流向(新浪)

```
板块资金:  https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/MoneyFlow.ssl_bkzj_bk?page=1&num=20&sort={netamount|netbuy|change}&asc=0&fenlei={0|1|2}
              # fenlei: 0=全部 1=行业 2=概念板块 3=地域
个股资金:  https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/MoneyFlow.ssl_bkzj_ssggzj?page=1&num=20&sort={...}&asc=0&bankuai=&shichang=
资金趋势:  http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/MoneyFlow.ssl_qsfx_zjlrqs?page=1&num={天数}&sort=opendate&asc=0&daima={代码}
```

必带:`Referer: https://finance.sina.com.cn`。返回 JSON(非加密)。

**东财资金流(按 K 线周期)**:

```
GET https://push2.eastmoney.com/api/qt/stock/fflow/kline/get?secid={secid}&klt=1&lmt=1
GET https://push2.eastmoney.com/api/qt/stock/fflow/daykline/get?secid={secid}&lmt={天数}
```

---

## 8. 公告 / 研报 / 龙虎榜

```
个股公告: https://np-anotice-stock.eastmoney.com/api/security/ann?page_size=50&page_index=1&ann_type=SHA,CYB,SZA,BJA,INV&client_source=web&f_node=0&stock_list={代码}
行业研报: https://reportapi.eastmoney.com/report/list?industryCode={...}&pageSize=50&industry=...&pageNo=1&pageType=0&qType=0
个股研报: https://reportapi.eastmoney.com/report/list2?code={代码}&pageSize=50&pageNo=1&qType=0
龙虎榜:   https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_BILLBOARD_DAILYDETAILS&filter=(TRADE_DATE='2026-07-01')&columns=ALL
```

---

## 9. 新闻资讯

### 9.1 财联社电报(推荐爬网页)

API 需要 sign 签名(动态计算,含 MD5 混淆),不建议逆向。**直接爬页面**:

```
GET https://www.cls.cn/telegraph        # HTML 页,chromedp/playwright 渲染
```

备用(固定 sign 可用的搜索接口,可能随时失效):

```
GET https://www.cls.cn/api/csw?app=CailianpressWeb&os=web&sv=8.4.6&sign=9f8797a1f4de66c2370f7a03990d2737&keyword={关键词}
```

### 9.2 新浪 7x24 快讯(免费 JSON)

```
GET https://zhibo.sina.com.cn/api/zhibo/feed?callback=callback&page=1&page_size=20&zhibo_id=152&tag_id=0&dire=f&dpc=1&pagesize=20&id=4161089&type=0&_={时间戳}
```

返回 JSONP,剥壳后 JSON 内 `result.data.feed.list[].rich_text` 为快讯文本。

### 9.3 华尔街见闻(需 UA 伪装)

```
快讯:   https://api-one-wscn.awtmt.com/apiv1/content/lives?channel={global-channel|a-stock-channel|us-stock-channel|...}&client=pc&limit={条数}&first_page=true&accept=live,vip-live
行情:   https://api-ddc-wscn.awtmt.com/market/real?prod_code=DXY.OTC,XAUUSD.OTC&fields={逗号字段列表}
K线:    https://api-ddc-wscn.awtmt.com/market/kline?prod_code=DXY.OTC&period_type={86400=日}&tick_count={条数}&fields={open,close,high,low,...}
日历:   https://api-one-wscn.awtmt.com/apiv1/finance/indicator/search?start_time={ts}&end_time={ts}&limit={条数}
搜索:   https://search-open-api-wscn.awtmt.com/search/search?keyword={词}&page=1&pageSize=10
```

> base 域名:快讯/日历/搜索用 `api-one-wscn.awtmt.com/apiv1`(搜索把 api-one 换成 search-open-api),行情/K 线用 `api-ddc-wscn.awtmt.com`。若 404 需通过浏览器 F12 抓当前实际域名。

### 9.4 TradingView 中文新闻

```
GET https://news-mediator.tradingview.com/news-flow/v2/news?filter=lang:zh-Hans&client=screener&streaming=false
    (需带 Host/Origin/Referer: cn.tradingview.com)
详情: https://news-headlines.tradingview.com/v3/story?id={id}&lang=zh-Hans
```

### 9.5 雪球热门(需 cookie,慎用)

```
先 GET https://xueqiu.com/ 取 cookie (不取会 403)
GET https://stock.xueqiu.com/v5/stock/hot_stock/list.json?page=1&size=10&_type=10&type=10   # 热门股
GET https://xueqiu.com/hot_event/list.json?count=10                                           # 热门事件
```

---

## 10. 节假日 / 交易日(强烈推荐,免费公开)

```
GET https://timor.tech/api/holiday/info/{YYYY-MM-DD}      # 单日查询
GET https://timor.tech/api/holiday/year/{YYYY}/           # 整年查询
```

返回 JSON:

```json
{
  "code": 0, "holiday": {
    "holiday": true,                       // 是否节假日
    "name": "国庆节",                      // 节假日名称
    "wage": 3,                             // 加班工资倍数
    "date": "2026-10-01"
  }
}
```

交易日判断逻辑(本项目实际做法):
1. 周六/周日 → 非交易日(确定性,缓存 1 天)
2. 调休补班(holiday=false 但标记为工作日)→ 交易日
3. 节假日 → 非交易日

---

## 11. 基金数据

```
场外净值(新浪):     GET https://hq.sinajs.cn/rn={ts}&list=f_{基金代码}          # 需 Referer,GBK
场外实时估值(天天): GET https://fundgz.1234567.com.cn/js/{基金代码}.js           # 返回 JS 文本 jsonpgz({...})
场内 ETF K线:       GET https://push2his.eastmoney.com/api/qt/stock/kline/get?secid={ETF secid}&klt=101  # 与股票K线同接口
历史净值:           GET https://fund.eastmoney.com/pingzhongdata/{基金代码}.js   # JS 文本,正则提 Data_netWorthTrend
基本信息:           GET https://fundmobapi.eastmoney.com/FundMNewApi/FundMNFInfo?pageIndex=1&pageSize=1&plat=Android&appType=ttjj&product=EFund&Version=1&deviceid=1&Ession=1&Fcodes={代码}
十大持仓:           GET https://fundf10.eastmoney.com/FundArchivesDatas.aspx?type=jjcc&code={代码}&topline=10&year=&month=&rt={ts}
基金排行:           GET https://fund.eastmoney.com/data/rankhandler.aspx?op=ph&dt=kf&ft=all&rs=&gs=0&sc=1nzf&st=desc&sd={开始日期}&ed={结束日期}&qdii=&tabSubtype=,,,,,&pi=1&pn=50&dx=1
```

ETF 的 secid 与股票一致:沪市 ETF `1.510050`、深市 ETF `0.159915`。

---

## 12. 美股 / 港股

无免费 JSON 直出,本项目用两种方式:

1. **行情页爬取**(新浪,goquery 解析 HTML):
   - 美股: `https://stock.finance.sina.com.cn/usstock/quotes/{代码}.html`
   - 港股: `https://stock.finance.sina.com.cn/hkstock/quotes/{代码}.html`
   - A股: `https://finance.sina.com.cn/realstock/company/{代码}/nc.shtml`
2. **百度股市通**: `https://gushitong.baidu.com/stock/us-{代码}` / `hk-{代码}` / `ab-{代码}`(页面内嵌 JSON,需 JS 执行,建议 playwright)

---

## 13. 问财自然语言选股(需密钥)

```
POST https://openapi.iwencai.com/v1/query2data
Header: Authorization: Bearer {IWENCAI_API_KEY}
Body: {"question": "macd金叉 换手率大于5% 市值小于200亿", "perpage": 50, "page": 1, "secondary_intent": "stock", "log_info": "{\"input_type\":\"typewrite\"}"}
```

> 密钥需在 iwencai 开放平台申请;请求体可能被加密(本项目有加密逻辑),若报错需比对抓包。

---

## 14. 通用注意事项(踩坑清单)

| # | 坑 | 解法 |
|---|---|---|
| 1 | 新浪接口不带 Referer 必 403 | 所有 `sinajs.cn` / `finance.sina.com.cn` 请求带 `Referer: https://finance.sina.com.cn` |
| 2 | 新浪/腾讯行情是 **GBK** 编码 | `resp.encoding = "gb18030"` 再解析 |
| 3 | 东财接口偶发随机 UA 检测 | 带随机 `User-Agent`,必要时请求频率控制在每秒 2-3 次内 |
| 4 | 东财 K 线高峰期 401/空数据 | 先访问 `https://quote.eastmoney.com/` 拿 cookie 再带 cookie 请求(本项目做法) |
| 5 | 财联社 API 需动态 sign | 改用爬页面 `https://www.cls.cn/telegraph` |
| 6 | 雪球接口需 cookie | 先 GET 首页取 cookie 再请求,且频率要低 |
| 7 | 所有接口都可能随时改版 | 本项目 4 层 fallback:K线=东财→新浪→腾讯→通达信;基金净值=新浪→天天基金。Python 项目建议同样做多源降级 |
| 8 | 东财字段是数字码 | 用前文 f12/f14/f2... 对照表解析,不要记"第几个字段" |
| 9 | JSONP 接口(新浪 K 线/快讯) | 正则剥壳:`re.sub(r'^callback_\d+\(|\);$', '', text)` 后 json.loads |
| 10 | 涨停/异动数据 | 东财 `push2ex.eastmoney.com/getAllStockChanges`(需 `ut` token,抓包获取);涨停复盘可用 `https://api.zizizaizai.com/v3/open/review/uplimit/hot?date1={date}&limit=20` |

---

## 15. 频率与配额建议

| 数据源 | 建议频率 | 批量方式 |
|---|---|---|
| 新浪实时 | 3-5 秒一次,单次最多 50-100 只 | 代码逗号拼接一次请求 |
| 腾讯实时 | 同上 | 同上 |
| 东财 K 线 | 单只不高于 1 次/秒 | 批量分页 |
| 东财全市场列表 | 5-10 分钟一次 | 每页 100,页数=总数/100 |
| timor.tech | 1 天 1 次缓存 | — |
| 财联社网页 | 1 分钟 1 次 | — |

**本项目实际经验**:自选股实时行情 5 秒轮询没问题;K 线按需拉取 + SQLite 落库缓存,避免重复请求。
