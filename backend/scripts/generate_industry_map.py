"""一次性生成离线行业归属表(baostock 全量拉取)

输出: app/data/industry_map.json
格式: {"600519.SH": {"name": "酒、饮料和娱乐茶制造业", "market": "SH"}, ...}

仅开发环境运行(baostock 是第三方 SDK,运行时零依赖,离线表只读)。
用法: python -m scripts.generate_industry_map
"""
import json
from pathlib import Path

import baostock as bs

OUT = Path(__file__).resolve().parents[1] / "app" / "data" / "industry_map.json"


def _internal(code: str) -> str:
    """sh.600519 → 600519.SH"""
    market, num = code.split(".")
    return f"{num}.{market.upper()}"


def main() -> None:
    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"baostock 登录失败: {lg.error_msg}")
    try:
        rs = bs.query_stock_industry()
        if rs.error_code != "0":
            raise RuntimeError(f"行业拉取失败: {rs.error_msg}")
        mapping: dict[str, dict] = {}
        while rs.next():
            row = rs.get_row_data()  # updateDate, code, code_name, industry, classification
            code, name = row[1], row[3]
            mapping[_internal(code)] = {
                "name": name,
                "classification": row[4],
            }
    finally:
        bs.logout()

    OUT.write_text(
        json.dumps(mapping, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    print(f"OK {len(mapping)} 条 → {OUT}")


if __name__ == "__main__":
    main()