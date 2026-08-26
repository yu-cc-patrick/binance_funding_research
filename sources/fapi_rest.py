"""币安合约 REST API 数据源 — 用于当下极端事件(月度 dump 未发布时)。
fapi.binance.com + api.binance.com, 关沙箱可用。
限制: klines 最多 1500 根, funding 最多 1000 条, OI 5min 最多 500 点(42h)。
仅适合补充最近几天的数据, 历史仍需月度 dump。
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from core.timewin import ms
from .base import DataSource


def _api_get(url: str, timeout: int = 30) -> list | dict | None:
    for attempt in range(3):
        try:
            req = Request(url, headers={"User-Agent": "binance-research/1.0"})
            with urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except HTTPError as e:
            if e.code == 429:
                time.sleep(2.0 * (attempt + 1))
            else:
                return None
        except Exception:
            time.sleep(1.0 * (attempt + 1))
    return None


class FapiFundingSource(DataSource):
    """合约资金费率 — 从 fapi.binance.com REST API。"""
    name = "funding"

    def fetch(self, symbol: str, start: datetime, end: datetime) -> list[dict]:
        raw = _api_get(
            f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={symbol}&limit=1000")
        if not raw:
            return []
        out = []
        for r in raw:
            ft = r['fundingTime']
            rate = float(r['fundingRate'])
            out.append({"t": ft, "rate": rate, "interval": 0})
        out.sort(key=lambda x: x['t'])
        # 从时间戳间隔推断 interval
        for i in range(1, len(out)):
            gap_h = round((out[i]['t'] - out[i-1]['t']) / 3600000)
            out[i]['interval'] = gap_h
        if out:
            out[0]['interval'] = out[1]['interval']
        lo_ms, hi_ms = ms(start), ms(end)
        return [r for r in out if lo_ms <= r['t'] <= hi_ms]


class FapiPriceSource(DataSource):
    """合约 1h K线 — 从 fapi.binance.com REST API。"""
    name = "price"

    def fetch(self, symbol: str, start: datetime, end: datetime) -> list[dict]:
        raw = _api_get(
            f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=1h&limit=1500")
        if not raw:
            return []
        out = [{"t": int(k[0]), "o": float(k[1]), "h": float(k[2]),
                "l": float(k[3]), "c": float(k[4]), "v": float(k[5])} for k in raw]
        lo_ms, hi_ms = ms(start), ms(end)
        return [r for r in out if lo_ms <= r['t'] <= hi_ms]


class FapiDailySource(DataSource):
    """日线 — 从 fapi.binance.com REST API (用于周线聚合)。"""
    name = "daily"
    lifetime = True

    def fetch(self, symbol: str, start: datetime, end: datetime) -> list[dict]:
        raw = _api_get(
            f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=1d&limit=500")
        if not raw:
            return []
        out = [{"t": int(k[0]), "o": float(k[1]), "h": float(k[2]),
                "l": float(k[3]), "c": float(k[4]), "v": float(k[5])} for k in raw]
        lo_ms, hi_ms = ms(start), ms(end)
        return [r for r in out if lo_ms <= r['t'] <= hi_ms]


class FapiOISource(DataSource):
    """持仓量 + 多空比 — 从 fapi REST API (5min 粒度, 仅近期)。"""
    name = "open_interest"

    def fetch(self, symbol: str, start: datetime, end: datetime) -> list[dict]:
        oi_raw = _api_get(
            f"https://fapi.binance.com/futures/data/openInterestHist?symbol={symbol}&period=5m&limit=500")
        if not oi_raw:
            return []
        # 多空比
        ls_raw = _api_get(
            f"https://fapi.binance.com/futures/data/globalLongShortAccountRatio?symbol={symbol}&period=5m&limit=500")
        ls_map = {}
        if ls_raw:
            for r in ls_raw:
                ls_map[int(r['timestamp'])] = float(r['longShortRatio'])

        out = []
        for r in oi_raw:
            t = int(r['timestamp'])
            pt = {
                "t": t,
                "oi": float(r['sumOpenInterest']),
                "oi_val": float(r['sumOpenInterestValue']),
            }
            if t in ls_map:
                pt["ls_ratio"] = ls_map[t]
                pt["top_ls_ratio"] = ls_map[t]
            out.append(pt)

        lo_ms, hi_ms = ms(start), ms(end)
        return [r for r in out if lo_ms <= r['t'] <= hi_ms]


class FapiSpotSource(DataSource):
    """币安现货 1h K线 — 从 api.binance.com REST API。"""
    name = "spot_volume"

    def fetch(self, symbol: str, start: datetime, end: datetime) -> list[dict]:
        raw = _api_get(
            f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1h&limit=1000")
        if not raw:
            return []
        out = [{"t": int(k[0]), "vol": float(k[7]),
                "vol_coin": float(k[5])} for k in raw]
        lo_ms, hi_ms = ms(start), ms(end)
        return [r for r in out if lo_ms <= r['t'] <= hi_ms]
