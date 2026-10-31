/**
 * 买股工具室 Service Worker(阶段5)
 *
 * 策略:只缓存**静态外壳**(导航请求 + 同源 GET 静态资源),
 * 绝不缓存 /api/** —— 行情与持仓数据必须每次实时获取,缓存会导致
 * 用户看到昨天的价格却以为是今天的,这是投资工具最不能接受的错误。
 */

/**
 * ⚠️ v2:彻底停掉 `/_next/static/**` 的缓存。
 *
 * 根因(2026-10-30 实测):开发模式下 Next 的 chunk 文件名**不带 hash**
 * (`/_next/static/chunks/app/layout.js`,而不是 `app/layout-<hash>.js`),
 * 同一路径的内容会随每次重建而变。SW 缓存优先把**上一次构建**的 chunk 喂给浏览器,
 * webpack 运行时拿到的 chunk id 与当前构建对不上 → chunk 永远注册不上 →
 * `ChunkLoadError: Loading chunk app/layout failed. (timeout: ...)`(等满 120s 才报)。
 *
 * 症状极具误导性:页面停在 SSR 骨架,所有 `useEffect` 都不执行,
 * 表现为「卡片永远停在加载中」+ 网络面板**一条 /api 请求都没有**——
 * 看起来像接口挂了,其实是客户端根本没启动。
 *
 * 生产模式虽然 chunk 带 hash(旧缓存条目不会再命中),但同一套代码在 dev 下是致命的。
 * → 静态 chunk 一律走网络;浏览器自身的 HTTP 缓存已经够用,SW 再缓存一层只有坏处。
 */
const CACHE_VERSION = 'v2';
const SHELL_CACHE = `shell-${CACHE_VERSION}`;
const RUNTIME_CACHE = `runtime-${CACHE_VERSION}`;

const SHELL_ASSETS = ['/', '/offline'];

/** 激活时清理旧版本缓存 */
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((k) => k !== SHELL_CACHE && k !== RUNTIME_CACHE)
            .map((k) => caches.delete(k)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(SHELL_CACHE)
      .then((cache) => cache.addAll(SHELL_ASSETS))
      .catch(() => {
        // 预缓存失败不阻塞安装
      })
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener('message', (event) => {
  if (event.data === 'SKIP_WAITING') self.skipWaiting();
});

function isApiRequest(url) {
  return (
    url.pathname.startsWith('/api/') ||
    url.pathname.startsWith('/ws') ||
    url.searchParams.has('stream')
  );
}

/**
 * Next.js App Router 的 **RSC 载荷请求**。
 *
 * ⚠️ 这类请求**绝不能走缓存**:
 * 它带 `?_rsc=` 查询参数(以及 Next-Router-* 头),返回的是「这个路由对应哪些 chunk」的映射。
 * 缓存优先会把它喂成**上次构建**的载荷 —— 与页面里实际引用的新 chunk 对不上,
 * 客户端导航直接报 `Cannot read properties of undefined (reading 'call')`。
 * 典型触发场景:发版后老用户还挂着旧 Service Worker,点任意站内链接就白屏。
 *
 * 代价:每次站内导航多一次网络往返。可接受 —— 换来的是发版后不炸。
 */
function isRscRequest(url, request) {
  return (
    url.searchParams.has('_rsc') ||
    request.headers.has('Next-Router-Prefetch') ||
    request.headers.has('Next-Router-State-Tree') ||
    request.headers.has('RSC')
  );
}

/**
 * Next.js 构建产物(JS/CSS)。**绝不能走缓存** —— 见 CACHE_VERSION 处的说明。
 * dev 下文件名不带 hash,重建后旧缓存即失效;生产下带 hash 但同样没必要缓存。
 */
function isNextStatic(url) {
  return url.pathname.startsWith('/_next/static/');
}

self.addEventListener('fetch', (event) => {
  const { request } = event;

  // 只处理 GET;POST/PUT/DELETE 直接走网络
  if (request.method !== 'GET') return;

  let url;
  try {
    url = new URL(request.url);
  } catch {
    return;
  }

  if (url.origin !== self.location.origin) return;

  // 1) API 与流式请求:网络优先,失败不缓存
  if (isApiRequest(url)) {
    event.respondWith(fetch(request));
    return;
  }

  // 2) RSC 载荷:必须走网络(见 isRscRequest 的注释)
  if (isRscRequest(url, request)) {
    event.respondWith(fetch(request));
    return;
  }

  // 2.5) Next 构建产物(chunks / css):**一律走网络**,绝不缓存
  // 见 CACHE_VERSION 处的说明:dev 下 chunk 不带 hash,缓存即失效 → ChunkLoadError。
  if (isNextStatic(url)) {
    event.respondWith(fetch(request));
    return;
  }

  // 3) 导航请求:网络优先,断网时回退到缓存的外壳
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then((res) => {
          const copy = res.clone();
          caches.open(SHELL_CACHE).then((c) => c.put(request, copy));
          return res;
        })
        .catch(async () => {
          const cached = await caches.match(request);
          return cached || (await caches.match('/offline')) || Response.error();
        }),
    );
    return;
  }

  // 4) 其它静态资源:缓存优先(带后台更新)
  event.respondWith(
    caches.match(request).then((cached) => {
      const network = fetch(request)
        .then((res) => {
          if (res && res.status === 200 && res.type === 'basic') {
            const copy = res.clone();
            caches.open(RUNTIME_CACHE).then((c) => c.put(request, copy));
          }
          return res;
        })
        .catch((err) => {
          // ⚠️ 原来写的是 `.catch(() => cached)`:无缓存时 resolve 成 undefined,
          // `respondWith(undefined)` 会让请求以 `net::ERR_FAILED` 收场,
          // 真实原因(网络失败)被吞掉,排查时只能看到一堆 ERR_FAILED。
          // → 无缓存就把原始错误抛出去。
          if (cached) return cached;
          throw err;
        });
      return cached || network;
    }),
  );
});
