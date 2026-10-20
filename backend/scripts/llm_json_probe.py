"""LLM JSON 解析诊断工具(2026-10-21 起因)

**为什么需要它**:AI 解读偶发 `JSON 解析失败: ... char 302` 这类报错。
异常信息只说**位置**不说**原因**,没有原文就只能靠猜 ——
2026-10-21 那次就是这么定位不到「LLM 漏掉键的起始引号」的。

后端已在解析失败时把原文落进日志(`app/services/stock_advice_service.py`
的 `_log_raw_on_parse_fail`),所以本工具是**主动复现**用的:

    # 模式 A:直接调 LLM(绕开 SSE),连打 N 次,失败时把原文写到文件
    python -m scripts.llm_json_probe raw 002185.SZ 5

    # 模式 B:连打 N 次真实 SSE 端点(走完整链路,含严格重试)
    python -m scripts.llm_json_probe loop 002185.SZ 5

模式 A 失败时会把原文写到 `backend/llm_raw_fail.txt`。
两者都会打印每轮结果,便于统计失败率。

**注意**:模式 A / B 都会真实调用 MiniMax(计费),别跑太多轮。
"""
import asyncio
import json
import re
import sys

RAW_URL = "http://127.0.0.1:8000/api/stock/{code}/analysis/stream?force=true"
FAIL_DUMP = "llm_raw_fail.txt"


def _show_fail(raw: str, err: Exception) -> None:
    print(f"  FAIL: {err}")
    with open(FAIL_DUMP, "w", encoding="utf-8") as f:
        f.write(raw)
    print(f"  >>> 原文已写入 {FAIL_DUMP}")
    m = re.search(r"char (\d+)", str(err))
    if m:
        p = int(m.group(1))
        print("  --- 出错位置附近 ---")
        print(raw[max(0, p - 250): p + 250])


async def probe_raw(code: str, rounds: int) -> None:
    """模式 A:直接调 LLM,看原文与解析结果"""
    from app.llm.factory import provider_factory
    from app.repositories.llm_settings_repo import llm_settings_repo
    from app.services.kline_service import fetch_klines
    from app.services.stock_advice_service import (
        ANALYSIS_SYSTEM,
        LLM_ANALYSIS_MAX_TOKENS,
        _build_context,
        _parse_llm_json,
    )

    active = await llm_settings_repo.get_active()
    llm = await provider_factory.get(active)
    klines = await fetch_klines(code, "daily", 120)
    ctx = json.dumps(_build_context(klines, "14.35"), ensure_ascii=False)
    user_msg = f"以下为该股票技术指标与最近K线:\n{ctx}\n用户持仓状态(position_status):loss"

    for i in range(1, rounds + 1):
        raw = await llm.chat(ANALYSIS_SYSTEM, user_msg, max_tokens=LLM_ANALYSIS_MAX_TOKENS)
        try:
            d = _parse_llm_json(raw)
            print(f"round {i}: OK (len={len(raw)}, keys={len(d)})", flush=True)
        except Exception as e:
            print(f"round {i}: ", end="")
            _show_fail(raw, e)
            return


async def probe_loop(code: str, rounds: int) -> None:
    """模式 B:连打真实 SSE 端点(走完整链路)"""
    import httpx

    async with httpx.AsyncClient() as client:
        for i in range(1, rounds + 1):
            got_ai = False
            err_msg = None
            async with client.stream("GET", RAW_URL.format(code=code), timeout=240) as r:
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    try:
                        evt = json.loads(line[5:].strip())
                    except Exception:
                        continue
                    if evt.get("event") == "ai_complete":
                        got_ai = True
                    elif evt.get("event") == "ai_error":
                        err_msg = evt.get("message")
            print(f"round {i}: {'OK' if got_ai else 'FAIL ' + str(err_msg)}", flush=True)


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        print("用法: python -m scripts.llm_json_probe {raw|loop} <code> [rounds]")
        return
    mode = sys.argv[1]
    code = sys.argv[2]
    rounds = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    if mode == "raw":
        asyncio.run(probe_raw(code, rounds))
    elif mode == "loop":
        asyncio.run(probe_loop(code, rounds))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
