/**
 * axios 实例 + snake_case → camelCase 自动转换(frontend-arch §7.1)
 *
 * 后端 Pydantic 用 snake_case,前端 TS 用 camelCase,转换在拦截器中自动完成。
 */
import axios from 'axios';

import { useUIStore } from '@/stores/useUIStore';

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

/**
 * snake_case → camelCase 转换(递归对象/数组)
 */
function snakeToCamel(obj: unknown): unknown {
  if (Array.isArray(obj)) return obj.map(snakeToCamel);
  if (obj !== null && typeof obj === 'object' && !(obj instanceof Date)) {
    return Object.fromEntries(
      Object.entries(obj as Record<string, unknown>).map(([k, v]) => [
        k.replace(/_([a-z])/g, (_, c: string) => c.toUpperCase()),
        snakeToCamel(v),
      ]),
    );
  }
  return obj;
}

/**
 * 便捷方法
 * 注意:url 保留前导斜杠,axios 的 combineURLs 会正确拼接 baseURL 路径(/api)。
 * 例:apiGet('/positions') → http://127.0.0.1:8000/api/positions
 */
export const apiGet = <T>(url: string) => api.get<T>(url).then((r) => r.data);
export const apiPost = <T>(url: string, body?: unknown) =>
  api.post<T>(url, body).then((r) => r.data);
export const apiPut = <T>(url: string, body?: unknown) =>
  api.put<T>(url, body).then((r) => r.data);
export const apiDelete = <T>(url: string) => api.delete<T>(url).then((r) => r.data);

/** SSE 端点(原生 fetch,不走 axios)*/
export const SSE_URL = '/events/sse';