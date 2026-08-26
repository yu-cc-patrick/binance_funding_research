"""指标计算 — 从 dataset.json 算衍生指标 → metrics.json。
完全取决于 dataset 和 price 数据源，不依赖任何外部临时文件。"""

from __future__ import annotations

import json
import os
import sys

from core.timewin import dt_from_ms, ms, three_phase, HOUR


def run(dataset_path: str, out_dir: str) -> str:
    """返回 metrics.json 路径。"""
    ds = json.load(open(dataset_path))
    cfg = ds["config"]
    pre_d = cfg["window"]["pre_lookback_days"]
    post_d = cfg["window"]["post_horizon_days"]
    mcap_cfg = cfg.get("market_cap", {}) or {}
    circ_map = mcap_cfg.get("circulating", {}) or {}
    circ_default = mcap_cfg.get("default_circulating")

    metrics = {}
    for sym, entry in ds["matches"].items():
        price_raw = entry["raw"].get("price", [])
        price_map = {k["t"]: k["c"] for k in price_raw}
        pts = sorted(price_map)

        # ---- 全程高低位判断(基于日线) ----
        daily = entry["raw"].get("daily", [])
        oi_raw = entry["raw"].get("open_interest", [])
        market = _market_position(daily, circ_map.get(sym, circ_default), oi_raw)
        if market:
            market["circulating"] = circ_map.get(sym, circ_default)

        sym_m = []
        for reg in entry["regimes"]:
            start = dt_from_ms(reg["start_ms"])
            end = dt_from_ms(reg["end_ms"])
            _, _, _, post_end = three_phase(start, end, pre_d, post_d)

            def px(dt):
                t = ms(dt)
                best = None
                for pt in pts:
                    if pt <= t:
                        best = price_map[pt]
                    else:
                        break
                return best if best is not None else (price_map[pts[0]] if pts else None)

            p_start = px(start)
            p_end = px(end)
            if p_start and p_end:
                chg_in = round((p_end / p_start - 1) * 100, 1)
            else:
                chg_in = None

            # post 段价格极值
            post_prices = [price_map[pt] for pt in pts
                           if ms(end) < pt <= ms(post_end)]
            p_min = round((min(post_prices) / p_end - 1) * 100, 1) if post_prices and p_end else None
            p_max = round((max(post_prices) / p_end - 1) * 100, 1) if post_prices and p_end else None
            p_last_v = px(post_end)
            p_last = round((p_last_v / p_end - 1) * 100, 1) if p_last_v and p_end else None

            # 累计负费率
            fund = entry["raw"].get("funding", [])
            seg = [r for r in fund
                   if reg["start_ms"] <= r["t"] <= reg["end_ms"]]
            cum_neg = round(sum(r["rate"] for r in seg if r["rate"] < 0) * 100, 3)

            # 区间内 OI 变化(USDT 名义价值)
            oi = entry["raw"].get("open_interest", [])
            oi_seg = [r for r in oi if reg["start_ms"] <= r["t"] <= reg["end_ms"]]
            oi_chg = None
            if len(oi_seg) >= 2 and oi_seg[0]["oi_val"]:
                oi_chg = round((oi_seg[-1]["oi_val"] / oi_seg[0]["oi_val"] - 1) * 100, 1)

            sym_m.append({
                **reg,
                "start_str": str(start),
                "end_str": str(end),
                "chg_in_1h_pct": chg_in,
                "post_min_chg": p_min,
                "post_max_chg": p_max,
                "post_last_chg": p_last,
                "cum_neg_pct": cum_neg,
                "oi_chg_in_pct": oi_chg,
            })

        if sym_m:
            metrics[sym] = {"regimes": sym_m, "market": market}

    path = os.path.join(out_dir, "metrics.json")
    json.dump(metrics, open(path, "w"), indent=1, default=str)
    print(f"saved {path}  ({len(metrics)} symbols)", file=sys.stderr)
    return path


def _market_position(daily: list, circulating, oi_data: list | None = None) -> dict | None:
    """从全程日线判断价格整体处于高位还是低位。
    返回 {ath, atl, last, from_ath_pct, range_pos_pct, chg_30d_pct,
          mcap_last, mcap_ath, oi_peak_coin, oi_pct_circ, verdict}。"""
    if not daily:
        return None
    ath = max(k["h"] for k in daily)
    atl = min(k["l"] for k in daily)
    last = daily[-1]["c"]
    from_ath = round((last / ath - 1) * 100, 1) if ath else None
    # 在全程 [低,高] 区间的相对位置 (0%=历史最低, 100%=历史最高)
    rng = (ath - atl) or 1e-9
    range_pos = round((last - atl) / rng * 100, 1)
    # 近 30 日(自然日)涨幅
    last_t = daily[-1]["t"]
    ref = None
    for k in daily:
        if k["t"] <= last_t - 30 * 86400000:
            ref = k["c"]
    chg_30d = round((last / ref - 1) * 100, 1) if ref else None

    out = {
        "ath": round(ath, 4), "atl": round(atl, 6),
        "last": round(last, 4),
        "from_ath_pct": from_ath, "range_pos_pct": range_pos,
        "chg_30d_pct": chg_30d,
    }
    if circulating:
        out["mcap_last"] = round(last * circulating / 1e6, 1)   # 百万美元
        out["mcap_ath"] = round(ath * circulating / 1e6, 1)
    # OI 币本位峰值与流通占比（用于判断合约杠杆集中度）
    if oi_data and circulating:
        oi_peaks_coin = [r.get("oi", 0) for r in oi_data if r.get("oi")]
        if oi_peaks_coin:
            out["oi_peak_coin"] = int(max(oi_peaks_coin))
            out["oi_pct_circ"] = round(out["oi_peak_coin"] / circulating * 100, 2)
    # 高低位裁定: 综合距高点 + 区间位置
    if range_pos >= 70:
        out["verdict"] = "高位"
    elif range_pos >= 35:
        out["verdict"] = "中位"
    else:
        out["verdict"] = "低位"
    return out

