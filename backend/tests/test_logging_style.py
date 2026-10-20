"""日志占位符风格守卫。

这个测试存在的唯一原因:2026-10-17 排查"启动慢"时发现,仓库里两套 logger 并存 ——

  * `app/core/logging.py` 导出的是 **loguru** logger,只认 `{}`;
  * 绝大多数 service/api 用的是**标准库** `logging.getLogger()`,只认 `%s`。

两套写法混用不会立刻报错,而是安静地把信息丢掉或直接抛异常:

  logger.info("拉取失败: %s", e)   # loguru  → 日志里永远是字面的 "%s",看不到原因
  logger.info("拉取失败: {}", e)   # 标准库  → TypeError: not all arguments converted
                                     #            during string formatting

后者在后台调度器里尤其隐蔽:任务异常被 asyncio 记成
"Task exception was never retrieved",界面只表现为"数据不更新"。

所以这里按模块的 logger 来源强制统一风格,阻止再次混淆。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1] / "app"
LEVELS = {"debug", "info", "success", "warning", "error", "exception", "critical", "trace"}
LOGGER_NAMES = {"logger", "log"}

# printf 风格占位符(含 %.2f / %5d 的精度与宽度);%% 是字面百分号,单独处理
PRINTF_SPEC_RE = re.compile(r"%(?:\([^)]*\))?[-+ 0#]*\d*(?:\.\d+)?[sdrf]")
BRACE_PAIR_RE = re.compile(r"\{\}")


def _brace_renders(message: str, arg_count: int) -> str | None:
    """用 str.format 实跑一遍(loguru 内部就是 `message.format(*args)`)。"""
    try:
        message.format(*(1.5 for _ in range(arg_count)))
    except (IndexError, KeyError, ValueError) as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


def _printf_renders(message: str, arg_count: int) -> str | None:
    """用 % 运算符实跑一遍,返回错误说明;能渲染则返回 None。

    仅靠正则数占位符个数抓不到真正的问题:例如 `"偏差 %s%, 降级"` 里那个
    落单的 `%` 会吃掉后面的字符,正则数出来是 1 个占位符、参数也正好 1 个,
    看起来"数量对得上",实际运行时 `msg % args` 抛
    `TypeError: not enough arguments for format string`。
    (2026-10-17 一次批量改写就踩了这个坑:`%.2f%%` 被改成 `%s%`,
    生产代码里降级逻辑因此被 `except TypeError: pass` 吞掉。)
    """
    try:
        message % tuple(1.5 for _ in range(arg_count))
    except (TypeError, ValueError) as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


def _python_files() -> list[Path]:
    return sorted(APP_DIR.rglob("*.py"))


def _uses_loguru(source: str) -> bool:
    if "from loguru import" in source:
        return True
    return bool(re.search(r"from app\.core\.logging import[^\n]*\blogger\b", source))


def _first_string_arg(node: ast.Call) -> ast.Constant | None:
    if not node.args:
        return None
    first = node.args[0]
    # 只检查普通字符串字面量;f-string 的动态部分无法静态判断,跳过
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first
    return None


def _format_calls(path: Path) -> list[tuple[int, bool, str, int]]:
    """返回 (行号, 是否 loguru, 消息字面量, 额外参数个数)。"""
    source = path.read_text(encoding="utf-8")
    loguru = _uses_loguru(source)
    tree = ast.parse(source)
    found: list[tuple[int, bool, str, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr in LEVELS):
            continue
        if not (isinstance(func.value, ast.Name) and func.value.id in LOGGER_NAMES):
            continue
        literal = _first_string_arg(node)
        if literal is None or len(node.args) < 2:
            continue
        if node.keywords or any(isinstance(a, ast.Starred) for a in node.args):
            continue
        found.append((node.lineno, loguru, literal.value, len(node.args) - 1))
    return found


def test_files_are_discoverable() -> None:
    assert _python_files(), "没扫到 app/ 下的 python 文件,测试本身失效了"


@pytest.mark.parametrize("path", _python_files(), ids=lambda p: p.name)
def test_log_placeholder_style_matches_logger_backend(path: Path) -> None:
    problems: list[str] = []
    for lineno, loguru, message, arg_count in _format_calls(path):
        if loguru:
            specs = PRINTF_SPEC_RE.findall(message)
            braces = BRACE_PAIR_RE.findall(message)
            if specs:
                problems.append(
                    f"{path.name}:{lineno} loguru logger 用了 printf 占位符 {specs},"
                    f"应改成 '{{}}': {message[:60]}"
                )
            elif len(braces) != arg_count:
                problems.append(
                    f"{path.name}:{lineno} loguru 占位符 {len(braces)} 个但传了 {arg_count} 个参数: "
                    f"{message[:60]}"
                )
            elif error := _brace_renders(message, arg_count):
                problems.append(
                    f"{path.name}:{lineno} loguru 格式串无法渲染({error}): {message[:60]}"
                )
        else:
            braces = BRACE_PAIR_RE.findall(message)
            specs = PRINTF_SPEC_RE.findall(message)
            if braces:
                problems.append(
                    f"{path.name}:{lineno} 标准库 logger 用了 '{{}}',会抛 TypeError,"
                    f"应改成 %s: {message[:60]}"
                )
            elif len(specs) != arg_count:
                problems.append(
                    f"{path.name}:{lineno} 标准库占位符 {len(specs)} 个但传了 {arg_count} 个参数: "
                    f"{message[:60]}"
                )
            elif error := _printf_renders(message, arg_count):
                problems.append(
                    f"{path.name}:{lineno} 标准库格式串无法渲染({error}),"
                    f"运行时这条日志会抛异常: {message[:60]}"
                )
    assert not problems, "日志占位符风格不对:\n" + "\n".join(problems)


def test_guard_catches_stray_percent_sign() -> None:
    """守卫自身的回归:落单的 `%` 必须被抓到。

    这正是 2026-10-17 真实踩过的坑 —— `%.2f%%` 被批量替换成 `%s%`,
    占位符"个数"仍然正确,只有实跑 `%` 才会暴露。
    """
    assert _printf_renders("偏差 %s%%, 降级", 1) is None
    assert _printf_renders("偏差 %s%, 降级", 1) is not None
    assert _printf_renders("a=%s b=%s", 1) is not None  # 参数少了
    assert _printf_renders("a=%s b=%s", 2) is None


def test_guard_catches_stray_brace() -> None:
    """loguru 侧:落单的 `{` / `}` 同样要在守卫里被抓到。

    注意 `%` 在 str.format 里是普通字符,所以这里只验证花括号。
    """
    assert _brace_renders("{} 与 {}", 2) is None
    assert _brace_renders("{} 与 {}", 1) is not None  # 参数少了
    assert _brace_renders("降级 } 后继续", 0) is not None  # 落单的右括号
    assert _brace_renders("降级 { 后继续", 0) is not None  # 落单的左括号
