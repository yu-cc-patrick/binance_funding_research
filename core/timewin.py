"""时间工具 — 毫秒/dt 转换、三阶段窗口计算、采样网格生成。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

HOUR = timedelta(hours=1)


def ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def dt_from_ms(m: int) -> datetime:
    return datetime.fromtimestamp(m / 1000, tz=timezone.utc)


def parse_utc(s: str) -> datetime:
    """从 'YYYY-MM-DD HH:MM' 字符串解析为 UTC datetime。"""
    return datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)


def three_phase(start: datetime, end: datetime,
                pre_days: int, post_days: int,
                post_cap: datetime | None = None
                ) -> tuple[datetime, datetime, datetime]:
    """
    三阶段起止时间：
      pre:   [start - pre_days, start)
      core:  [start, end]
      post:  (end, end + post_days] （不超过 post_cap）
    返回 (pre_start, core_start, core_end, post_end)。
    """
    pre_start = start - timedelta(days=pre_days)
    post_end = end + timedelta(days=post_days)
    if post_cap and post_end > post_cap:
        post_end = post_cap
    return pre_start, start, end, post_end


def sample_grid(start: datetime, end: datetime,
                interval: timedelta) -> list[datetime]:
    """在 [start, end] 内以 interval 步长生成采样时间点列表。"""
    out, t = [], start
    while t <= end:
        out.append(t)
        t += interval
    return out
