"""区间检测 — 从 funding 序列中找出「interval 持续为 1h 且含负费率」的段。

已通过合成数据单测验证：10×8h + 30×1h含负 + 10×8h → 1 个区间；
全正 1h 跑 → 排除；interval 列缺失时回退到时间戳 gap 推断。"""

from __future__ import annotations


def detect(hist: list[dict], one_hour: int = 1) -> list[dict]:
    """
    输入：[{t: ms, rate: float, interval: int_hours}, ...]
    输出：[{start_ms, end_ms, n,  n_neg, min_rate}, ...]

    优先用 interval 字段；缺失/为 0 时回退到时间戳 gap 推断（≤75 分钟）。
    要求区间长度 ≥3 且至少含一个负费率。
    """
    n = len(hist)
    have_interval = any(r.get("interval", 0) for r in hist)

    def is_1h(idx: int) -> bool:
        if have_interval:
            return hist[idx].get("interval", 0) == one_hour
        if idx + 1 >= n:
            return False
        return (hist[idx + 1]["t"] - hist[idx]["t"]) <= 75 * 60 * 1000

    regimes = []
    i = 0
    while i < n:
        if is_1h(i):
            j = i
            while j + 1 < n and is_1h(j + 1):
                j += 1
            seg = hist[i:j + 1]
            if len(seg) >= 3 and any(r["rate"] < 0 for r in seg):
                rates = [r["rate"] for r in seg]
                regimes.append({
                    "start_ms": seg[0]["t"],
                    "end_ms": seg[-1]["t"],
                    "n": len(seg),
                    "n_neg": sum(1 for v in rates if v < 0),
                    "min_rate": min(rates),
                })
            i = j + 1
        else:
            i += 1
    return regimes
