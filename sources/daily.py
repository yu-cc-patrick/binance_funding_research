"""日线全程数据源 —— 拉取该合约 *上市至今* 的 1d OHLC,
供「判断价格整体高低」用(周线图 + 历史高低点 + 近一月涨幅 + 高点市值)。

与 price 源(事件窗口 1h)区别: 本源 lifetime=True,collect 给它
全程窗口(config.window.lifetime_start → end)。周线由 plotting 聚合。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from core.dumps import DUMP_KLINES_1D_M, DUMP_KLINES_1D_D, months_in
from core.http import download_csv_rows
from core.timewin import ms
from .base import DataSource


class DailySource(DataSource):
    name = "daily"
    lifetime = True

    def fetch(self, symbol: str, start: datetime,
              end: datetime) -> list[dict]:
        """返回 [{t: ms, o,h,l,c, v(成交额USDT)}, ...] 时间升序去重。"""
        out = {}
        lo_ms, hi_ms = ms(start), ms(end)
        for ym in months_in(start, end):
            rows = download_csv_rows(DUMP_KLINES_1D_M.format(sym=symbol, ym=ym))
            if rows:
                _ingest(rows, out)
        # 日度 dump 补当月未发布部分
        have = set(out)
        d = start.replace(hour=0, minute=0, second=0, microsecond=0)
        d_end = end.replace(hour=0, minute=0, second=0, microsecond=0)
        while d <= d_end:
            d0 = ms(d)
            if not any(d0 <= t < d0 + 86400000 for t in have):
                rows = download_csv_rows(
                    DUMP_KLINES_1D_D.format(sym=symbol, ymd=f"{d:%Y-%m-%d}"))
                if rows:
                    _ingest(rows, out)
            d += timedelta(days=1)
        return [{"t": t, "o": o, "h": h, "l": l, "c": c, "v": v}
                for t, (o, h, l, c, v) in sorted(out.items())
                if lo_ms <= t <= hi_ms]


def _ingest(rows, out) -> None:
    body = rows[1:] if rows and not rows[0][0].isdigit() else rows
    for k in body:
        try:
            # klines: openTime,o,h,l,c,vol,closeTime,quoteVol,...
            out[int(k[0])] = (float(k[1]), float(k[2]), float(k[3]),
                              float(k[4]),
                              float(k[7]) if len(k) > 7 else 0.0)
        except (ValueError, IndexError):
            continue
