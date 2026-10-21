"""决策层零 IO / 零 LLM 守卫测试(阶段 9 收尾回填 (c))

**为什么需要这个守卫**:决策层四模块是「纯函数、零 IO、零 LLM」的硬约束 ——
它们只接受**已经取好的数据**。一旦混进 IO / LLM 依赖:
1. 「规则推断」变成不可复现的黑箱(同一份输入两次跑出不同结论);
2. 「价格必须来自 indicators/报价/持仓或其显式四则运算」这条铁律失去可审计性;
3. 「零 LLM」这个产品承诺无法用测试证明,只能靠口头承诺。

**判定方式**:按 **AST 的 import 节点**判定,**不用子串扫** ——
`fulfillment` 字段名里含 "llm" 子串,子串扫会把它误判成 LLM 引用。
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]

# 决策层四模块(纯函数、零 IO、零 LLM)
DECISION_LAYER_FILES = [
    "app/services/position_status.py",
    "app/services/outlook_service.py",
    "app/services/plan_item_builder.py",
    "app/services/fulfillment_checker.py",
]

# 明确禁止的 IO / LLM 依赖顶层包
FORBIDDEN_ROOTS = frozenset({
    # 数据库 / ORM
    "sqlalchemy", "alembic", "aiosqlite", "psycopg", "psycopg2", "asyncpg", "databases",
    # 网络
    "httpx", "requests", "aiohttp", "urllib3", "websockets", "urllib",
    # LLM
    "openai", "anthropic", "langchain", "langchain_openai", "llama_index",
    "google", "cohere", "mistralai", "zhipuai", "dashscope",
})

# 决策层若要碰数据库/仓储,必然经过这些项目内部入口(零 IO 的落点)
FORBIDDEN_INTERNAL_PREFIXES = (
    "app.db",
    "app.models",
    "app.repositories",
    "app.core.db_lock",
)


def _parse_imports(source: str) -> set[str]:
    """解析源码,返回**绝对导入**的模块名集合(相对导入不计)"""
    tree = ast.parse(source)
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                continue  # 相对导入(包内)不计入
            if node.module:
                mods.add(node.module)
    return mods


def _imported_modules(path: Path) -> set[str]:
    """读取文件并解析出导入集合"""
    return _parse_imports(path.read_text(encoding="utf-8"))


def _root(mod: str) -> str:
    return mod.split(".", 1)[0]


def _violations(source: str) -> tuple[list[str], list[str]]:
    """对一段源码求两类违规:IO/LLM 依赖、非(标准库/app)模块。

    返回 (io_llm_hits, internal_hits)。抽成函数是为了让下面的
    `test_guard_detects_violations` 能对**同一套判定逻辑**做自检,
    避免出现「永远通过的空守卫」。
    """
    mods = _parse_imports(source)
    io_llm = sorted(m for m in mods if _root(m) in FORBIDDEN_ROOTS)
    internal = sorted(
        m for m in mods
        if _root(m) not in sys.stdlib_module_names and _root(m) != "app"
    )
    return io_llm, internal


# ---------------- 守卫本体 ----------------

def test_decision_layer_files_all_exist():
    """守卫自身的输入前提:四个模块都在(路径写错 → 守卫变空测试)"""
    for rel in DECISION_LAYER_FILES:
        assert (BACKEND_ROOT / rel).is_file(), f"决策层模块缺失: {rel}"


def test_decision_layer_has_no_io_or_llm_dependencies():
    """决策层不得依赖任何 IO / LLM 包(sqlalchemy / httpx / openai 等)"""
    for rel in DECISION_LAYER_FILES:
        for mod in _imported_modules(BACKEND_ROOT / rel):
            assert _root(mod) not in FORBIDDEN_ROOTS, (
                f"{rel} 依赖了 IO/LLM 包 {mod} —— 决策层必须零 IO、零 LLM"
            )


def test_decision_layer_has_no_internal_module_outside_app():
    """除 `app.*`(项目内部)与标准库外,决策层不得 import 任何其它内部模块"""
    for rel in DECISION_LAYER_FILES:
        for mod in _imported_modules(BACKEND_ROOT / rel):
            root = _root(mod)
            assert root in sys.stdlib_module_names or root == "app", (
                f"{rel} 导入了既非标准库、也非项目内部(app.*)的模块 {mod}"
            )


def test_decision_layer_does_not_touch_database():
    """决策层不得引入数据库 / 仓储入口(app.db / app.models / app.repositories)"""
    for rel in DECISION_LAYER_FILES:
        for mod in _imported_modules(BACKEND_ROOT / rel):
            for prefix in FORBIDDEN_INTERNAL_PREFIXES:
                assert not (mod == prefix or mod.startswith(prefix + ".")), (
                    f"{rel} 导入了数据库入口 {mod} —— 决策层只接受已取好的数据"
                )


def test_decision_layer_currently_imports_nothing_from_app():
    """现状断言:决策层连 app.* 都不 import(纯函数,连内部工具函数都不依赖)

    这条是**现状快照**,不是永久铁律 —— 将来若要复用某个纯工具模块,
    需连同上面的守卫一起改,而不是悄悄绕过。
    """
    for rel in DECISION_LAYER_FILES:
        app_mods = sorted(
            m for m in _imported_modules(BACKEND_ROOT / rel) if _root(m) == "app"
        )
        assert app_mods == [], f"{rel} 引入了项目内部模块 {app_mods}"


# ---------------- 守卫自检(防空测试) ----------------

def test_guard_detects_violations():
    """守卫本身必须能抓到违规 —— 否则上面的断言全是空转"""
    io_llm, internal = _violations("import httpx\nfrom openai import OpenAI\n")
    assert io_llm == ["httpx", "openai"]
    # httpx / openai 既不在标准库也不是 app.* → 同时被「内部模块」规则命中
    assert internal == ["httpx", "openai"]

    io_llm, internal = _violations("from my_internal_helper import foo\n")
    assert io_llm == []
    assert internal == ["my_internal_helper"]

    io_llm, internal = _violations("from app.services import battle_plan_service\n")
    assert io_llm == []
    assert internal == []          # app.* 属项目内部,不在「app.* 之外」之列

    io_llm, internal = _violations("import json\nfrom typing import Any\n")
    assert io_llm == []
    assert internal == []
