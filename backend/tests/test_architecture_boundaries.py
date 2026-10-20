"""架构边界守卫(2026-10 新增,对标 PanWatch tests/test_architecture_boundaries.py)

用 `ast` 静态分析 import,把"分层依赖方向"写成会失败的测试,
而不是写在文档里靠自觉。

当前依赖方向:

    api          → services / repositories / core / models / llm
    services     → repositories / core / models / llm / data / ocr
    repositories → models / core
    core         → config 等基础设施(不得反向依赖业务)
    models       → (ORM 定义,不得导入 api/services)

规则分级:

- `HARD`: 现状零违规,直接断言(新增代码一旦违反立即失败)
- `BASELINE`: 存量违规已冻结在 ``_BASELINE`` 中,只允许变少、不允许变多。
  每修掉一处,请同步从基线里删掉对应条目 —— 基线归零时把规则升级为 HARD。
"""
from __future__ import annotations

import ast
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = BACKEND_ROOT / "app"

# 分层,数字越小越靠内(被依赖方)
LAYERS = ("core", "models", "llm", "data", "ocr", "repositories", "services", "api")

# 允许的"向内依赖"方向:key 不得 import 列表中比自己更靠内的层
# (索引越小越内层;api 可以依赖除 api 外的任何层,core 不得依赖任何业务层)
INWARD_ALLOWED: dict[str, set[str]] = {
    "core": set(),
    # schemas 需要复用 core.stock_code 做代码规范化(DTO 层依赖纯工具函数,合理)
    "models": {"core"},
    "llm": {"core"},
    "data": {"core", "models"},
    "ocr": {"core", "models"},
    "repositories": {"core", "models"},
    "services": {"core", "models", "llm", "data", "ocr", "repositories"},
    "api": {"core", "models", "llm", "data", "ocr", "repositories", "services"},
}

# 已知的"例外"依赖:技术债,冻结在基线里,只减不增。
# 每条都写了原因;重构掉一处就从基线删除。
#   repositories -> services: screener_repo 在函数内延迟 import scoring 的
#       StockFeatures/build_reason(纯函数,但归属错了层)。
#   llm -> repositories: LLM provider factory 需要从 llm_keys_repo 解析加密 Key;
#       理想形态是 platform 层注入,当前是便捷妥协。
_ALLOWED_EXCEPTIONS: dict[tuple[str, str], set[str]] = {
    # screener 域已迁到 modules/(ADR-0001),该技术债随之一起搬走
    ("llm", "repositories"): {"llm/factory.py"},
}

# api 直接导入 repositories 的存量违规(2026-10 基线快照)。
# 每收敛一处就删一行;清空后把该规则改为 HARD 断言。
_API_TO_REPOSITORIES_BASELINE: set[str] = {
    "api/calculator.py",
    "api/cost_settings.py",
    "api/diagnose.py",
    "api/llm_keys.py",
    "api/reflection_context.py",
    "api/screenshot.py",
    "api/stop_losses.py",
    # 阶段1 新增:价格提醒/通知两个 router 走 service 边界,已在基线外验证
    # api/screener.py / api/positions.py / api/transactions.py 已随
    # screener、portfolio 域迁到 modules/(ADR-0001),随之移出基线
}


def _layer_of(rel: str) -> str | None:
    head = rel.split("/")[0] if "/" in rel else ""
    return head if head in LAYERS else None


def _python_files() -> list[Path]:
    return sorted(
        p
        for p in APP_ROOT.rglob("*.py")
        if "__pycache__" not in p.parts and p.name != "__init__.py"
    )


def _relative(path: Path) -> str:
    return path.relative_to(APP_ROOT).as_posix()


def _internal_imports(path: Path) -> set[str]:
    """返回该文件 import 的 `app.<layer>...` 目标层级集合。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as e:  # pragma: no cover - 源码损坏
        raise AssertionError(f"{_relative(path)} 语法错误: {e}") from e

    layers: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("app."):
                    head = alias.name.split(".")[1]
                    if head in LAYERS:
                        layers.add(head)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            # 支持 `from app.services import x` 与 `from app.services.x import y`
            if mod.startswith("app."):
                head = mod.split(".")[1]
                if head in LAYERS:
                    layers.add(head)
    return layers


# ============================================================
# HARD 规则:现状必须为零违规
# ============================================================


def test_core_does_not_depend_on_business_layers() -> None:
    """core 是基础设施,不得反向依赖 api/services/repositories。"""
    violations = [
        f"{_relative(p)} -> {sorted(targets)}"
        for p in _python_files()
        if (layer := _layer_of(_relative(p))) == "core"
        and (targets := _internal_imports(p) - {"core"})
    ]
    assert violations == [], f"core 不得依赖业务层: {violations}"


def test_repositories_do_not_import_api_or_services() -> None:
    """仓储层只做持久化,用例编排属于 services(存量例外见基线)。"""
    # .get 而非 []:整条规则收敛完毕后,key 会从基线里删掉,这里必须容忍缺失
    allowed = _ALLOWED_EXCEPTIONS.get(("repositories", "services"), set())
    violations = [
        f"{_relative(p)} -> {sorted(_internal_imports(p) & {'api', 'services'})}"
        for p in _python_files()
        if _layer_of(_relative(p)) == "repositories"
        and (_internal_imports(p) & {"api", "services"})
        and _relative(p) not in allowed
    ]
    assert violations == [], f"repositories 不得导入 api/services: {violations}"


def test_services_do_not_import_api() -> None:
    """服务层不得反向依赖 HTTP 层(避免 router ↔ service 循环依赖)。"""
    violations = [
        f"{_relative(p)} -> {sorted(_internal_imports(p) & {'api'})}"
        for p in _python_files()
        if _layer_of(_relative(p)) == "services"
        and (_internal_imports(p) & {"api"})
    ]
    assert violations == [], f"services 不得导入 api: {violations}"


def test_layers_never_import_outward() -> None:
    """任何层都不得依赖比自己更靠外的层(如 repositories -> services)。"""
    violations: list[str] = []
    for path in _python_files():
        rel = _relative(path)
        layer = _layer_of(rel)
        if layer is None:
            continue
        allowed = INWARD_ALLOWED[layer]
        for target in _internal_imports(path):
            if target == layer:
                continue
            if target in allowed:
                continue
            if rel in _ALLOWED_EXCEPTIONS.get((layer, target), set()):
                continue
            violations.append(f"{rel} ({layer}) -> {target}")
    assert violations == [], f"依赖方向违规: {sorted(violations)}"


def test_exception_baselines_are_not_stale() -> None:
    """例外基线里的文件若已不再违规,提示同步清理。"""
    stale: list[str] = []
    for (src_layer, dst_layer), files in _ALLOWED_EXCEPTIONS.items():
        for rel in files:
            path = APP_ROOT / rel
            if not path.exists():
                stale.append(f"{rel}(文件已删除)")
                continue
            if _layer_of(rel) != src_layer or dst_layer not in _internal_imports(path):
                stale.append(f"{rel}(已不再 {src_layer} -> {dst_layer})")
    assert stale == [], f"例外基线已过期,请清理: {stale}"


# ============================================================
# BASELINE 规则:存量冻结,只减不增
# ============================================================


def test_api_to_repository_imports_do_not_grow() -> None:
    """api 直接 import repositories 应逐条收敛到 service 边界。

    现状存量见 _API_TO_REPOSITORIES_BASELINE;修掉一处就从基线里删一行。
    """
    actual = {
        _relative(p)
        for p in _python_files()
        if _layer_of(_relative(p)) == "api"
        and "repositories" in _internal_imports(p)
    }
    new = actual - _API_TO_REPOSITORIES_BASELINE
    assert new == set(), (
        "新增 api → repositories 直连(应走 service 边界): "
        f"{sorted(new)};若确有必要,请同时在 _API_TO_REPOSITORIES_BASELINE 中登记理由"
    )


def test_baseline_is_not_stale() -> None:
    """基线里登记的文件已经不再违规时,提示同步清理,避免基线长期腐化。"""
    actual = {
        _relative(p)
        for p in _python_files()
        if _layer_of(_relative(p)) == "api"
        and "repositories" in _internal_imports(p)
    }
    stale = _API_TO_REPOSITORIES_BASELINE - actual
    assert stale == set(), (
        f"基线中这些文件已不再直连 repositories,请从 _API_TO_REPOSITORIES_BASELINE 删除: {sorted(stale)}"
    )


# ============================================================
# HARD 规则:阶段3 模拟盘与真实持仓必须隔离
# ============================================================

# 模拟盘 service/repository 一旦导入真实持仓/流水仓储,就有把模拟流水
# 写进真实账的风险 —— 这类污染极难事后分辨,必须在代码层硬拦。
_FORBIDDEN_IN_PAPER = (
    "repositories.position_repo",
    "modules.portfolio.repository",
    "api.positions",
    "api.transactions",
)


def test_paper_trading_never_imports_real_position_modules() -> None:
    """模拟盘代码禁止触碰真实持仓/流水模块。"""
    offenders: list[str] = []
    for path in _python_files():
        rel = _relative(path)
        if not (rel.startswith("services/paper_trading/") or rel.startswith("repositories/paper_trading")):
            continue
        src = path.read_text(encoding="utf-8")
        for forbidden in _FORBIDDEN_IN_PAPER:
            # 同时覆盖 `from app.xxx import` 与字符串路径引用
            if forbidden in src:
                offenders.append(f"{rel} -> {forbidden}")
    assert offenders == [], (
        "模拟盘代码禁止导入真实持仓/流水模块(会污染真实账本): " f"{offenders}"
    )


def test_paper_tables_are_separate_from_real_tables() -> None:
    """ORM 里 paper_* 模型不得复用真实表名,也不得把真实表当父表外键。"""
    from app.models.orm import (
        PaperAccount,
        PaperEquitySnapshot,
        PaperOrder,
        PaperPosition,
    )

    real_tables = {"transactions", "positions", "watchlist", "trade_scores"}
    for model in (PaperAccount, PaperOrder, PaperPosition, PaperEquitySnapshot):
        assert model.__tablename__.startswith("paper_"), (
            f"{model.__name__} 表名 {model.__tablename__} 未以 paper_ 前缀隔离"
        )
        assert model.__tablename__ not in real_tables, (
            f"{model.__name__} 与真实表重名: {model.__tablename__}"
        )


# ============================================================
# HARD 规则:modules/<domain>(ADR-0001)
# ============================================================

MODULES_ROOT = APP_ROOT / "modules"


def _module_files() -> list[Path]:
    if not MODULES_ROOT.exists():
        return []
    return [p for p in MODULES_ROOT.rglob("*.py") if "__pycache__" not in p.parts]


def _domain_of(rel: str) -> str | None:
    """app/modules/<domain>/... → <domain>"""
    if not rel.startswith("modules/"):
        return None
    parts = rel.split("/")
    return parts[1] if len(parts) >= 3 else None


def test_modules_have_service_entrypoint() -> None:
    """每个域必须暴露 service.py —— 它是跨域唯一允许的入口。"""
    domains = sorted({d for d in (_domain_of(_relative(p)) for p in _module_files()) if d})
    assert domains, "modules/ 下还没有任何业务域"
    for d in domains:
        assert (MODULES_ROOT / d / "service.py").exists(), (
            f"模块 {d} 缺少 service.py(跨域唯一允许的入口)"
        )


def test_modules_do_not_import_other_domains_internals() -> None:
    """跨域只能 import 对方的 service,不得 import api / repository / 其他内部模块。

    这是 modules 版架构里最容易破的边界:写顺手了就会 `from modules.b.repository import x`。
    """
    offenders: list[str] = []
    for path in _module_files():
        rel = _relative(path)
        own = _domain_of(rel)
        if not own:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as e:  # pragma: no cover
            raise AssertionError(f"{rel} 语法错误: {e}") from e

        for node in ast.walk(tree):
            mods: list[str] = []
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app.modules."):
                mods = [node.module]
            elif isinstance(node, ast.Import):
                mods = [a.name for a in node.names if a.name.startswith("app.modules.")]
            for mod in mods:
                parts = mod.split(".")
                if len(parts) < 3 or parts[2] == own:
                    continue
                other = parts[2]
                leaf = parts[3] if len(parts) > 3 else ""
                # 唯一允许的跨域入口:modules.<other>.service
                if leaf != "service":
                    offenders.append(f"{rel} → {mod}")
    assert offenders == [], (
        f"跨域只能 import 对方的 service(不得触及 api/repository/内部模块): {sorted(offenders)}"
    )


def test_modules_do_not_import_legacy_layered_api() -> None:
    """modules/ 内不得回头 import 顶层 app.api.*(会形成环)。"""
    offenders: list[str] = []
    for path in _module_files():
        rel = _relative(path)
        if not _domain_of(rel):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app.api"):
                names = [node.module]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names if a.name.startswith("app.api")]
            for n in names:
                offenders.append(f"{rel} → {n}")
    assert offenders == [], f"modules/ 不得 import app.api.*: {sorted(offenders)}"
