# 接口变更日志(API Changelog)

> 面向开发者。每次后端接口变更时追加一行。
> 与 `release-notes.md` 的区别:`release-notes` 面向用户(功能视角),本文件面向开发者(API 视角)。

## 变更模板

```
## YYYY-MM-DD | v0.1.x | 一句话变更主题

### Breaking(破坏性)
- 端点 X 字段 Y 从 int 改为 string(前端需同步)

### Added(新增)
- 新增端点 Z

### Changed(修改)
- 端点 X 字段 Y 默认值从 X 改为 Y

### Deprecated(弃用)
- 端点 X 将于 v0.2 移除

### Fixed(修复)
- 端点 X 在 Y 场景下返回错误码 Z 应为 W
```

---

## 历史记录

### 2026-08-01 | v0.1.0 | MVP 初始版

#### Added
- 16 个端点全部新增(详见 `api-contract.md`)
- v2.1:加 `GET /api/llm/keys` + `PUT /api/llm/keys` + `POST /api/llm/test`
- v2.0:加截图识别 5 个端点
- v1.7:加 SSE `GET /api/events/sse`
- v1.5:加 `POST /api/diagnose/{trade_id}/regenerate`

#### 设计原则(贯穿 MVP)
- 所有金额字段用 **字符串** 传输(精度保护)
- snake_case → camelCase 在 axios 拦截器自动转换
- 错误格式统一:`{ code, message, detail }`
- 5 类鉴权缺失(MVP 单机)

#### 已知限制
- 无鉴权(MVP 单机自用)
- 无分页元数据标准化(`{ items, total }` 是临时方案)
- 错误码未来可能细分(目前 16 类够用)