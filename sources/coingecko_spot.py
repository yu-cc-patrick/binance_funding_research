"""CoinGecko 全市场现货成交量数据源。
免费端点 `/coins/{id}/market_chart?days=365` → 最近365天 daily粒度全市场聚合量(CEX+DEX)。
沙箱白名单内, 不需 auth key。
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from core.timewin import ms
from .base import DataSource

COINGECKO = "https://api.coingecko.com/api/v3"

# Binance symbol → CoinGecko coin id (手动维护)
SYM_TO_CG: dict[str, str | None] = {
    "RAVEUSDT": "ravedao",
    "AAPLUSDT": None,   # 股票永续无现货
    "MSFTUSDT": None,
}


def _sym_to_cg_id(symbol: str) -> str | None:
    if symbol in SYM_TO_CG:
        return SYM_TO_CG[symbol]
    if symbol in ("AAPLUSDT", "MSFTUSDT"):
        return None
    return symbol.replace("USDT", "").lower()


def _cg_get(url: str) -> dict | None:
    for attempt in range(3):
        try:
            req = Request(url, headers={"User-Agent": "binance-research/1.0"})
            with urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except HTTPError as e:
            if e.code == 429:
                time.sleep(2.0 * (attempt + 1))
            else:
                return None
        except Exception:
            time.sleep(1.0 * (attempt + 1))
    return None


class CoinGeckoSpotSource(DataSource):
    name = "coingecko_spot"

    def fetch(self, symbol: str, start: datetime,
              end: datetime) -> list[dict]:
        """返回 [{t: ms, vol: USDT成交额}, ...] 全市场现货量, daily粒度。"""
        cg_id = _sym_to_cg_id(symbol)
        if cg_id is None:
            return []

        lo_ms, hi_ms = ms(start), ms(end)

        # CoinGecko total_volumes 每个点都是滚动 24h 量(不论 daily 还是 1h 粒度)
        # 如果混用不同粒度会重复计数 → 只用 daily (days=365)
        # 标记 _nobucket=True 让 volume 绘图不求和、直接画
        data = _cg_get(f"{COINGECKO}/coins/{cg_id}/market_chart?vs_currency=usd&days=365")
        if not data:
            return []

        volumes = data.get("total_volumes", [])
        out = []
        for tv in volumes:
            t_ms = int(tv[0])
            vol = float(tv[1])
            if lo_ms <= t_ms <= hi_ms and vol > 0:
                # 现货量是滚动24h, 标记不对 bucket 求和
                out.append({"t": t_ms, "vol": vol, "_nobucket": True})

        out.sort(key=lambda x: x["t"])
        # 去重
        seen, ded = set(), []
        for r in out:
            if r["t"] not in seen:
                seen.add(r["t"])
                ded.append(r)
        return ded
