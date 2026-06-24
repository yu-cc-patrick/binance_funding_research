"""现货成交量数据源。从币安现货 1h K线 dump 提取成交额(USDT)。
字段: klines[7] = quote_volume(成交额), klines[5] = base_volume(币数)。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from core.dumps import months_in
from core.http import download_csv_rows
from core.timewin import ms
from .base import DataSource

# 现货月度K线URL (与合约分开)
SPOT_KLINES_M = "https://data.binance.vision/data/spot/monthly/klines/{sym}/1h/{sym}-1h-{ym}.zip"
SPOT_KLINES_D = "https://data.binance.vision/data/spot/daily/klines/{sym}/1h/{sym}-1h-{ymd}.zip"


class SpotVolumeSource(DataSource):
    name = "spot_volume"

    def fetch(self, symbol: str, start: datetime,
              end: datetime) -> list[dict]:
        """返回 [{t: ms, vol: USDT成交额, vol_coin: 币成交量}, ...] 时间升序。"""
        out = {}
        lo_ms, hi_ms = ms(start), ms(end)
        for ym in months_in(start, end):
            rows = download_csv_rows(SPOT_KLINES_M.format(sym=symbol, ym=ym))
            if rows:
                _ingest_spot(rows, out)
        # 日度补本月未发布的
        d = start.replace(hour=0, minute=0, second=0, microsecond=0)
        while d <= end:
            rows = download_csv_rows(
                SPOT_KLINES_D.format(sym=symbol, ymd=f"{d:%Y-%m-%d}"))
            if rows:
                _ingest_spot(rows, out)
            d += timedelta(days=1)
        return [{"t": t, "vol": v, "vol_coin": vc}
                for t, (v, vc) in sorted(out.items())
                if lo_ms <= t <= hi_ms]


def _ingest_spot(rows, out) -> None:
    # spot 1h kline: openTime(微秒!),o,h,l,c,base_vol,closeTime,quote_vol,...
    body = rows[1:] if rows and not rows[0][0][:4].isdigit() else rows
    for k in body:
        try:
            t_us = int(k[0])
            t_ms = t_us // 1000  # 微秒 → 毫秒
            out[t_ms] = (float(k[7]), float(k[5]))
        except (ValueError, IndexError):
            continue
