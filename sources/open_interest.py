"""持仓量(Open Interest)数据源。从 daily metrics dump 读取
sum_open_interest(未平仓合约币数) + sum_open_interest_value(USDT 名义价值)
+ 多空比。粒度 5 分钟。

注意: 币安 metrics dump 只有 *日度* 版本且只保留近期(约几个月),
更早的日期 404 —— 用 ok_404 容错,拿不到就跳过当天。

★ 使用 ThreadPoolExecutor 并发下载,大幅缩短采集时间。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

from core.dumps import DUMP_METRICS_D
from core.http import download_csv_rows
from core.timewin import ms
from .base import DataSource

MAX_WORKERS = 12  # 并发 HTTP 请求数


class OpenInterestSource(DataSource):
    name = "open_interest"

    def fetch(self, symbol: str, start: datetime,
              end: datetime) -> list[dict]:
        """返回 [{t: ms, oi: 币数, oi_val: USDT, ls_ratio: 多空账户比}, ...]
        时间升序去重。并发下载每天的数据。"""
        lo_ms, hi_ms = ms(start), ms(end)
        out = {}
        days = []
        d = start.replace(hour=0, minute=0, second=0, microsecond=0)
        tz = d.tzinfo
        while d <= end:
            days.append(d)
            d += timedelta(days=1)

        def _fetch_day(day):
            rows = download_csv_rows(
                DUMP_METRICS_D.format(sym=symbol, ymd=f"{day:%Y-%m-%d}"))
            return day, rows

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(_fetch_day, d): d for d in days}
            for fut in as_completed(futures):
                day, rows = fut.result()
                if rows:
                    _ingest(rows, out, lo_ms, hi_ms, tz)

        return [{"t": t, **v} for t, v in sorted(out.items())]


def _ingest(rows, out, lo_ms, hi_ms, tz) -> None:
    # header: create_time, symbol, sum_open_interest, sum_open_interest_value,
    #         count_toptrader_long_short_ratio, sum_toptrader_long_short_ratio,
    #         count_long_short_ratio, sum_taker_long_short_vol_ratio
    body = rows[1:] if rows and not rows[0][0][:4].isdigit() else rows
    for r in body:
        if len(r) < 4:
            continue
        try:
            t = int(datetime.strptime(
                r[0], "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz).timestamp() * 1000)
            oi = float(r[2])
            oi_val = float(r[3])
            # 全账户多空比 (index 6)
            ls = float(r[6]) if len(r) > 6 and r[6] not in ("", None) else None
            # 大户多空比 (index 5, sum_toptrader_long_short_ratio)
            top_ls = float(r[5]) if len(r) > 5 and r[5] not in ("", None) else None
        except (ValueError, IndexError):
            continue
        if lo_ms <= t <= hi_ms:
            out[t] = {"oi": oi, "oi_val": oi_val, "ls_ratio": ls,
                      "top_ls_ratio": top_ls}
