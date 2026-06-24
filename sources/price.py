"""价格数据源。从 1h klines dump（月度 + 日度）读取 OHLC，
同时提供收盘价序列（指标用）和完整 OHLC（制图用）。
"""

from __future__ import annotations

from datetime import datetime

from core.dumps import DUMP_KLINES_M, DUMP_KLINES_D, months_in, days_in
from core.http import download_csv_rows
from core.timewin import ms
from .base import DataSource


class PriceSource(DataSource):
    name = "price"

    def fetch(self, symbol: str, start: datetime,
              end: datetime) -> list[dict]:
        """
        返回 [{t: ms, o: float, h: float, l: float, c: float}, ...]
        时间升序（已去重）。
        """
        out = {}
        lo_ms, hi_ms = ms(start), ms(end)
        # 月度 dump
        for ym in months_in(start, end):
            rows = download_csv_rows(
                DUMP_KLINES_M.format(sym=symbol, ym=ym))
            if rows:
                _ingest(rows, out)
        # 日度 dump 填补月度未覆盖的日期
        have = set(out)
        for ymd in days_in(start, end):
            d0 = ms(datetime.strptime(ymd, "%Y-%m-%d").replace(
                tzinfo=start.tzinfo))
            if any(d0 <= t < d0 + 86400000 for t in have):
                continue
            rows = download_csv_rows(
                DUMP_KLINES_D.format(sym=symbol, ymd=ymd))
            if rows:
                _ingest(rows, out)
        return [{"t": t, "o": o, "h": h, "l": l, "c": c, "v": v}
                for t, (o, h, l, c, v)
                in sorted(out.items()) if lo_ms <= t <= hi_ms]

    def fetch_close(self, symbol: str, start: datetime,
                    end: datetime) -> dict[int, float]:
        """返回 {openTime_ms: close_price} 字典（指标计算用）。"""
        kl = self.fetch(symbol, start, end)
        return {k["t"]: k["c"] for k in kl}

    def fetch_ohlc(self, symbol: str, start: datetime,
                   end: datetime) -> list[tuple[int, float, float, float, float]]:
        """返回 [(t, o, h, l, c), ...]，制图用。"""
        return [(k["t"], k["o"], k["h"], k["l"], k["c"])
                for k in self.fetch(symbol, start, end)]


def _ingest(rows: list[list[str]], out: dict) -> None:
    """CSV 行 → out[t] = (o, h, l, c, v_quote_USDT)。"""
    body = rows[1:] if rows and not rows[0][0].isdigit() else rows
    for k in body:
        try:
            out[int(k[0])] = (float(k[1]), float(k[2]),
                              float(k[3]), float(k[4]),
                              float(k[7]) if len(k) > 7 else 0.0)
        except (ValueError, IndexError):
            continue
