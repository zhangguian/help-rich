/**
 * 生成盯盘首页重设计预览稿(静态 HTML + 真实 API 数据)
 *
 * 用途:视觉改动「先出稿件再落码」——用真实数据渲染一份可离线打开的静态稿,
 *      确认方向后再改 Next.js 源码。
 *
 * 运行:node scripts/gen-design-preview.mjs
 * 产出:frontend/public/previews/trading-desk.html
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
const API = process.env.RICH_API_BASE || 'http://127.0.0.1:8000';
const OUT = path.join(ROOT, 'frontend', 'public', 'previews', 'trading-desk.html');

const get = async (u) => {
  const r = await fetch(API + u);
  if (!r.ok) throw new Error(`${u} -> HTTP ${r.status}`);
  return r.json();
};

// ---------------------------------------------------------------- 取数
const [overview, sentiment, amountTrend, watchlist, positions, indicators] = await Promise.all([
  get('/api/market/overview'),
  get('/api/market/sentiment'),
  get('/api/market/amount-trend'),
  get('/api/watchlist'),
  get('/api/positions'),
  get('/api/kline/002185.SZ/indicators?period=daily&limit=120'),
]);

const wlItems = watchlist.items || watchlist;
const codes = wlItems.map((w) => w.stock_code);
const quotes = await get(`/api/quotes?codes=${codes.join(',')}`);

const posItems = positions.items || [];
const posCodes = new Set(posItems.map((p) => p.stock_code));
const favCodes = new Set(wlItems.filter((w) => w.is_favorite).map((w) => w.stock_code));

// 持仓优先、其次特别关注,再按涨幅降序 —— 与首页"盯盘列表"一致
const quoteByCode = Object.fromEntries(quotes.map((q) => [q.code, q]));
const listRows = wlItems
  .map((w) => ({ ...w, q: quoteByCode[w.stock_code] }))
  .filter((w) => w.q)
  .sort((a, b) => {
    const pa = posCodes.has(a.stock_code) ? 0 : 1;
    const pb = posCodes.has(b.stock_code) ? 0 : 1;
    if (pa !== pb) return pa - pb;
    const fa = favCodes.has(a.stock_code) ? 0 : 1;
    const fb = favCodes.has(b.stock_code) ? 0 : 1;
    if (fa !== fb) return fa - fb;
    return (b.q.change_pct ?? 0) - (a.q.change_pct ?? 0);
  });

// ---------------------------------------------------------------- K 线
const kItems = indicators.items || [];
const kLast = kItems.slice(-40);

const ma = (n) => {
  const out = [];
  for (let i = 0; i < kItems.length; i++) {
    if (i < n - 1) { out.push(null); continue; }
    let s = 0;
    for (let j = i - n + 1; j <= i; j++) s += Number(kItems[j].close);
    out.push(s / n);
  }
  return out;
};
const maAll = { 5: ma(5), 10: ma(10), 20: ma(20), 60: ma(60) };

const lows = kLast.map((d) => Number(d.low));
const highs = kLast.map((d) => Number(d.high));
const pMin = Math.min(...lows) * 0.985;
const pMax = Math.max(...highs) * 1.015;
const vMax = Math.max(...kLast.map((d) => Number(d.volume))) || 1;

const W = 1000, H = 300, VH = 52, PAD = 4;

// K 线数据交给前端运行时按容器实测尺寸渲染(1:1 像素映射,不做非等比缩放,
// 否则 K 线会被拉变形、Y 轴刻度与价格对不上 —— 真实图表库也是这么做的)
const kData = {
  items: kLast.map((d) => ({
    date: d.date,
    o: Number(d.open),
    h: Number(d.high),
    l: Number(d.low),
    c: Number(d.close),
    v: Number(d.volume),
  })),
  ma: Object.fromEntries(
    [5, 10, 20, 60].map((n) => [
      n,
      maAll[n].slice(-kLast.length).map((v) => (v == null ? null : Number(v))),
    ])
  ),
  maColors: { 5: 'var(--ma5)', 10: 'var(--ma10)', 20: 'var(--ma20)', 60: 'var(--ma60)' },
  high20: Math.max(...highs),
  low20: Math.min(...lows),
};

// 网格线由前端运行时按容器尺寸绘制

// ---------------------------------------------------------------- 宽度色带
const b = sentiment.buckets;
const bandDefs = [
  { key: 'limit_down', label: '跌停', n: b.limit_down, v: 'var(--down-d)' },
  { key: 'down_5_10', label: '-5~10', n: b.down_5_10, v: 'var(--down-2)' },
  { key: 'down_1_5', label: '-1~5', n: b.down_1_5, v: 'var(--down-1)' },
  { key: 'down_0_1', label: '-0~1', n: b.down_0_1, v: 'var(--down-0)' },
  { key: 'flat', label: '平', n: b.flat, v: 'var(--flat)' },
  { key: 'up_0_1', label: '0~1', n: b.up_0_1, v: 'var(--up-0)' },
  { key: 'up_1_5', label: '1~5', n: b.up_1_5, v: 'var(--up-1)' },
  { key: 'up_5_10', label: '5~10', n: b.up_5_10, v: 'var(--up-2)' },
  { key: 'limit_up', label: '涨停', n: b.limit_up, v: 'var(--up-d)' },
];
const total = sentiment.sample_size;
const bandHtml = bandDefs
  .map((d) => `<div class="band-seg" style="flex:${(d.n / total) * 100};background:${d.v}" title="${d.label} ${d.n} 只"></div>`)
  .join('');

const bandLegend = bandDefs
  .map((d) => `<span class="band-chip"><i style="background:${d.v}"></i>${d.label} <b>${d.n}</b></span>`)
  .join('');

// ---------------------------------------------------------------- 持仓汇总
const totalMv = posItems.reduce((s, p) => s + Number(p.current_price) * p.shares, 0);
const floatPnl = posItems.reduce((s, p) => s + Number(p.floating_pnl), 0);
const totalCost = posItems.reduce((s, p) => s + Number(p.total_cost), 0);
const todayPnl = posItems.reduce((s, p) => s + Number(p.today_pnl), 0);

const fmtY = (n) =>
  n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtPct = (n) => `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`;
const cls = (n) => (n > 0 ? 'up' : n < 0 ? 'down' : 'flat');

// ---------------------------------------------------------------- 列表行
const listHtml = listRows
  .map((w) => {
    const q = w.q;
    const isPos = posCodes.has(w.stock_code);
    const isFav = favCodes.has(w.stock_code);
    const active = w.stock_code === '002185.SZ';
    return `<div class="qrow${active ? ' active' : ''}">
      <div class="qleft">
        <span class="qname">${w.stock_name}${isPos ? '<i class="tag-pos">持</i>' : ''}${isFav ? '<i class="tag-fav">★</i>' : ''}</span>
        <span class="qcode">${w.stock_code}</span>
      </div>
      <span class="qprice mono ${cls(q.change_pct)}">${Number(q.current_price).toFixed(3)}</span>
      <span class="qpct mono ${cls(q.change_pct)}">${fmtPct(q.change_pct)}</span>
    </div>`;
  })
  .join('');

const posHtml = posItems
  .map((p) => {
    const pct = (Number(p.floating_pnl) / Number(p.total_cost)) * 100;
    const todayPct = ((Number(p.current_price) - Number(p.prev_close)) / Number(p.prev_close)) * 100;
    return `<div class="prow">
      <div class="pl">
        <span class="pname">${p.stock_name}</span>
        <span class="pcode">${p.stock_code} · ${p.shares}股</span>
      </div>
      <div class="pr">
        <span class="pmono mono ${cls(pct)}">${fmtPct(pct)}</span>
        <span class="pmono mono ${cls(todayPct)}">${fmtPct(todayPct)}</span>
      </div>
    </div>`;
  })
  .join('');

const idxHtml = overview.indexes
  .map((i) => {
    // 指数名缩写(顶栏宽度紧张时全称太长):上证指数→上证 / 深证成指→深证 / 创业板指→创业板
    const short = i.name.replace('成指', '').replace(/指$/, '').replace('指数', '');
    return `<span class="tick" title="${i.name}"><i>${short}</i><b class="mono ${cls(i.change_pct)}">${Number(i.current_price).toFixed(2)}</b><em class="mono ${cls(i.change_pct)}">${fmtPct(i.change_pct)}</em></span>`;
  })
  .join('');

const gainHtml = overview.gainers
  .map((g) => `<span class="mv"><b>${g.name}</b><em class="mono up">${fmtPct(g.change_pct)}</em></span>`)
  .join('');
const loseHtml = overview.losers
  .map((g) => `<span class="mv"><b>${g.name}</b><em class="mono down">${fmtPct(g.change_pct)}</em></span>`)
  .join('');

const volHtml = amountTrend.items
  .map(
    (v) => `<span class="volbar" title="${v.date} ${v.volume_yi} 亿手"><i style="height:${(v.volume_yi / Math.max(...amountTrend.items.map((x) => x.volume_yi))) * 100}%"></i><u>${v.date.slice(5)}</u></span>`
  )
  .join('');

const active = listRows.find((w) => w.stock_code === '002185.SZ') || listRows[0];
const aq = active.q;

// ---------------------------------------------------------------- HTML
const html = `<!DOCTYPE html>
<html lang="zh-CN" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>买股工具室 · 盯盘台重设计稿</title>
<style>
/* ============ 设计 token:深色(默认)/ 浅色 ============ */
:root{
  --mono:"JetBrains Mono","Cascadia Mono",Consolas,ui-monospace,monospace;
  --ui:"PingFang SC","Microsoft YaHei","Segoe UI",system-ui,sans-serif;
  --rail:48px; --list:258px; --decision:304px; --topbar:46px; --breadth:44px;
}
html[data-theme="dark"]{
  --bg:#070B12; --panel:#0D131D; --panel-2:#121A26; --panel-3:#18212F;
  --line:#1E2836; --line-soft:#161E2A;
  --text:#E2E8F2; --text-2:#8FA0B8; --text-3:#5C6B84;
  --up:#F6465D; --up-0:rgba(246,70,93,.32); --up-1:rgba(246,70,93,.55); --up-2:rgba(246,70,93,.78); --up-d:#FF5C71;
  --down:#0ECB81; --down-0:rgba(14,235,129,.30); --down-1:rgba(14,235,129,.52); --down-2:rgba(14,235,129,.76); --down-d:#2BE39A;
  --flat:#3A475C; --accent:#22D3EE; --accent-soft:rgba(34,211,238,.12);
  --warn:#F5A524; --warn-soft:rgba(245,165,36,.14);
  --grid:rgba(143,160,184,.13); --shadow:0 18px 44px -18px rgba(0,0,0,.8);
  --ma5:#F0883E; --ma10:#A78BFA; --ma20:#3B9EFF; --ma60:#22C55E;
  color-scheme:dark;
}
html[data-theme="light"]{
  --bg:#EEF1F5; --panel:#FFFFFF; --panel-2:#F7F9FB; --panel-3:#EEF2F6;
  --line:#DDE3EA; --line-soft:#EAEEF3;
  --text:#101826; --text-2:#54627A; --text-3:#8A97AC;
  --up:#D92B3E; --up-0:rgba(217,43,62,.16); --up-1:rgba(217,43,62,.34); --up-2:rgba(217,43,62,.6); --up-d:#C21F32;
  --down:#07A05C; --down-0:rgba(7,160,92,.14); --down-1:rgba(7,160,92,.3); --down-2:rgba(7,160,92,.55); --down-d:#068A50;
  --flat:#C9D2DD; --accent:#0A84C4; --accent-soft:rgba(10,132,196,.1);
  --warn:#B87400; --warn-soft:rgba(184,116,0,.12);
  --grid:rgba(16,24,38,.09); --shadow:0 10px 26px -14px rgba(16,24,38,.28);
  --ma5:#C2410C; --ma10:#7C3AED; --ma20:#1D4ED8; --ma60:#15803D;
  color-scheme:light;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:var(--ui);font-size:13px;line-height:1.45;
  -webkit-font-smoothing:antialiased;overflow:hidden}
.mono{font-family:var(--mono);font-variant-numeric:tabular-nums;letter-spacing:-.01em}
.up{color:var(--up)} .down{color:var(--down)} .flat{color:var(--text-3)}
.lbl{font-family:var(--mono);font-size:9.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--text-3)}

/* ============ 预览器外壳(非产品界面) ============ */
.preview-bar{display:flex;align-items:center;gap:14px;padding:9px 16px;background:#11161F;
  border-bottom:1px solid #232C3A;color:#C9D4E4;font-size:12px;flex-wrap:wrap}
.preview-bar b{color:#fff;font-weight:600}
.preview-bar .hint{color:#7C8AA3}
.seg{display:inline-flex;border:1px solid #2A3444;border-radius:7px;overflow:hidden}
.seg button{background:transparent;border:0;color:#9AA8BE;padding:4px 11px;font-size:11.5px;cursor:pointer;font-family:var(--ui)}
.seg button.on{background:#22D3EE;color:#04222A;font-weight:600}
.seg button:hover:not(.on){background:#1B2432;color:#D6E0EE}
.scene{display:none}
.scene.on{display:block}
/* 视口模拟:用 iframe 以真实宽度渲染,媒体查询按 iframe 宽度判定 */
.vpwrap{display:none;overflow:auto;height:calc(100vh - 37px);background:#0A0E16;padding:0}
.vpwrap.on{display:block}
.vpwrap iframe{border:0;display:block;background:#070B12}
body.framed .preview-bar{display:none}
body.framed .desk{height:100vh}

/* ============ 产品:盯盘台 ============ */
.desk{height:calc(100vh - 37px);display:flex;flex-direction:column;overflow:hidden;background:var(--bg)}

/* --- 顶栏 --- */
.topbar{height:var(--topbar);flex:0 0 auto;display:flex;align-items:center;gap:16px;
  padding:0 14px;background:var(--panel);border-bottom:1px solid var(--line)}
.brand{display:flex;align-items:center;gap:8px;font-weight:600;font-size:13px;letter-spacing:.01em;white-space:nowrap;flex:0 0 auto}
.brand .mark{width:22px;height:22px;border-radius:5px;background:linear-gradient(140deg,var(--up),#FF8A5B);
  display:grid;place-items:center;font-size:11px;color:#fff;font-weight:700;font-family:var(--mono);flex:0 0 auto}
.tabs{display:flex;gap:2px;background:var(--panel-2);border:1px solid var(--line);border-radius:7px;padding:2px;flex:0 0 auto}
.tabs button{background:transparent;border:0;color:var(--text-2);font-size:11.5px;padding:3px 12px;
  border-radius:5px;cursor:pointer;font-family:var(--ui);white-space:nowrap}
.tabs button.on{background:var(--panel-3);color:var(--text);font-weight:600}
.tabs button.on.fav{color:var(--warn)}
.ticker{display:flex;align-items:center;gap:16px;margin-left:auto;min-width:0;overflow:hidden}
.tick{display:flex;align-items:baseline;gap:6px;white-space:nowrap}
.tick i{font-style:normal;font-size:10.5px;color:var(--text-3);font-family:var(--mono);letter-spacing:.06em;white-space:nowrap}
.tick b{font-size:13.5px;font-weight:600}
.tick em{font-style:normal;font-size:11.5px;font-weight:600}
.hb{display:flex;align-items:center;gap:8px;padding-left:12px;border-left:1px solid var(--line);
  font-size:11px;color:var(--text-3);flex:0 0 auto;white-space:nowrap}
.pill{border:1px solid var(--line);border-radius:5px;padding:3px 9px;color:var(--text-2);cursor:pointer;
  background:var(--panel-2);white-space:nowrap}
.pill:hover{border-color:var(--accent);color:var(--accent)}

/* --- 市场宽度条(签名元素) --- */
.breadth{height:var(--breadth);flex:0 0 auto;display:flex;align-items:center;gap:16px;
  padding:0 14px;background:var(--panel-2);border-bottom:1px solid var(--line)}
.bstats{display:flex;align-items:baseline;gap:14px;white-space:nowrap}
.bstat{display:flex;align-items:baseline;gap:5px}
.bstat u{text-decoration:none;font-size:10px;color:var(--text-3);font-family:var(--mono);letter-spacing:.1em}
.bstat b{font-size:16px;font-weight:600;font-family:var(--mono)}
.bandwrap{flex:1;min-width:0;display:flex;flex-direction:column;gap:3px}
.band{display:flex;height:12px;border-radius:3px;overflow:hidden;background:var(--panel-3);gap:1px}
.band-seg{transition:filter .15s}
.band-seg:hover{filter:brightness(1.35)}
.band-legend{display:flex;gap:16px;justify-content:flex-start;flex-wrap:wrap;overflow:hidden;row-gap:3px}
.band-chip{display:flex;align-items:center;gap:4px;font-size:9px;color:var(--text-3);
  font-family:var(--mono);letter-spacing:.02em;white-space:nowrap}
.band-chip i{width:7px;height:7px;border-radius:2px;display:inline-block}
.band-chip b{color:var(--text-2);font-weight:600}

/* --- 主体三栏 --- */
.main{flex:1;min-height:0;display:grid;grid-template-columns:var(--rail) var(--list) minmax(0,1fr) var(--decision);
  grid-template-rows:minmax(0,1fr)}
.rail{background:var(--panel);border-right:1px solid var(--line);display:flex;flex-direction:column;
  align-items:center;padding:8px 0;gap:2px;overflow:hidden}
.rlogo{width:28px;height:28px;border-radius:7px;background:linear-gradient(140deg,var(--up),#FF8A5B);
  display:grid;place-items:center;color:#fff;font-weight:700;font-family:var(--mono);font-size:11px;margin-bottom:8px}
.ritem{width:32px;height:30px;border-radius:6px;display:grid;place-items:center;color:var(--text-3);cursor:pointer;
  font-size:14px;line-height:1;transition:background .14s,color .14s;position:relative}
.ritem:hover{background:var(--panel-3);color:var(--text-2)}
.ritem.on{background:var(--accent-soft);color:var(--accent)}
.ritem.on::before{content:"";position:absolute;left:-8px;top:7px;bottom:7px;width:2px;border-radius:2px;background:var(--accent)}
.rsep{width:20px;height:1px;background:var(--line);margin:6px 0}

/* --- 行情列表 --- */
.qlist{background:var(--panel);border-right:1px solid var(--line);display:flex;flex-direction:column;
  min-width:0;min-height:0;overflow:hidden}
.qhead{display:flex;align-items:center;gap:8px;padding:0 10px;height:32px;border-bottom:1px solid var(--line)}
.qhead .lbl{flex:1}
.qsort{font-size:10px;color:var(--text-3);font-family:var(--mono)}
.qsearch{flex:1;background:var(--panel-2);border:1px solid var(--line);border-radius:6px;color:var(--text);
  font-size:11.5px;padding:3px 8px;font-family:var(--ui);outline:none}
.qsearch:focus{border-color:var(--accent)}
.qrows{flex:1;overflow-y:auto}
.qrow{display:flex;align-items:center;gap:8px;padding:5px 10px;border-bottom:1px solid var(--line-soft);
  cursor:pointer;position:relative}
.qrow:hover{background:var(--panel-2)}
.qrow.active{background:var(--accent-soft)}
.qrow.active::before{content:"";position:absolute;left:0;top:0;bottom:0;width:2px;background:var(--accent)}
.qleft{flex:1;min-width:0;display:flex;flex-direction:column;gap:0}
.qname{font-size:12.5px;font-weight:500;display:flex;align-items:center;gap:4px;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;line-height:1.3}
.qcode{font-family:var(--mono);font-size:9.5px;color:var(--text-3);line-height:1.2}
.qprice{font-size:12px;text-align:right;font-weight:500;min-width:48px;white-space:nowrap}
.qpct{font-size:10.5px;text-align:right;min-width:48px;white-space:nowrap}
.tag-pos{font-style:normal;font-size:9px;background:var(--accent-soft);color:var(--accent);
  border-radius:3px;padding:0 3px;font-weight:600}
.tag-fav{font-style:normal;font-size:10px;color:var(--warn)}
.qfoot{border-top:1px solid var(--line);padding:5px 10px;font-size:10px;color:var(--text-3);
  display:flex;justify-content:space-between;font-family:var(--mono)}

/* --- 中栏:图表舞台 --- */
.stage{min-width:0;min-height:0;display:flex;flex-direction:column;background:var(--bg);overflow:hidden}
.stockhead{display:flex;align-items:center;gap:14px;padding:9px 14px;background:var(--panel);
  border-bottom:1px solid var(--line);flex-wrap:wrap}
.sh-name{font-size:17px;font-weight:600;letter-spacing:.01em}
.sh-code{font-family:var(--mono);font-size:11px;color:var(--text-3)}
.sh-price{display:flex;align-items:baseline;gap:9px}
.sh-price b{font-family:var(--mono);font-size:26px;font-weight:600;line-height:1}
.sh-price em{font-style:normal;font-family:var(--mono);font-size:13px;font-weight:600}
.sh-meta{display:flex;gap:14px;margin-left:auto;flex-wrap:wrap}
.shm{display:flex;flex-direction:column;gap:1px;white-space:nowrap}
.shm u{text-decoration:none;font-size:9px;color:var(--text-3);font-family:var(--mono);letter-spacing:.1em}
.shm b{font-family:var(--mono);font-size:12.5px;font-weight:500}
.sh-tags{display:flex;gap:5px;flex-wrap:wrap}
.sh-tag{font-size:10px;padding:1px 6px;border-radius:4px;border:1px solid var(--line);color:var(--text-2);white-space:nowrap}
.sh-tag.pos{color:var(--accent);border-color:var(--accent);background:var(--accent-soft)}
.sh-price{display:flex;align-items:baseline;gap:9px;white-space:nowrap}

.chartbar{display:flex;align-items:center;gap:14px;padding:0 14px;height:34px;background:var(--panel);
  border-bottom:1px solid var(--line)}
.periods{display:flex;gap:1px}
.periods button{background:transparent;border:1px solid transparent;color:var(--text-2);font-size:11.5px;
  padding:2px 11px;border-radius:5px;cursor:pointer;font-family:var(--ui)}
.periods button.on{background:var(--panel-3);border-color:var(--line);color:var(--text);font-weight:600}
.overlay-legend{display:flex;gap:12px;margin-left:auto;font-size:10px;color:var(--text-3);font-family:var(--mono)}
.overlay-legend i{display:inline-block;width:12px;height:2px;vertical-align:middle;margin-right:4px}

.chartbox{flex:1;min-height:0;padding:10px 14px 6px;display:flex;gap:6px}
.yaxis{width:40px;flex:0 0 auto;display:flex;flex-direction:column;justify-content:space-between;
  padding:3px 0 22px;font-size:9px;color:var(--text-3);font-family:var(--mono);text-align:right;line-height:1}
.plot{flex:1;min-width:0;display:flex;flex-direction:column;min-height:0}
.chartarea{flex:1;min-height:0;position:relative}
.chartarea svg{position:absolute;inset:0;width:100%;height:100%;display:block}
.xaxis{display:flex;justify-content:space-between;font-size:9px;color:var(--text-3);font-family:var(--mono);
  padding-top:3px;height:14px;flex:0 0 auto}
.legend-row{display:flex;gap:16px;padding:6px 2px 0;border-top:1px solid var(--line-soft);margin-top:4px;
  flex-wrap:wrap;flex:0 0 auto}
.leg{display:flex;align-items:baseline;gap:5px;font-size:10.5px;color:var(--text-3);font-family:var(--mono)}
.leg b{color:var(--text-2);font-size:11.5px}

.levels{background:var(--panel);border-top:1px solid var(--line);padding:8px 14px 10px;flex:0 0 auto}
.levels-head{display:flex;align-items:center;gap:8px;margin-bottom:7px}
.lv{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}
.lv-item{background:var(--panel-2);border:1px solid var(--line);border-radius:7px;padding:6px 9px;
  display:flex;flex-direction:column;gap:2px}
.lv-item u{text-decoration:none;font-size:9.5px;font-family:var(--mono);letter-spacing:.1em}
.lv-item b{font-family:var(--mono);font-size:14px;font-weight:600}
.lv-item span{font-size:10.5px;color:var(--text-3);line-height:1.35}
.lv-item.support{border-left:2px solid var(--down)}
.lv-item.stabilize{border-left:2px solid var(--warn)}
.lv-item.pressure{border-left:2px solid var(--up)}

/* --- 右栏:决策 --- */
.decision{background:var(--panel);border-left:1px solid var(--line);display:flex;flex-direction:column;
  min-width:0;min-height:0;overflow-y:auto;overflow-x:hidden}
.dsec{padding:11px 13px;border-bottom:1px solid var(--line)}
.dhead{display:flex;align-items:center;gap:7px;margin-bottom:9px}
.dhead .lbl{flex:1}
.dnum{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;min-width:0}
.dnum-item{display:flex;flex-direction:column;gap:1px;min-width:0}
.dnum-item u{text-decoration:none;font-size:9px;color:var(--text-3);font-family:var(--mono);letter-spacing:.06em;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.dnum-item b{font-family:var(--mono);font-size:13.5px;font-weight:600;white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis}
.dnum-item span{font-size:9.5px;color:var(--text-3);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.prow{display:flex;align-items:center;gap:8px;padding:4px 0;border-bottom:1px solid var(--line-soft);font-size:11.5px}
.prow:last-child{border-bottom:0}
.pl{flex:1;min-width:0;display:flex;flex-direction:column;line-height:1.25}
.pname{font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pcode{font-size:9.5px;color:var(--text-3);font-family:var(--mono)}
.pr{display:flex;align-items:baseline;gap:10px;flex:0 0 auto}
.pmono{font-size:11px;text-align:right;min-width:52px;white-space:nowrap}

.ai-card{background:var(--panel-2);border:1px solid var(--line);border-radius:9px;padding:10px 11px}
.ai-top{display:flex;align-items:center;gap:8px;margin-bottom:7px}
.ai-view{font-size:12px;font-weight:600;padding:2px 8px;border-radius:5px;background:var(--up-soft);color:var(--up)}
.ai-score{font-family:var(--mono);font-size:11px;color:var(--text-3);margin-left:auto}
.ai-line{font-size:12px;line-height:1.6;color:var(--text-2);margin-bottom:7px}
.ai-line b{color:var(--text);font-weight:600}
.ai-risk{background:var(--warn-soft);border-left:2px solid var(--warn);border-radius:0 6px 6px 0;
  padding:6px 9px;font-size:11.5px;line-height:1.55;color:var(--text-2)}
.ai-risk u{text-decoration:none;font-size:9.5px;font-family:var(--mono);letter-spacing:.1em;color:var(--warn);
  display:block;margin-bottom:2px}

.steps{display:flex;flex-direction:column;gap:7px}
.step{display:flex;gap:9px;align-items:flex-start}
.step-n{width:17px;height:17px;flex:0 0 auto;border-radius:50%;background:var(--panel-3);color:var(--text-3);
  font-size:9.5px;font-family:var(--mono);display:grid;place-items:center;margin-top:1px;font-weight:600}
.step.on .step-n{background:var(--accent);color:#04222A}
.step-q{font-size:11.5px;line-height:1.5}
.step-q b{color:var(--text);font-weight:600}
.step-a{font-size:11px;color:var(--text-2);margin-top:2px;padding:4px 7px;background:var(--panel-2);
  border:1px solid var(--line);border-radius:5px}
.step.on .step-a{color:var(--text);border-color:var(--line);background:var(--panel-3)}
.step-a.muted{color:var(--text-3);background:transparent;border-style:dashed}

.mvrow{display:flex;gap:12px;flex-wrap:wrap}
.mv{display:flex;align-items:baseline;gap:5px;font-size:11px;color:var(--text-2)}
.mv b{font-weight:500}
.mv em{font-style:normal;font-size:10.5px;font-weight:600}
.volbars{display:flex;gap:7px;align-items:flex-end;height:46px;margin-top:7px}
.volbar{flex:1;display:flex;flex-direction:column;align-items:center;gap:3px;height:100%;justify-content:flex-end}
.volbar i{width:100%;background:var(--accent);opacity:.5;border-radius:2px 2px 0 0;display:block}
.volbar u{text-decoration:none;font-size:9px;color:var(--text-3);font-family:var(--mono)}

/* 空场景 */
.empty{display:grid;place-items:center;height:100%;text-align:center;color:var(--text-3)}
.empty .big{font-size:40px;opacity:.25;margin-bottom:10px}
.empty h4{font-size:14px;color:var(--text-2);font-weight:600;margin-bottom:5px}
.empty p{font-size:12px;max-width:280px;line-height:1.6}
.empty-hint{margin-top:14px;display:flex;gap:6px;flex-wrap:wrap;justify-content:center}
.empty-hint span{font-size:10.5px;border:1px solid var(--line);border-radius:5px;padding:2px 8px;color:var(--text-3)}

::-webkit-scrollbar{width:7px;height:7px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--line);border-radius:8px}
::-webkit-scrollbar-thumb:hover{background:var(--text-3)}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}

/* 中等宽度降级:先收窄两侧,但**不牺牲决策栏**——
   新手速看 5 步与 AI 解读是核心功能,不能因为窗口窄就消失 */
@media (max-width:1400px){
  :root{--list:244px;--decision:300px}
  .sh-meta{gap:11px}
  .dnum-item b{font-size:12.5px}
}
@media (max-width:1200px){
  :root{--list:214px;--decision:282px}
  .tick i{display:none}
  .band-legend{gap:8px;flex-wrap:wrap;justify-content:flex-start}
  .bstats{gap:10px}
  .bstat b{font-size:14px}
}
/* 窄屏(平板竖屏 / 侧边窄面板):决策栏不隐藏,改为**移到底部横排**,
   保证「AI 解读 + 新手速看」始终可见 —— 这是小白用户的核心入口 */
@media (max-width:1040px){
  .main{grid-template-columns:var(--rail) var(--list) minmax(0,1fr);
    grid-template-rows:minmax(0,1fr) minmax(230px,320px)}
  .decision{grid-column:1/-1;border-left:0;border-top:1px solid var(--line);
    display:grid;grid-template-columns:repeat(3,minmax(0,1fr));align-items:start;overflow-y:auto}
  .dsec{border-bottom:0;border-right:1px solid var(--line);padding:9px 11px}
  .sh-meta{display:none}
}
</style>
</head>
<body>

<div class="preview-bar">
  <b>买股工具室 · 盯盘台重设计稿</b>
  <span class="hint">布局从「卡片墙 + 上下堆叠」改为「满屏三栏工作台」；右侧集中决策信息</span>
  <div class="seg" id="themeSeg">
    <button data-t="dark" class="on">深色终端</button>
    <button data-t="light">浅色纸面</button>
  </div>
  <div class="seg" id="sceneSeg">
    <button data-s="main" class="on">已选股票</button>
    <button data-s="cold">冷启动(未选)</button>
  </div>
  <div class="seg" id="vpSeg">
    <button data-w="auto" class="on">自适应</button>
    <button data-w="1440">1440px</button>
    <button data-w="1280">1280px</button>
  </div>
  <span class="hint">数据取自本机后端真实接口 · ${new Date().toLocaleString('zh-CN')}</span>
</div>
<div class="vpwrap" id="vpwrap"></div>

<!-- ================= 场景 1:已选股票 ================= -->
<div class="scene on" id="scene-main">
<div class="desk">

  <header class="topbar">
    <div class="brand"><span class="mark">买</span>买股工具室</div>
    <div class="tabs"><button class="on">自选</button><button class="fav">★ 关注</button></div>
    <div class="ticker">${idxHtml}</div>
    <div class="hb"><span class="pill">自动刷新 ON</span><span class="mono">20:57:31</span></div>
  </header>

  <section class="breadth">
    <div class="bstats">
      <div class="bstat"><u>全A</u><b class="mono">${sentiment.sample_size}</b><u>只</u></div>
      <div class="bstat"><u>涨</u><b class="mono up">${sentiment.up_total}</b></div>
      <div class="bstat"><u>跌</u><b class="mono down">${sentiment.down_total}</b></div>
      <div class="bstat"><u>涨停</u><b class="mono up">${sentiment.limit_up}</b></div>
      <div class="bstat"><u>跌停</u><b class="mono down">${sentiment.limit_down}</b></div>
      <div class="bstat"><u>成交</u><b class="mono">${(sentiment.amount_yi / 10000).toFixed(2)}</b><u>万亿</u></div>
    </div>
    <div class="bandwrap">
      <div class="band">${bandHtml}</div>
      <div class="band-legend">${bandLegend}</div>
    </div>
  </section>

  <div class="main">

    <nav class="rail">
      <div class="rlogo">买</div>
      <div class="ritem on" title="盯盘">📈</div>
      <div class="rsep"></div>
      <div class="ritem" title="大盘">🌏</div>
      <div class="ritem" title="板块">🗂</div>
      <div class="ritem" title="快讯">📰</div>
      <div class="rsep"></div>
      <div class="ritem" title="选股">🎯</div>
      <div class="ritem" title="回测">📊</div>
      <div class="ritem" title="盘前简报">☀️</div>
      <div class="rsep"></div>
      <div class="ritem" title="持仓">💼</div>
      <div class="ritem" title="设置">⚙️</div>
    </nav>

    <section class="qlist">
      <div class="qhead">
        <input class="qsearch" placeholder="代码 / 名称">
        <span class="qsort">涨幅 ▾</span>
      </div>
      <div class="qrows">${listHtml}</div>
      <div class="qfoot"><span>${listRows.length} 只</span><span>持仓 ${posItems.length}</span></div>
    </section>

    <section class="stage">
      <div class="stockhead">
        <span class="sh-name">${active.stock_name}</span>
        <span class="sh-code">${active.stock_code}</span>
        <span class="sh-price">
          <b class="${cls(aq.change_pct)}">${Number(aq.current_price).toFixed(3)}</b>
          <em class="${cls(aq.change_pct)}">${fmtPct(aq.change_pct)}</em>
        </span>
        <span class="sh-tags">
          <span class="sh-tag pos">持仓 ${posItems.find((p) => p.stock_code === active.stock_code)?.shares ?? 0} 股</span>
          <span class="sh-tag">成本 ${Number(posItems.find((p) => p.stock_code === active.stock_code)?.avg_cost ?? 0).toFixed(3)}</span>
        </span>
        <div class="sh-meta">
          <div class="shm"><u>最高</u><b class="mono">${Number(aq.high ?? aq.current_price).toFixed(3)}</b></div>
          <div class="shm"><u>最低</u><b class="mono">${Number(aq.low ?? aq.current_price).toFixed(3)}</b></div>
          <div class="shm"><u>昨收</u><b class="mono">${Number(aq.prev_close ?? 0).toFixed(3)}</b></div>
          <div class="shm"><u>成交额</u><b class="mono">${(Number(aq.amount ?? 0) / 1e8).toFixed(2)} 亿</b></div>
        </div>
      </div>

      <div class="chartbar">
        <div class="periods"><button>分时</button><button class="on">日K</button><button>周K</button><button>月K</button><button>60分</button></div>
        <div class="overlay-legend">
          <span><i style="background:var(--ma5)"></i>MA5</span>
          <span><i style="background:var(--ma10)"></i>MA10</span>
          <span><i style="background:var(--ma20)"></i>MA20</span>
          <span><i style="background:var(--ma60)"></i>MA60</span>
        </div>
      </div>

      <div class="chartbox">
        <div class="yaxis"></div>
        <div class="plot">
          <div class="chartarea"></div>
          <div class="xaxis"></div>
          <div class="legend-row">
            <span class="leg">MA5 <b class="mono" style="color:var(--ma5)">${(maAll[5].filter((v) => v != null).slice(-1)[0]).toFixed(2)}</b></span>
            <span class="leg">MA10 <b class="mono" style="color:var(--ma10)">${(maAll[10].filter((v) => v != null).slice(-1)[0]).toFixed(2)}</b></span>
            <span class="leg">MA20 <b class="mono" style="color:var(--ma20)">${(maAll[20].filter((v) => v != null).slice(-1)[0]).toFixed(2)}</b></span>
            <span class="leg">MA60 <b class="mono" style="color:var(--ma60)">${(maAll[60].filter((v) => v != null).slice(-1)[0]).toFixed(2)}</b></span>
            <span class="leg">20日高 <b class="mono">${Math.max(...highs).toFixed(2)}</b></span>
            <span class="leg">20日低 <b class="mono">${Math.min(...lows).toFixed(2)}</b></span>
          </div>
        </div>
      </div>

      <div class="levels">
        <div class="levels-head">
          <span class="lbl">关键价位</span>
          <span style="font-size:10.5px;color:var(--text-3)">来自技术指标与 AI 解读 · 位置参考</span>
        </div>
        <div class="lv">
          <div class="lv-item support"><u>支撑</u><b>13.47</b><span>近 5 日最低点,跌破可能测试 9.67 强支撑</span></div>
          <div class="lv-item stabilize"><u>企稳</u><b>14.55</b><span>下降通道下轨,在此企稳可能反弹</span></div>
          <div class="lv-item pressure"><u>压力</u><b>16.22</b><span>MA20 均线,需放量突破才算反转</span></div>
          <div class="lv-item pressure"><u>压力</u><b>16.75</b><span>MA60 均线,中期多空分水岭</span></div>
        </div>
      </div>
    </section>

    <aside class="decision">
      <div class="dsec">
        <div class="dhead"><span class="lbl">持仓概览</span><span style="font-size:10px;color:var(--text-3)">${posItems.length} 只</span></div>
        <div class="dnum">
          <div class="dnum-item"><u>总市值</u><b class="mono">¥${fmtY(totalMv)}</b><span>股数 × 现价</span></div>
          <div class="dnum-item"><u>总浮盈</u><b class="mono ${cls(floatPnl)}">${fmtPct((floatPnl / totalCost) * 100)}</b><span>¥${fmtY(floatPnl)}</span></div>
          <div class="dnum-item"><u>今日盈亏</u><b class="mono ${cls(todayPnl)}">${todayPnl >= 0 ? '+' : ''}¥${fmtY(todayPnl)}</b><span>现价 − 昨收</span></div>
        </div>
        <div style="margin-top:9px">${posHtml}</div>
      </div>

      <div class="dsec">
        <div class="dhead"><span class="lbl">AI 解读</span><span class="ai-score mono">view 75 分</span></div>
        <div class="ai-card">
          <div class="ai-top">
            <span class="ai-view">看多</span>
            <span style="font-size:11px;color:var(--text-3)">MDD · 30s</span>
          </div>
          <p class="ai-line"><b>KDJ 金叉超卖区 + 量增价升</b>,底背离诱空信号,75 分看多,短期可能反弹但整体仍在下降通道。</p>
          <p class="ai-line">下降通道中,9 月底高点 18.55 跌至当前 ${Number(aq.current_price).toFixed(2)},跌幅约 22.6%,现价触及下轨 14.55 附近,短期有支撑。</p>
          <div class="ai-risk"><u>风险提示</u>当前浮亏约 37%,下降通道未反转,MACD 零轴下方运行,中期趋势仍偏空,反弹高度有限,建议逢高减仓而非加仓死守。</div>
        </div>
      </div>

      <div class="dsec">
        <div class="dhead"><span class="lbl">新手速看 · 5 步</span><span style="font-size:10px;color:var(--accent)">已分析</span></div>
        <div class="steps">
          <div class="step on"><div class="step-n">1</div><div><div class="step-q"><b>方向</b> 涨势 / 跌势 / 震荡</div>
            <div class="step-a">看多 · 下降通道中短线企稳</div></div></div>
          <div class="step on"><div class="step-n">2</div><div><div class="step-q"><b>量能</b> 放量上涨更可信</div>
            <div class="step-a">缩量 0.54,但末日量较前 5 日均量增长 32%,量增价升</div></div></div>
          <div class="step on"><div class="step-n">3</div><div><div class="step-q"><b>价位</b> 当前价处于近 120 日什么位置</div>
            <div class="step-a">低位区间(接近 P20 ¥15.19),慎接飞刀</div></div></div>
          <div class="step on"><div class="step-n">4</div><div><div class="step-q"><b>支撑 / 压力</b> 关键位置决定买卖点</div>
            <div class="step-a">支撑 ¥13.47 · 企稳 ¥14.55 · 压力 ¥16.22 / 16.75</div></div></div>
          <div class="step on"><div class="step-n">5</div><div><div class="step-q"><b>信号确认</b> 机械信号 + 胜率 + AI 解读一致</div>
            <div class="step-a">看多 · 75 分 · 历史同类胜率 61%</div></div></div>
        </div>
      </div>

      <div class="dsec">
        <div class="dhead"><span class="lbl">领涨 / 领跌</span></div>
        <div class="mvrow">${gainHtml}</div>
        <div class="mvrow" style="margin-top:4px">${loseHtml}</div>
      </div>

      <div class="dsec">
        <div class="dhead"><span class="lbl">两市量能 · 近 5 日</span><span style="font-size:10px;color:var(--text-3)">亿手</span></div>
        <div class="volbars">${volHtml}</div>
      </div>
    </aside>

  </div>
</div>
</div>

<!-- ================= 场景 2:冷启动 ================= -->
<div class="scene" id="scene-cold">
<div class="desk">
  <header class="topbar">
    <div class="brand"><span class="mark">买</span>买股工具室</div>
    <div class="tabs"><button class="on">自选</button><button class="fav">★ 关注</button></div>
    <div class="ticker">${idxHtml}</div>
    <div class="hb"><span class="pill">自动刷新 ON</span><span class="mono">20:57:31</span></div>
  </header>
  <section class="breadth">
    <div class="bstats">
      <div class="bstat"><u>全A</u><b class="mono">${sentiment.sample_size}</b><u>只</u></div>
      <div class="bstat"><u>涨</u><b class="mono up">${sentiment.up_total}</b></div>
      <div class="bstat"><u>跌</u><b class="mono down">${sentiment.down_total}</b></div>
      <div class="bstat"><u>涨停</u><b class="mono up">${sentiment.limit_up}</b></div>
      <div class="bstat"><u>跌停</u><b class="mono down">${sentiment.limit_down}</b></div>
      <div class="bstat"><u>成交</u><b class="mono">${(sentiment.amount_yi / 10000).toFixed(2)}</b><u>万亿</u></div>
    </div>
    <div class="bandwrap">
      <div class="band">${bandHtml}</div>
      <div class="band-legend">${bandLegend}</div>
    </div>
  </section>
  <div class="main">
    <nav class="rail">
      <div class="rlogo">买</div>
      <div class="ritem on" title="盯盘">📈</div>
      <div class="rsep"></div>
      <div class="ritem" title="大盘">🌏</div>
      <div class="ritem" title="板块">🗂</div>
      <div class="ritem" title="快讯">📰</div>
      <div class="rsep"></div>
      <div class="ritem" title="选股">🎯</div>
      <div class="ritem" title="回测">📊</div>
      <div class="ritem" title="盘前简报">☀️</div>
      <div class="rsep"></div>
      <div class="ritem" title="持仓">💼</div>
      <div class="ritem" title="设置">⚙️</div>
    </nav>
    <section class="qlist">
      <div class="qhead">
        <input class="qsearch" placeholder="代码 / 名称">
        <span class="qsort">涨幅 ▾</span>
      </div>
      <div class="qrows">${listHtml}</div>
      <div class="qfoot"><span>${listRows.length} 只</span><span>持仓 ${posItems.length}</span></div>
    </section>
    <section class="stage">
      <div class="empty">
        <div>
          <div class="big">📈</div>
          <h4>选一只股票,这里会出现 K 线与 AI 解读</h4>
          <p>左侧列表按涨幅排序,带「持」标记的是你的持仓。选中后这里会显示分时 / 日K / 周K 与关键价位。</p>
          <div class="empty-hint">
            <span>持仓 7 只</span><span>特别关注 6 只</span><span>今日涨停 ${sentiment.limit_up} 家</span>
          </div>
        </div>
      </div>
    </section>
    <aside class="decision">
      <div class="dsec">
        <div class="dhead"><span class="lbl">持仓概览</span><span style="font-size:10px;color:var(--text-3)">${posItems.length} 只</span></div>
        <div class="dnum">
          <div class="dnum-item"><u>总市值</u><b class="mono">¥${fmtY(totalMv)}</b><span>股数 × 现价</span></div>
          <div class="dnum-item"><u>总浮盈</u><b class="mono ${cls(floatPnl)}">${fmtPct((floatPnl / totalCost) * 100)}</b><span>¥${fmtY(floatPnl)}</span></div>
          <div class="dnum-item"><u>今日盈亏</u><b class="mono ${cls(todayPnl)}">${todayPnl >= 0 ? '+' : ''}¥${fmtY(todayPnl)}</b><span>现价 − 昨收</span></div>
        </div>
        <div style="margin-top:9px">${posHtml}</div>
      </div>
      <div class="dsec">
        <div class="dhead"><span class="lbl">新手速看 · 5 步</span><span style="font-size:10px;color:var(--text-3)">待分析</span></div>
        <div class="steps">
          <div class="step"><div class="step-n">1</div><div><div class="step-q"><b>方向</b> 涨势 / 跌势 / 震荡</div>
            <div class="step-a muted">先在左侧选一只股票</div></div></div>
          <div class="step"><div class="step-n">2</div><div><div class="step-q"><b>量能</b> 放量上涨更可信</div>
            <div class="step-a muted">先在左侧选一只股票</div></div></div>
          <div class="step"><div class="step-n">3</div><div><div class="step-q"><b>价位</b> 近 120 日的相对位置</div>
            <div class="step-a muted">先在左侧选一只股票</div></div></div>
          <div class="step"><div class="step-n">4</div><div><div class="step-q"><b>支撑 / 压力</b> 关键位置决定买卖点</div>
            <div class="step-a muted">先在左侧选一只股票</div></div></div>
          <div class="step"><div class="step-n">5</div><div><div class="step-q"><b>信号确认</b> 机械信号 + 胜率 + AI</div>
            <div class="step-a muted">先在左侧选一只股票</div></div></div>
        </div>
      </div>
      <div class="dsec">
        <div class="dhead"><span class="lbl">领涨 / 领跌</span></div>
        <div class="mvrow">${gainHtml}</div>
        <div class="mvrow" style="margin-top:4px">${loseHtml}</div>
      </div>
    </aside>
  </div>
</div>
</div>

<script>
document.getElementById('themeSeg').addEventListener('click',(e)=>{
  const b=e.target.closest('button'); if(!b) return;
  document.documentElement.dataset.theme=b.dataset.t;
  [...e.currentTarget.children].forEach(x=>x.classList.toggle('on',x===b));
  const f=document.querySelector('#vpwrap iframe');
  if(f) f.contentWindow.postMessage({theme:b.dataset.t},'*');
});
document.getElementById('sceneSeg').addEventListener('click',(e)=>{
  const b=e.target.closest('button'); if(!b) return;
  document.getElementById('scene-'+b.dataset.s).classList.add('on');
  document.getElementById('scene-'+(b.dataset.s==='main'?'cold':'main')).classList.remove('on');
  [...e.currentTarget.children].forEach(x=>x.classList.toggle('on',x===b));
  // 切场景时同步 iframe 内的场景
  const f=document.querySelector('#vpwrap iframe');
  if(f) f.contentWindow.postMessage({scene:b.dataset.s,theme:document.documentElement.dataset.theme},'*');
  if(typeof renderCharts==='function') renderCharts();
});
document.getElementById('vpSeg').addEventListener('click',(e)=>{
  const b=e.target.closest('button'); if(!b) return;
  [...e.currentTarget.children].forEach(x=>x.classList.toggle('on',x===b));
  const wrap=document.getElementById('vpwrap');
  const scenes=[...document.querySelectorAll('.scene')];
  if(b.dataset.w==='auto'){
    wrap.classList.remove('on');
    scenes.forEach(s=>s.style.display='');
    return;
  }
  scenes.forEach(s=>s.style.display='none');
  wrap.classList.add('on');
  // 面板比模拟视口窄 → 整体等比缩放显示,保证能看到**完整**的四栏结构;
  // iframe 高度按「可用高度 ÷ 缩放比」给,缩放后正好铺满面板,避免底部露出空白
  // (那片空白会被误读成"设计留了虚空" —— 上一版深色终端就是这么被否掉的)
  const availW=wrap.clientWidth||820, availH=wrap.clientHeight||700;
  const w=parseInt(b.dataset.w,10);
  const scale=Math.min(1,availW/w);
  const fh=Math.round(availH/scale);
  wrap.innerHTML='<div style="width:'+Math.round(w*scale)+'px;height:'+availH+'px;margin:0 auto;overflow:hidden">'
    +'<iframe src="trading-desk.html?frame=1" style="width:'+w+'px;height:'+fh+'px;border:0;'
    +'transform:scale('+scale+');transform-origin:top left"></iframe></div>';
});
// iframe 内:接收父页面的场景/主题指令
if(new URLSearchParams(location.search).has('frame')){
  document.body.classList.add('framed');
  window.addEventListener('message',(e)=>{
    if(e.data&&e.data.theme) document.documentElement.dataset.theme=e.data.theme;
    if(e.data&&e.data.scene){
      document.getElementById('scene-'+e.data.scene).classList.add('on');
      document.getElementById('scene-'+(e.data.scene==='main'?'cold':'main')).classList.remove('on');
    }
    if(typeof renderCharts==='function') setTimeout(renderCharts,40);
  });
  // 初始主题跟随父页面
  try{
    const t=window.parent.document.documentElement.dataset.theme;
    if(t) document.documentElement.dataset.theme=t;
  }catch(e){}
}
document.querySelectorAll('.qrow').forEach(r=>{
  r.addEventListener('click',()=>{
    document.querySelectorAll('.qrow').forEach(x=>x.classList.remove('active'));
    r.classList.add('active');
  });
});
</script>
<script id="kdata" type="application/json">${JSON.stringify(kData)}</script>
<script>
/* K 线按容器实测尺寸渲染:viewBox 与像素 1:1,不做非等比缩放
   —— 蜡烛不会被拉变形,Y 轴刻度与价格严格对应 */
function renderCharts(){
  const d=JSON.parse(document.getElementById('kdata').textContent);
  document.querySelectorAll('.plot').forEach(plot=>{
    const area=plot.querySelector('.chartarea');
    if(!area) return;
    const ya=plot.parentElement.querySelector('.yaxis');
    const xa=plot.querySelector('.xaxis');
    const W=area.clientWidth, H=area.clientHeight;
    if(W<80||H<80) return;
    const items=d.items, n=items.length;
    const PAD=3, VHR=Math.max(36,Math.round(H*0.17)), XH=14;
    const PH=H-VHR-XH;
    let pMin=Infinity,pMax=-Infinity,vMax=0;
    items.forEach(k=>{if(k.l<pMin)pMin=k.l;if(k.h>pMax)pMax=k.h;if(k.v>vMax)vMax=k.v;});
    pMin=pMin*0.985; pMax=pMax*1.015;
    const x=i=>PAD+(i*(W-PAD*2))/(n-1);
    const y=p=>PAD+((pMax-p)/(pMax-pMin))*(PH-PAD*2);
    const bw=Math.max(1.2,(W-PAD*2)/n-1.4);
    let s='';
    for(let i=0;i<=4;i++){
      const p=pMin+(pMax-pMin)*i/4, yy=y(p);
      s+='<line x1="0" y1="'+yy.toFixed(1)+'" x2="'+W+'" y2="'+yy.toFixed(1)+'" stroke="var(--grid)" stroke-width="0.6"/>';
    }
    items.forEach((k,i)=>{
      const up=k.c>=k.o, col=up?'var(--up)':'var(--down)';
      s+='<line x1="'+x(i).toFixed(1)+'" y1="'+y(k.h).toFixed(1)+'" x2="'+x(i).toFixed(1)+'" y2="'+y(k.l).toFixed(1)+'" stroke="'+col+'" stroke-width="1"/>';
      const yo=y(Math.max(k.o,k.c)), yc=y(Math.min(k.o,k.c));
      s+='<rect x="'+(x(i)-bw/2).toFixed(1)+'" y="'+yo.toFixed(1)+'" width="'+bw.toFixed(1)+'" height="'+Math.max(1,yc-yo).toFixed(1)+'" fill="'+col+'" rx="0.4"/>';
      const vh=(k.v/vMax)*(VHR-6);
      s+='<rect x="'+(x(i)-bw/2).toFixed(1)+'" y="'+(PH+VHR-vh).toFixed(1)+'" width="'+bw.toFixed(1)+'" height="'+vh.toFixed(1)+'" fill="'+col+'" opacity="0.4"/>';
    });
    Object.keys(d.ma).forEach(key=>{
      const pts=[];
      d.ma[key].forEach((v,i)=>{if(v==null)return;pts.push(x(i).toFixed(1)+','+y(v).toFixed(1));});
      s+='<polyline points="'+pts.join(' ')+'" fill="none" stroke="'+d.maColors[key]+'" stroke-width="1.1" opacity="0.9"/>';
    });
    s+='<line x1="0" y1="'+PH+'" x2="'+W+'" y2="'+PH+'" stroke="var(--grid)" stroke-width="0.8"/>';
    area.innerHTML='<svg viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none" role="img" aria-label="日K线图">'+s+'</svg>';
    let yt='';
    for(let i=0;i<=4;i++){const p=pMax-(pMax-pMin)*i/4;yt+='<span>'+p.toFixed(2)+'</span>';}
    if(ya) ya.innerHTML=yt;
    if(xa){
      const idx=[0,Math.round(n*0.25),Math.round(n*0.5),Math.round(n*0.75),n-1];
      xa.innerHTML=idx.map(i=>'<span>'+items[i].date.slice(5)+'</span>').join('');
    }
  });
}
renderCharts();
setTimeout(renderCharts,60);
window.addEventListener('resize',()=>{clearTimeout(window.__rt);window.__rt=setTimeout(renderCharts,80);});
if(document.fonts&&document.fonts.ready) document.fonts.ready.then(()=>renderCharts());
</script>
</body>
</html>
`;

fs.mkdirSync(path.dirname(OUT), { recursive: true });
fs.writeFileSync(OUT, html, 'utf8');
console.log('written:', OUT);
console.log('bytes:', Buffer.byteLength(html));
console.log('rows:', listRows.length, 'positions:', posItems.length, 'kline:', kLast.length);
