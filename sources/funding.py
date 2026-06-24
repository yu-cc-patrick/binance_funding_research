"""资金费率数据源。从月度 fundingRate dump 读取费率 + 结算周期（小时）。"""

from __future__ import annotations

from datetime import datetime

from core.dumps import DUMP_FUNDING, months_in
from core.http import download_csv_rows
from core.timewin import ms
from .base import DataSource


class FundingSource(DataSource):
    name = "funding"

    def fetch(self, symbol: str, start: datetime,
              end: datetime) -> list[dict]:
        """返回 [{t: ms, rate: float, interval: int_hours}, ...] 时间升序去重。"""
        lo_ms, hi_ms = ms(start), ms(end)
        out = []
        for ym in months_in(start, end):
            rows = download_csv_rows(
                DUMP_FUNDING.format(sym=symbol, ym=ym))
            if not rows:
                continue
            # header: calc_time, funding_interval_hours, last_funding_rate
            body = rows[1:] if rows and not rows[0][0].isdigit() else rows
            for r in body:
                if len(r) < 3:
                    continue
                try:
                    t = int(r[0])
                    interval = int(float(r[1])) if r[1] not in ("", None) else 0
                    rate = float(r[2])
                except (ValueError, IndexError):
                    continue
                if lo_ms <= t <= hi_ms:
                    out.append({"t": t, "rate": rate, "interval": interval})
        out.sort(key=lambda x: x["t"])
        # 去重
        seen, ded = set(), []
        for row in out:
            if row["t"] in seen:
                continue
            seen.add(row["t"])
            ded.append(row)
        return ded
