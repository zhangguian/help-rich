# ADR-0002: ProviderFactory 改 async + 返回 None(v2.1 临时决策)

## 状态
已采纳(2026-08-01)

## 背景

`backend-arch §9.3` 原设计 `ProviderFactory.get(name) -> BaseLLM`,**同步 + 必有返回值**。

v2.1 引入 Key UI 输入 + Fernet 加密存储后,Key 从 SQLite 解密是 **IO 操作**,不能同步。

两个问题:
1. **同步变异步**:`get()` 必须 `async`,所有调用方加 `await`
2. **Key 缺时怎么办**:原设计假设 Key 必填,启动时校验;v2.1 决策"启动不阻塞",Key 缺时必须返回 `None` 而不是抛错

## 决策

**改动 1**:`get()` 改 `async def get(name: str) -> BaseLLM | None`
- 调用方加 `await`
- Key 缺时返回 `None`,不抛错

**改动 2**:`DiagnoseService.score_and_notify` 增加空检查
```python
llm = await ProviderFactory.get(active)
if llm is None:
    # 优雅降级:推 trade.failed
    return
```

**改动 3**:`ProviderFactory` 单例缓存改为异步(避免并发 race condition)

## 后果

- ✅ Key 缺时优雅降级,符合"启动不阻塞"决策(D44)
- ⚠️ 调用方多一层 `if llm is None:` 检查,代码略增
- ⚠️ 单测需要 mock 异步 + None 两种情况
- ⚠️ 性能影响:每次评分多 1 次 DB IO(Key 解密),用 in-memory 缓存缓解(可优化 v0.2)

## 替代方案(被否决)

| 方案 | 否决理由 |
|---|---|
| Key 缺时抛错,启动校验 | 与"启动不阻塞"决策冲突 |
| 同步读 Key(用 Keyring 等) | 引入新依赖,MVP 不必要 |
| 全局 cache 启动时一次性解密 | Key 可能运行时变化,无法热更新 |

## 参考

- backend-arch §9.3 / §11.3.4
- project-book §3.A(v2.1 Key UI 输入)