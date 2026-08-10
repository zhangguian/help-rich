"""沪深 300 + 中证 500 成分股初始化脚本(v2.6 选股模块)

数据源策略:
- 一级:东财公开 API(guide §5.全市场股票列表)— 自动拉取
  https://push2.eastmoney.com/api/qt/clist/get?fs=m:1+t:2,m:0+t:6&fid=f3&pn=1&pz=10000
- 二级:本地种子表(本文件 _SEED_300/_SEED_500)— 网络不可达兜底

用法:
    python -m scripts.init_index_constituents
    python -m scripts.init_index_constituents --force   # 全量重写
    python -m scripts.init_index_constituents --seed-only  # 仅用种子表(offline)

落表:index_constituents(UNIQUE(index_code, stock_code))
"""
import argparse
import asyncio
import json
import logging
from datetime import date
from pathlib import Path

import httpx
from sqlalchemy.exc import IntegrityError

from app.core.config import SCREENER_POOL_INDEX_CODES
from app.db import async_session
from app.models.orm import IndexConstituent

logger = logging.getLogger(__name__)

# ============================================================
# 种子表(offline 兜底,覆盖 HS300 + CS500 常见成分股 ~80 只)
# ============================================================

# (stock_code, stock_name) — 数据来自历史快照(2026-08),仅作兜底
# 真实场景由东财 API 全量拉取覆盖。
_SEED_HS300: list[tuple[str, str]] = [
    ("600519.SH", "贵州茅台"), ("601318.SH", "中国平安"), ("600036.SH", "招商银行"),
    ("601398.SH", "工商银行"), ("601939.SH", "建设银行"), ("601988.SH", "中国银行"),
    ("600276.SH", "恒瑞医药"), ("000858.SZ", "五粮液"), ("000333.SZ", "美的集团"),
    ("002594.SZ", "比亚迪"), ("300750.SZ", "宁德时代"), ("600900.SH", "长江电力"),
    ("601012.SH", "隆基绿能"), ("600887.SH", "伊利股份"), ("000651.SZ", "格力电器"),
    ("600030.SH", "中信证券"), ("601166.SH", "兴业银行"), ("600000.SH", "浦发银行"),
    ("601288.SH", "农业银行"), ("601328.SH", "交通银行"), ("600028.SH", "中国石化"),
    ("601857.SH", "中国石油"), ("601088.SH", "中国神华"), ("600050.SH", "中国联通"),
    ("601728.SH", "中国电信"), ("600941.SH", "中国移动"), ("600585.SH", "海螺水泥"),
    ("601888.SH", "中国中免"), ("600196.SH", "复星医药"), ("000001.SZ", "平安银行"),
    ("002415.SZ", "海康威视"), ("000063.SZ", "中兴通讯"), ("600519.SH", "贵州茅台"),
    ("601995.SH", "中金公司"), ("600436.SH", "片仔癀"), ("600809.SH", "山西汾酒"),
    ("000568.SZ", "泸州老窖"), ("002714.SZ", "牧原股份"), ("300059.SZ", "东方财富"),
    ("002475.SZ", "立讯精密"), ("000725.SZ", "京东方A"), ("002230.SZ", "科大讯飞"),
    ("600438.SH", "通威股份"), ("002466.SZ", "天齐锂业"), ("300760.SZ", "迈瑞医疗"),
    ("601633.SH", "长城汽车"), ("600104.SH", "上汽集团"), ("601628.SH", "中国人寿"),
    ("600690.SH", "海尔智家"), ("600547.SH", "山东黄金"), ("601225.SH", "陕西煤业"),
    ("601899.SH", "紫金矿业"), ("600905.SH", "三峡能源"), ("601877.SH", "正泰电器"),
    ("002607.SZ", "中公教育"), ("300015.SZ", "爱尔眼科"), ("000661.SZ", "长春高新"),
    ("600763.SH", "通策医疗"), ("300124.SZ", "汇川技术"), ("603259.SH", "药明康德"),
    ("603288.SH", "海天味业"), ("603799.SH", "华友钴业"), ("688981.SH", "中芯国际"),
    ("688041.SH", "东微半导"),
]

_SEED_CS500: list[tuple[str, str]] = [
    ("000301.SZ", "东方盛虹"), ("000708.SZ", "中信特钢"), ("000932.SZ", "华菱钢铁"),
    ("000999.SZ", "华润三九"), ("002001.SZ", "新和成"), ("002027.SZ", "分众传媒"),
    ("002120.SZ", "韵达股份"), ("002241.SZ", "歌尔股份"), ("002271.SZ", "东方雨虹"),
    ("002311.SZ", "海大集团"), ("002460.SZ", "赣锋锂业"), ("002493.SZ", "荣盛石化"),
    ("002648.SZ", "卫星化学"), ("002736.SZ", "国信证券"), ("002812.SZ", "恩捷股份"),
    ("002841.SZ", "视源股份"), ("300003.SZ", "乐普医疗"), ("300122.SZ", "智飞生物"),
    ("300142.SZ", "沃森生物"), ("300316.SZ", "晶盛机电"), ("300347.SZ", "泰格医药"),
    ("300408.SZ", "三环集团"), ("300413.SZ", "芒果超媒"), ("300433.SZ", "蓝思科技"),
    ("300442.SZ", "润泽科技"), ("300661.SZ", "圣邦股份"), ("300674.SZ", "宇信科技"),
    ("300751.SZ", "迈为股份"), ("300919.SZ", "中伟股份"), ("300999.SZ", "金龙鱼"),
    ("600060.SH", "海信视像"), ("600176.SH", "中国巨石"), ("600219.SH", "南山铝业"),
    ("600346.SH", "恒力石化"), ("600392.SH", "盛和资源"), ("600460.SH", "士兰微"),
    ("600486.SH", "扬农化工"), ("600516.SH", "方大炭素"), ("600600.SH", "青岛啤酒"),
    ("600699.SH", "均胜电子"), ("600741.SH", "华域汽车"), ("600745.SH", "闻泰科技"),
    ("600795.SH", "国电电力"), ("600848.SH", "上海临港"), ("600886.SH", "国投电力"),
    ("600893.SH", "航发动力"), ("600958.SH", "东方证券"), ("600989.SH", "宝丰能源"),
    ("601000.SH", "唐山港"), ("601066.SH", "中信建投"), ("601100.SH", "恒立液压"),
    ("601117.SH", "中国化学"), ("601138.SH", "工业富联"), ("601155.SH", "新城控股"),
    ("601168.SH", "西部矿业"), ("601186.SH", "中国铁建"), ("601216.SH", "君正集团"),
    ("601233.SH", "桐昆股份"), ("601238.SH", "广汽集团"), ("601555.SH", "东吴证券"),
    ("601577.SH", "长沙银行"), ("601601.SH", "中国太保"), ("601607.SH", "上海医药"),
    ("601658.SH", "邮储银行"), ("601668.SH", "中国建筑"), ("601669.SH", "中国电建"),
    ("601688.SH", "华泰证券"), ("601689.SH", "拓普集团"), ("601696.SH", "中银证券"),
    ("601800.SH", "中国交建"), ("601816.SH", "京沪高铁"), ("601818.SH", "光大银行"),
    ("601838.SH", "成都银行"), ("601878.SH", "浙商证券"), ("601881.SH", "中国银河"),
    ("601888.SH", "中国中免"), ("601898.SH", "中煤能源"), ("601899.SH", "紫金矿业"),
    ("601919.SH", "中远海控"), ("601933.SH", "永辉超市"), ("601939.SH", "建设银行"),
    ("601985.SH", "中国核电"), ("601988.SH", "中国银行"), ("601995.SH", "中金公司"),
    ("601998.SH", "中信银行"), ("603019.SH", "中科曙光"), ("603087.SH", "甘李药业"),
    ("603160.SH", "汇顶科技"), ("603501.SH", "韦尔股份"), ("603517.SH", "绝味食品"),
    ("603659.SH", "璞泰来"), ("603799.SH", "华友钴业"), ("603833.SH", "欧派家居"),
    ("603899.SH", "晨光文具"), ("603986.SH", "兆易创新"), ("688005.SH", "容百科技"),
    ("688008.SH", "澜起科技"), ("688012.SH", "中微公司"), ("688036.SH", "传音控股"),
    ("688065.SH", "凯赛生物"), ("688099.SH", "晶晨股份"), ("688111.SH", "金山办公"),
    ("688126.SH", "沪硅产业"), ("688169.SH", "石头科技"), ("688180.SH", "君实生物"),
    ("688256.SH", "寒武纪"), ("688271.SH", "联影医疗"), ("688396.SH", "华润微"),
    ("688561.SH", "奇安信"), ("688599.SH", "天合光能"), ("688981.SH", "中芯国际"),
]


_SEED_MAP: dict[str, list[tuple[str, str]]] = {
    "000300.SH": _SEED_HS300,
    "000905.SH": _SEED_CS500,
}


# ============================================================
# 东财 API(可选,在线时优先)
# ============================================================

EAST_MONEY_INDEX_URL = (
    "https://push2.eastmoney.com/api/qt/clist/get"
    "?pn=1&pz=1000&po=1&fid=f3&fields=f12,f14"
    "&fs={index_code}"
)
EAST_MONEY_INDEX_FS = {
    "000300.SH": "m:1+t:2,m:0+t:6&fs=b:%2B000300",  # HS300 (SH/SZ 两端)
    "000905.SH": "b:%2B000905",  # CS500
}


async def _fetch_east_money(index_code: str) -> list[tuple[str, str]] | None:
    """在线拉取指数成分股;失败返回 None(让调用方回退种子表)"""
    fs = EAST_MONEY_INDEX_FS.get(index_code)
    if not fs:
        return None
    url = f"https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=2000&po=1&fid=f3&fields=f12,f14&fs={fs}"
    try:
        async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
        rows = (data.get("data") or {}).get("diff") or []
        out: list[tuple[str, str]] = []
        for r in rows:
            code = r.get("f12")
            name = r.get("f14")
            if not code or not name:
                continue
            # 东财返回 sh.600519 → 转 600519.SH
            if code.startswith(("sh.", "sz.")):
                market = code.split(".")[0].upper()
                num = code.split(".")[1]
                code = f"{num}.{market}"
            elif code.isdigit() and len(code) == 6:
                # 6 位数字 → 按 6/9/0 开头判断市场
                if code.startswith(("60", "68")):
                    code = f"{code}.SH"
                else:
                    code = f"{code}.SZ"
            out.append((code, name))
        if len(out) < 50:
            logger.warning("东财 %s 返回 %d 条,可能不完整", index_code, len(out))
            return None
        return out
    except Exception as e:  # noqa: BLE001
        logger.warning("东财 %s 拉取失败,回退种子表: %s", index_code, e)
        return None


# ============================================================
# 主流程
# ============================================================


async def _seed_one(index_code: str, force: bool, seed_only: bool) -> int:
    """单个指数种子入/补库,返回实际写入行数(去重后)"""
    # 1. 拉取来源
    src = None if seed_only else await _fetch_east_money(index_code)
    src_label = "东财 API" if src else "种子表(offline 兜底)"
    raw_seed = src if src else _SEED_MAP.get(index_code, [])
    if not raw_seed:
        logger.error("%s 无数据源(种子表也未配置)", index_code)
        return 0

    # 2. seed 内部去重(种子表历史上出现过手工重复,导致 UNIQUE 冲突整批回滚)
    seen: set[str] = set()
    seed: list[tuple[str, str]] = []
    for code, name in raw_seed:
        if code in seen:
            logger.debug("[%s] 跳过 seed 内部重复: %s", index_code, code)
            continue
        seen.add(code)
        seed.append((code, name))
    logger.info("[%s] 数据源: %s,去重后候选 %d 条", index_code, src_label, len(seed))

    # 3. 落库:逐条 commit,避免单条 UNIQUE 冲突导致整批回滚
    added = 0
    async with async_session() as session:
        if force:
            from sqlalchemy import delete
            await session.execute(
                delete(IndexConstituent).where(IndexConstituent.index_code == index_code)
            )
            await session.commit()
        for code, name in seed:
            try:
                session.add(IndexConstituent(
                    index_code=index_code,
                    stock_code=code,
                    stock_name=name,
                    added_at=date.today(),
                ))
                await session.commit()
                added += 1
            except IntegrityError as _ie:
                # 已存在 (index_code, stock_code) → 跳过,不阻断后续
                await session.rollback()
                logger.debug("[%s] 已存在,跳过: %s", index_code, code)
    return added


async def main_async(force: bool, seed_only: bool) -> None:
    total = 0
    for code in SCREENER_POOL_INDEX_CODES:
        total += await _seed_one(code, force=force, seed_only=seed_only)
    logger.info("初始化完成: 共写入 %d 条", total)


def main() -> None:
    parser = argparse.ArgumentParser(description="初始化沪深300+中证500 成分股表")
    parser.add_argument("--force", action="store_true", help="清空该指数已有数据后重写")
    parser.add_argument("--seed-only", action="store_true", help="仅用种子表,不在线拉取")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(main_async(force=args.force, seed_only=args.seed_only))


if __name__ == "__main__":
    main()