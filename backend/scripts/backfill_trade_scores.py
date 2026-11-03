"""补评 / 全量重算交易评分(一次性脚本)

背景:评分口径已升级为 **6 维 / 满分 120**(新增「交易时机」维),
而库里已存的评分是旧口径(5 维 / 100 分)—— 两套分数混存不可比,
必须全量重算一次。

同时补上历史漏评的流水(来源:一键清仓 / 截图导入流水 / 评分功能之前的老流水)。

用法(在 backend/ 目录下):
    python -m scripts.backfill_trade_scores --dry-run          # 只看候选
    python -m scripts.backfill_trade_scores                     # 补无评分的
    python -m scripts.backfill_trade_scores --force             # 全量重算(口径升级用)
    python -m scripts.backfill_trade_scores --force --no-comment# 只算分,不烧 LLM token
    python -m scripts.backfill_trade_scores --stock-code 002185.SZ

幂等:重复执行安全(trade_scores 是 upsert)。
"""
import argparse
import asyncio
import logging

from app.db import async_session  # noqa: F401  (确保 app 包已初始化)
from app.services.diagnose_service import (
    diagnose_service,
    find_backfill_candidates,
)


async def _run(
    stock_code: str | None,
    force: bool,
    with_comment: bool,
    dry_run: bool,
) -> None:
    trade_ids = await find_backfill_candidates(
        stock_code=stock_code,
        force=force,
        limit=1000,
    )
    print(f"候选流水 {len(trade_ids)} 笔: {trade_ids}")
    if dry_run:
        return
    if not trade_ids:
        print("没有需要补评的流水")
        return

    for i, tid in enumerate(trade_ids, 1):
        try:
            await diagnose_service.score_and_notify(tid, with_comment)
            print(f"[{i}/{len(trade_ids)}] trade #{tid} 评分完成")
        except Exception as e:  # noqa: BLE001
            logging.getLogger(__name__).warning(
                "trade #%s 评分失败: %s", tid, e
            )
            print(f"[{i}/{len(trade_ids)}] trade #{tid} 失败: {e}")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="补评 / 全量重算交易评分")
    parser.add_argument("--stock-code", default=None, help="限定某只股票")
    parser.add_argument(
        "--force",
        action="store_true",
        help="全量重算(评分口径升级后必须加这个)",
    )
    parser.add_argument(
        "--no-comment",
        action="store_true",
        help="只算分,不调 LLM(省 token)",
    )
    parser.add_argument("--dry-run", action="store_true", help="只看候选,不执行")
    args = parser.parse_args()

    asyncio.run(
        _run(
            stock_code=args.stock_code,
            force=args.force,
            with_comment=not args.no_comment,
            dry_run=args.dry_run,
        )
    )


if __name__ == "__main__":
    main()
