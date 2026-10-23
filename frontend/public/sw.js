/**
 * 买股工具室 Service Worker(阶段5)
 *
 * 策略:只缓存**静态外壳**(导航请求 + 同源 GET 静态资源),
 * 绝不缓存 /api/** —— 行情与持仓数据必须每次实时获取,缓存会导致
 * 用户看到昨天的价格却以为是今天的,这是投资工具最不能接受的错误。
 */

const CACHE_VERSION = 'v1';
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

  // 4) 静态资源:缓存优先(带后台更新)
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
        .catch(() => cached);
      return cached || network;
    }),
  );
});
