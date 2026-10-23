/**
 * axios 实例 + snake_case → camelCase 自动转换(frontend-arch §7.1)
 *
 * 后端 Pydantic 用 snake_case,前端 TS 用 camelCase,转换在拦截器中自动完成。
 */
import axios from 'axios';
import type { AxiosRequestConfig } from 'axios';

import { useUIStore } from '@/stores/useUIStore';

/**
 * axios 请求级「预期 404」开关(类型增强)
 *
 * **为什么要它**:有些 404 是**正常业务语义**而不是故障 ——
 * 例如 `GET /api/battle-plan` 在「今天的作战计划还没生成」时按 API 契约返回 404,
 * 前端据此渲染空态卡片。这种 404 再配一个红色「请求失败」toast,
 * 等于把正常状态渲染成错误(与本功能「诚实披露、不制造恐慌」的基调冲突)。
 *
 * **语义边界**(三条都不能破):
 *   1. 只对**本次请求**生效 —— 不传这个字段的请求行为完全不变。
 *   2. **只静音 404** —— 400/409/422/500/网络错误照常弹 toast。
 *   3. **错误照常 reject** —— 调用方(如 PlanPanel)仍要靠 `e.response.status === 404`
 *      走空态分支;绝不能把 404 变成 resolved。
 *
 * **代价**:开关是「按状态码静音」而不是「按 URL 静音」——
 * 所以只应加在**语义明确**的单点调用上(如 `fetchBattlePlan`),
 * 不要加在会返回多种错误的通用请求上,否则真出 404 时会被一起吞掉。
 */
declare module 'axios' {
  export interface AxiosRequestConfig<D = any, P = any> {
    /**
     * 本次请求的 404 是否为**预期业务结果**。
     *
     * true → 404 时**不弹**错误 toast(错误仍然 reject);
     * 其它状态码(422/500/网络错误等)完全不受影响。
     */
    expectedNotFound?: boolean;
  }
}

/** API 错误响应格式(与 backend-arch §7.3 / docs/api-contract §14.3 一致)*/
export interface ApiError {
  code: string;
  message: string;
  detail?: Record<string, unknown>;
}

export const api = axios.create({
  // 用 127.0.0.1 而非 localhost:Node 的 dns.lookup('localhost') 返回 ::1(IPv6),
  // 而后端 uvicorn 只监听 IPv4,SSR 端 fetch 会失败
  // 路径以 /api 开头(后端路由前缀,见 backend-arch §7.1)
  baseURL: process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000/api',
  timeout: 10000,
  headers: { 'Content-Type': 'application/json' },
});

/** 响应拦截器:snake_case → camelCase + 统一错误处理 */
api.interceptors.response.use(
  (response) => {
    if (response.data && typeof response.data === 'object') {
      response.data = snakeToCamel(response.data);
    }
    return response;
  },
  (error) => {
    // 「预期 404」短路:404 是正常业务语义(如今日作战计划还没生成)→ 不弹 toast。
    // ⚠️ 仍然 reject —— 调用方(PlanPanel)靠 e.response.status === 404 走空态分支。
    // ⚠️ 只认 404:422/500/网络错误照常弹 toast(见下)。
    if (error.config?.expectedNotFound === true && error.response?.status === 404) {
      return Promise.reject(error);
    }

    let message = '请求失败';
    let type: 'error' | 'warning' = 'error';

    // 1. ApiError 格式 `{code, message}`(后端业务错误)
    if (error.response?.data?.code && error.response.data.message) {
      message = error.response.data.message;
    }
    // 2. FastAPI 422 校验错误:`[{"loc":["body","field"], "msg":"..."}]`
    else if (error.response?.status === 422 && Array.isArray(error.response.data?.detail)) {
      const issues = error.response.data.detail as Array<{ loc?: (string | number)[]; msg?: string }>;
      const first = issues[0];
      if (first?.msg) {
        const field = Array.isArray(first.loc) ? first.loc.filter((x) => x !== 'body').join('.') : '';
        message = field ? `${field}: ${first.msg}` : first.msg;
      } else {
        message = '参数校验失败';
      }
    }
    // 3. 网络错误(CORS / 服务未起 / 超时)
    else if (error.code === 'ERR_NETWORK' || error.message?.includes('Network Error')) {
      message = '网络错误:后端可能未启动或 CORS 被拦截';
    } else if (error.code === 'ECONNABORTED') {
      message = '请求超时,请重试';
    }
    // 4. 其他 HTTP 错误
    else if (error.response?.status) {
      message = `请求失败 (HTTP ${error.response.status})`;
    }

    // 触发 toast(忽略 store 不可用,如 SSR / 测试)
    try {
      useUIStore.getState().showToast({ type, message });
    } catch {
      /* ignore */
    }
    return Promise.reject(error);
  },
);

/** 请求拦截器:camelCase → snake_case(后端 Pydantic 字段约定) */
api.interceptors.request.use(
  (config) => {
    if (config.data && typeof config.data === 'object' && !(config.data instanceof FormData)) {
      config.data = camelToSnake(config.data);
    }
    return config;
  },
  (error) => Promise.reject(error),
);

/**
 * camelCase → snake_case 转换(请求 body 用)
 *
 * 与 camelKey 对称:区间分桶键 `up5_10` → `up_5_10`
 */
function camelToSnake(obj: unknown): unknown {
  if (Array.isArray(obj)) return obj.map(camelToSnake);
  if (obj !== null && typeof obj === 'object' && !(obj instanceof Date)) {
    return Object.fromEntries(
      Object.entries(obj as Record<string, unknown>).map(([k, v]) => {
        const range = /^([a-z]+)(\d+)_(\d+)$/.exec(k);
        const snake = range
          ? `${range[1]}_${range[2]}_${range[3]}`
          : k.replace(/[A-Z]/g, (c) => `_${c.toLowerCase()}`);
        return [snake, camelToSnake(v)];
      }),
    );
  }
  return obj;
}

/**
 * 单个键名 snake_case → camelCase
 *
 * **为什么要单独抽一个函数**:区间分桶键(后端 `up_5_10` / `down_1_5` / `limit_up`)
 * 有一半是数字,通用规则 `/_([a-z])/g` 只吃掉「下划线 + 字母」,
 * 于是 `up_5_10` 原样保留 —— 而 src/lib/types.ts 里声明的字段名是
 * `up5_10`(第一段下划线去掉、第二段保留)。
 *
 * 结果:类型检查全绿、运行期却是 `undefined`。
 * 受影响的地方(此前都是静默失效的):
 *   - components/desk/BreadthBar.tsx(市场宽度色带 → 6 个档位家数显示 undefined)
 *   - components/market/MarketOverviewPage.tsx(大盘页「A 股涨跌分布」)
 *
 * 规则(窄口径,只命中「单词 + 两段数字」这一种形态):
 *   up_5_10  → up5_10
 *   down_1_5 → down1_5
 *   limit_up → limitUp(走通用规则)
 */
function camelKey(key: string): string {
  // P3(阶段10):快路径 —— 没有下划线的键绝大多数本来就是 camelCase,
  // 直接返回,省掉一次正则扫描。盯盘页每次轮询要对上千个键跑这个函数,
  // 而正则扫描是这个函数里最贵的一步。
  if (!key.includes('_')) return key;
  const range = /^([a-z]+)_(\d+)_(\d+)$/.exec(key);
  if (range) return `${range[1]}${range[2]}_${range[3]}`;
  return key.replace(/_([a-z])/g, (_, c: string) => c.toUpperCase());
}

/**
 * snake_case → camelCase 转换(递归对象/数组)
 * 供 SSE 流式(fetch 直连,不走 axios 拦截器)等场景复用
 */
export function snakeToCamel(obj: unknown): unknown {
  if (Array.isArray(obj)) {
    // P3(阶段10):内容没变就返回**原数组**,不新建。
    // 意义在于保留引用 —— 下游的 memo/浅比较只有拿到同一个引用才判得出"没变",
    // 否则每次转换都造一批新对象,浅比较永远为假。
    let changed = false;
    const out = obj.map((v) => {
      const c = snakeToCamel(v);
      if (c !== v) changed = true;
      return c;
    });
    return changed ? out : obj;
  }
  if (obj !== null && typeof obj === 'object' && !(obj instanceof Date)) {
    const src = obj as Record<string, unknown>;
    let changed = false;
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(src)) {
      const ck = camelKey(k);
      const cv = snakeToCamel(v);
      if (ck !== k || cv !== v) changed = true;
      out[ck] = cv;
    }
    return changed ? out : src;
  }
  return obj;
}

/**
 * 便捷方法
 * 注意:url 保留前导斜杠,axios 的 combineURLs 会正确拼接 baseURL 路径(/api)。
 * 例:apiGet('/positions') → http://127.0.0.1:8000/api/positions
 * config 可覆盖默认 10s 超时,如 LLM 慢接口需 `{ timeout: 60000 }`
 */
export const apiGet = <T>(url: string, config?: AxiosRequestConfig) =>
  api.get<T>(url, config).then((r) => r.data);
export const apiPost = <T>(url: string, body?: unknown, config?: AxiosRequestConfig) =>
  api.post<T>(url, body, config).then((r) => r.data);
export const apiPatch = <T>(url: string, body?: unknown, config?: AxiosRequestConfig) =>
  api.patch<T>(url, body, config).then((r) => r.data);
export const apiPut = <T>(url: string, body?: unknown, config?: AxiosRequestConfig) =>
  api.put<T>(url, body, config).then((r) => r.data);
export const apiDelete = <T>(url: string, config?: AxiosRequestConfig) =>
  api.delete<T>(url, config).then((r) => r.data);

/** SSE 端点(原地址,EventSource 不支持自定义 header,需直接传 base) */
export const sseUrl = (): string => {
  const base = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';
  return `${base}/api/events/sse`;
};

/** 获取 baseURL(用于 fetch 直接调用,如 multipart/form-data) */
export const apiBaseUrl = (): string =>
  process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000/api';