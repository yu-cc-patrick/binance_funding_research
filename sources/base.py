"""数据源插件基类。
每个数据源实现 fetch(symbol, start, end) → list[dict] 和
可选的 align_to_grid(timestamps[], raw[]) → list[value]。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime


class DataSource(ABC):
    name: str = ""  # 子类覆盖
    lifetime: bool = False  # True=用全程窗口(上市→end)而非事件窗口

    @abstractmethod
    def fetch(self, symbol: str, start: datetime,
              end: datetime) -> list[dict]:
        """从数据转储拉取原始数据，返回 [{t: ms, ...}, ...] 时间升序。"""
        ...

    def align_to_grid(self, grid: list[int],
                      raw: list[dict]) -> list:
        """把原始数据对齐到采样网格，返回每网格点的值（或 None）。
        默认用最近的前值。子类可覆写。"""
        if not raw:
            return [None] * len(grid)
        raw_sorted = sorted(raw, key=lambda x: x["t"])
        out, ri = [], 0
        for t in grid:
            while ri + 1 < len(raw_sorted) and raw_sorted[ri + 1]["t"] <= t:
                ri += 1
            if raw_sorted[ri]["t"] <= t:
                out.append(self._extract_value(raw_sorted[ri]))
            else:
                out.append(None)
        return out

    def _extract_value(self, row: dict):
        """从原始行提取对齐值（子类覆写）。"""
        return row
