# ADR-0001: 包管理用 uv 而非 venv

## 状态
已采纳(2026-08-01)

## 背景

实施 MVP(P1.1 后端骨架)时需要选 Python 包管理工具。`backend-arch §2` 隐含使用现代工具,但没明确写 `uv` vs `venv + pip`。

候选:
- **uv**:Astral 团队(Ruff 作者)推出的 Rust 实现的 Python 包管理器,装包快 10x,锁版本强
- **venv + pip**:Python 标准库 + 标准工具,通用但慢
- **poetry**:成熟,但配置复杂,Win11 偶有问题

## 决策

**采用 uv**。

理由:
1. **装包速度**:akshare 等大型依赖用 uv 比 pip 快 5~10 倍,Win11 上实测明显
2. **锁版本**:`uv.lock` 自动生成,等价于 `requirements.txt` + `Pipfile.lock`,更可靠
3. **Python 版本管理**:uv 自动下载指定 Python 版本,不用系统装 Python 3.11
4. **Windows 友好**:uv 是 Rust 实现,跨平台一致性好

## 后果

- ✅ 装包速度大幅提升,Day 4 装 akshare 节省 ~5min
- ✅ `uv.lock` 入 git,版本严格可追溯
- ⚠️ 团队成员需要 `pip install uv` 一次;新机器 1 分钟搞定
- ⚠️ 部分老 Python 工具链(setuptools 早期版本)与 uv 兼容性问题,MVP 用现代包(Pydantic v2 / FastAPI)无影响

## 替代方案(被否决)

| 方案 | 否决理由 |
|---|---|
| venv + pip | 装包慢,Win11 路径问题多 |
| poetry | Win11 偶有 lockfile 解析失败;MVP 用不到虚拟环境多 Python 版本切换 |
| conda | 重,个人项目不需要 |

## 参考

- uv 官方:https://docs.astral.sh/uv/
- backend-arch §2 技术栈