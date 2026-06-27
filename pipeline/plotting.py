"""制图 — 从 dataset.json + metrics.json + config/annotations/*.yaml 生成多维图。

布局(每个 regime 一张):
  行1 通栏  : 周线全程图 · 历史高低点 + 高点市值 + 高低位裁定
  行2 双栏  : 价格 K 线 · 策略点位标注 + 阶段叙事文字(OI+费率)
  行3 双栏  : OI 柱 USDT 名义价值
  行4 双栏  : OI 柱 币本位(张数)
  行5 双栏  : 资金费率 柱
  底部表格 : 策略评分(当时分 vs 事后分)

沙箱限制: 联网采集与出图需关沙箱运行(代理截断 >100B body)。"""

from __future__ import annotations

import json
import math
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Patch
from matplotlib import font_manager
from datetime import datetime, timedelta, timezone

from core.timewin import dt_from_ms, ms, three_phase, HOUR

# ---- 字体 ----
for _fp in ("/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
            "/System/Library/Fonts/Hiragino Sans GB.ttc"):
    if os.path.exists(_fp):
        try:
            font_manager.fontManager.addfont(_fp)
            plt.rcParams["font.family"] = \
                font_manager.FontProperties(fname=_fp).get_name()
            break
        except Exception:
            continue
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["svg.fonttype"] = "none"    # 文字保留为 <text> 元素, Inkscape 可编辑

GREEN, RED, GREY = "#2ca02c", "#d62728", "#888"


# ══════════════════════════════════════════════════════════════════
# 工具
# ══════════════════════════════════════════════════════════════════

def _aggregate_weekly(daily: list) -> list:
    """日线 [{t,o,h,l,c,v}] 聚合成周线(ISO 周一为界)。"""
    if not daily:
        return []
    buckets = {}
    for k in sorted(daily, key=lambda x: x["t"]):
        dt = dt_from_ms(k["t"])
        monday = dt - timedelta(days=dt.weekday())
        wk = ms(monday.replace(hour=0, minute=0, second=0, microsecond=0))
        b = buckets.get(wk)
        if b is None:
            buckets[wk] = {"t": wk, "o": k["o"], "h": k["h"],
                           "l": k["l"], "c": k["c"], "v": k.get("v", 0)}
        else:
            b["h"] = max(b["h"], k["h"])
            b["l"] = min(b["l"], k["l"])
            b["c"] = k["c"]
            b["v"] += k.get("v", 0)
    return [buckets[w] for w in sorted(buckets)]


def _to_num(m): return mdates.date2num(dt_from_ms(m))


def _bands(ax, bands):
    for b0, b1, c, _ in bands:
        ax.axvspan(mdates.date2num(b0), mdates.date2num(b1),
                   color=c, alpha=0.7, zorder=0)


def _stat_segment(data, lo_ms, hi_ms, key):
    """区间内 data[{key}] 的 (首, 尾, 首→尾变化%, 均值, 最小, 最大)。"""
    seg = [r for r in data if lo_ms <= r["t"] <= hi_ms]
    if not seg:
        return None, None, None, None, None, None
    vals = [r[key] for r in seg if r.get(key) is not None]
    if not vals:
        return None, None, None, None, None, None
    chg = round((vals[-1] / vals[0] - 1) * 100, 1) if vals[0] else None
    return (vals[0], vals[-1], chg,
            round(sum(vals) / len(vals), 4),
            round(min(vals), 4),
            round(max(vals), 4))


# ══════════════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════════════

def run(dataset_path: str, annotations_dir: str, out_dir: str,
        metrics_path: str | None = None, plot_overrides: dict | None = None):
    import yaml
    ds = json.load(open(dataset_path))
    cfg = ds["config"]
    # 应用 CLI 覆盖 (prefix, show_structure 等)
    if plot_overrides:
        cfg.setdefault("plot", {}).update(plot_overrides)
    pre_d = cfg["window"]["pre_lookback_days"]
    post_d = cfg["window"]["post_horizon_days"]
    mt = json.load(open(metrics_path)) if metrics_path and \
        os.path.exists(metrics_path) else {}

    for sym, entry in ds["matches"].items():
        ann_path = os.path.join(annotations_dir, f"{sym}.yaml")
        annot = yaml.safe_load(open(ann_path)) if os.path.exists(ann_path) else {}

        price_data = entry["raw"].get("price", [])
        fund_data = entry["raw"].get("funding", [])
        oi_data = entry["raw"].get("open_interest", [])
        daily_data = entry["raw"].get("daily", [])
        if not price_data:
            continue
        kl = sorted((k["t"], k["o"], k["h"], k["l"], k["c"]) for k in price_data)
        weekly = _aggregate_weekly(daily_data)
        market = (mt.get(sym, {}) or {}).get("market") if mt else None

        for ri, reg in enumerate(entry["regimes"]):
            start = dt_from_ms(reg["start_ms"])
            end = dt_from_ms(reg["end_ms"])
            pre0, _, _, post1 = three_phase(start, end, pre_d, post_d)
            zoom0 = start - timedelta(hours=4)
            zoom1 = end + timedelta(hours=4)
            bands = [(pre0, start, "#d8e8ff", "pre · 4h结算"),
                     (start, end, "#ffe1e1", "1h 区间"),
                     (end, post1, "#ddf5e1", "post · 恢复4h")]

            # 7行网格. 右栏结构分析可选(config.plot.show_structure)
            show_struct = cfg.get("plot", {}).get("show_structure", False)
            if show_struct:
                fig = plt.figure(figsize=(42, 24))
                gs_right = 0.48
            else:
                fig = plt.figure(figsize=(22, 24))
                gs_right = 0.97
            gs = fig.add_gridspec(
                7, 2, height_ratios=[2.0, 2.8, 1.0, 1.0, 1.0, 0.8, 1.0],
                width_ratios=[3, 2], hspace=0.28, wspace=0.12,
                left=0.05, right=gs_right)
            axW  = fig.add_subplot(gs[0, :])
            axP  = fig.add_subplot(gs[1, 0])
            axPz = fig.add_subplot(gs[1, 1])
            axOu  = fig.add_subplot(gs[2, 0], sharex=axP)
            axOuz = fig.add_subplot(gs[2, 1], sharex=axPz)
            axOb  = fig.add_subplot(gs[3, 0], sharex=axP)
            axObz = fig.add_subplot(gs[3, 1], sharex=axPz)
            axV  = fig.add_subplot(gs[4, 0], sharex=axP)
            axVz = fig.add_subplot(gs[4, 1], sharex=axPz)
            axL  = fig.add_subplot(gs[5, 0], sharex=axP)
            axLz = fig.add_subplot(gs[5, 1], sharex=axPz)
            axF  = fig.add_subplot(gs[6, 0], sharex=axP)
            axFz = fig.add_subplot(gs[6, 1], sharex=axPz)

            _draw_weekly(axW, weekly, market, sym, start, end)

            kl_zoom = [k for k in kl if ms(zoom0) <= k[0] <= ms(zoom1)]
            loP, hiP = ms(pre0), ms(post1)
            loZ, hiZ = ms(zoom0), ms(zoom1)

            # 价格
            _draw_price(axP, kl, bands, pre0, post1)
            _draw_price(axPz, kl_zoom, bands, zoom0, zoom1)

            # OI USDT (全景4h重采样, 放大1h重采样)
            _draw_oi(axOu, oi_data, bands, pre0, post1, "oi_val",
                     "持仓量 USDT\n(百万)", resample_hours=4)
            _draw_oi(axOuz, oi_data, bands, zoom0, zoom1, "oi_val",
                     "持仓量 USDT\n(百万)", resample_hours=1)
            # OI 币本位
            _draw_oi(axOb, oi_data, bands, pre0, post1, "oi",
                     "持仓量 币本位\n(百万枚)", resample_hours=4)
            _draw_oi(axObz, oi_data, bands, zoom0, zoom1, "oi",
                     "持仓量 币本位\n(百万枚)", resample_hours=1)

            # 成交量 (合约+现货)
            cvol_data = entry["raw"].get("price", [])  # 含v字段
            svol_data = entry["raw"].get("spot_volume", [])
            _draw_volume(axV, cvol_data, svol_data, bands, pre0, post1, 4)
            _draw_volume(axVz, cvol_data, svol_data, bands, zoom0, zoom1, 1)

            # 大户多空比
            _draw_ls_ratio(axL, oi_data, bands, pre0, post1, 4)
            _draw_ls_ratio(axLz, oi_data, bands, zoom0, zoom1, 1)

            # 费率
            _draw_funding(axF, fund_data, bands, pre0, post1, True)
            _draw_funding(axFz, fund_data, bands, zoom0, zoom1, False)

            # 标注
            _annotate(axP, kl, annot.get("panorama", []), loP, hiP, 1.75)
            _annotate(axPz, kl_zoom, annot.get("zoom", []), loZ, hiZ, 1.42)
            _mark_strategy(axP, kl, annot.get("strategy", []), loP, hiP)
            # 阶段叙事 → 独立表格(不标在图上, 避免遮挡)

            axP.set_title(f"{sym} 价格全景 (pre → 1h区间 → post), 阶段叙事",
                          fontsize=11)
            axPz.set_title(f"1h 区间放大 ({start:%m-%d %H:%M}→{end:%m-%d %H:%M} UTC, {reg['n']}次)",
                           fontsize=11)
            _price_legend(axP, bands, annot)
            _bottom_tables(fig, annot.get("phases", []), annot.get("strategy", []))

            # 右栏: 每阶段结构分析 (可选, 由 config.plot.show_structure 控制)
            show_structure = cfg.get("plot", {}).get("show_structure", False)
            if show_structure:
                from pipeline.structure import analyze_window
                structs = []
                phase_times = []
                for ev in annot.get("panorama", []):
                    txt = ev.get("text", "").strip()
                    if txt and txt[0] == "P" and len(txt) >= 2 and txt[1].isdigit():
                        try:
                            t = datetime.strptime(ev["time"], "%Y-%m-%d %H:%M")
                            t = t.replace(tzinfo=timezone.utc)
                            phase_times.append((t, txt.split()[0], txt))
                        except (ValueError, KeyError):
                            continue
                phase_times.sort(key=lambda x: x[0])
                if len(phase_times) >= 2:
                    for i in range(len(phase_times)):
                        label = phase_times[i][1]
                        t0 = phase_times[i][0]
                        t1 = (phase_times[i + 1][0] if i + 1 < len(phase_times)
                              else t0 + timedelta(days=7))
                        if (t1 - t0).total_seconds() < 3600:
                            continue
                        try:
                            r = analyze_window(entry["raw"], (ms(t0), ms(t1)))
                            r["band_label"] = f"{label} {phase_times[i][2][:30]}"
                            structs.append(r)
                        except Exception:
                            continue
                else:
                    for b0, b1, _, label in bands:
                        r = analyze_window(entry["raw"], (ms(b0), ms(b1)))
                        r["band_label"] = label
                        structs.append(r)
                _render_structure(fig, structs)

            fig.suptitle(f"{sym} — 资金费率 1h+负费率事件 · 多维分析",
                         fontsize=17, y=0.997)

            os.makedirs(out_dir, exist_ok=True)
            prefix = cfg.get("plot", {}).get("filename_prefix", "")
            stem = f"{prefix}{sym}"
            # PNG
            path_png = os.path.join(out_dir, f"{stem}.png")
            fig.savefig(path_png, dpi=120, bbox_inches="tight")
            # SVG — Inkscape 可编辑(文字为真实 text 元素, gid 可定位)
            path_svg = os.path.join(out_dir, f"{stem}.svg")
            fig.savefig(path_svg, format="svg", bbox_inches="tight")
            plt.close(fig)
            print(f"saved {stem}.png + .svg", file=sys.stderr)


# ══════════════════════════════════════════════════════════════════
# 各行绘制
# ══════════════════════════════════════════════════════════════════

def _draw_weekly(ax, weekly, market, sym, ev_start, ev_end):
    """周线全程图: K线 + 历史高低点 + 高点市值 + 高低位裁定 + 事件位置标记。"""
    if not weekly:
        ax.text(0.5, 0.5, "无日线数据", ha="center", transform=ax.transAxes)
        return
    w = 5.0
    for k in weekly:
        x = _to_num(k["t"]) + 3.5
        col = GREEN if k["c"] >= k["o"] else RED
        ax.plot([x, x], [k["l"], k["h"]], color=col, lw=1.0, zorder=2)
        ax.add_patch(plt.Rectangle(
            (x - w / 2, min(k["o"], k["c"])), w,
            max(abs(k["c"] - k["o"]), 1e-9),
            facecolor=col, edgecolor=col, lw=0.5, zorder=3))
    ax.axvspan(mdates.date2num(ev_start), mdates.date2num(ev_end),
               color="#ffd0d0", alpha=0.5, zorder=0)
    if market:
        ath, last = market["ath"], market["last"]
        ax.axhline(ath, color="#c0392b", ls="--", lw=1.0, alpha=0.7, zorder=1)
        ax.axhline(last, color="#1a73e8", ls=":", lw=1.0, alpha=0.7, zorder=1)
        x_lo = _to_num(weekly[0]["t"])
        ax.text(x_lo, ath, f" 历史高 {ath:g}", color="#c0392b",
                va="bottom", fontsize=8.5)
        ax.text(x_lo, last, f" 现价 {last:g}", color="#1a73e8",
                va="bottom", fontsize=8.5)
        mc = (f"高点市值 {market.get('mcap_ath','?')}M → "
              f"现 {market.get('mcap_last','?')}M\n"
              if market.get("mcap_ath") else "")
        circ = market.get("circulating")
        circ_s = f"(流通≈{circ/1e6:g}M枚)" if circ else "(无流通量,仅价格)"
        verdict = market.get("verdict", "?")
        vcol = {"高位": "#c0392b", "中位": "#e08a00",
                "低位": "#2ca02c"}.get(verdict, "#333")
        txt = (f"整体: {verdict}\n"
               f"距高点 {market.get('from_ath_pct','?')}%\n"
               f"区间位置 {market.get('range_pos_pct','?')}%\n"
               f"近30日 {market.get('chg_30d_pct','?')}%\n"
               f"{mc}{circ_s}")
        ax.text(0.995, 0.96, txt, transform=ax.transAxes, ha="right",
                va="top", fontsize=9, zorder=10,
                bbox=dict(boxstyle="round,pad=0.5", fc="#fffbe6",
                          ec=vcol, lw=1.8, alpha=0.96))
    ax.set_title(f"{sym} 周线全程 (上市→现在) · 判断价格整体高低位",
                 fontsize=11.5, fontweight="bold")
    ax.set_ylabel("价格 (USDT)")
    ax.grid(True, axis="y", alpha=0.25)
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))


def _draw_price(ax, kl, bands, x0, x1):
    to_num = _to_num
    w = (1.0 / 24) * 0.7
    _bands(ax, bands)
    for t, o, h, l, c in kl:
        x = to_num(t)
        col = GREEN if c >= o else RED
        ax.plot([x, x], [l, h], color=col, linewidth=0.6, zorder=2)
        ax.add_patch(plt.Rectangle(
            (x - w / 2, min(o, c)), w, max(abs(c - o), 1e-9),
            facecolor=col, edgecolor=col, linewidth=0.4, zorder=3))
    ax.set_ylabel("价格 (USDT)")
    ax.grid(True, axis="y", alpha=0.25)
    ax.set_xlim(to_num(ms(x0)), to_num(ms(x1)))


def _draw_oi(ax, oi, bands, x0, x1, field, ylabel, resample_hours=1):
    """持仓量柱状图。field='oi_val'=USDT, 'oi'=币数。颜色绿增红减。
    OI原始5min粒度太密,按resample_hours重采样后画柱。"""
    to_num = _to_num
    _bands(ax, bands)
    lo, hi = ms(x0), ms(x1)
    seg = [r for r in oi if lo <= r["t"] <= hi]
    if not seg:
        return
    # 按 resample_hours 分桶,每桶取末值
    bucket_ms = resample_hours * 3600_000
    buckets = {}
    for r in sorted(seg, key=lambda x: x["t"]):
        bk = (r["t"] // bucket_ms) * bucket_ms
        buckets[bk] = r[field]
    bk_ts = sorted(buckets)
    if not bk_ts:
        return
    w = (to_num(hi) - to_num(lo)) / max(len(bk_ts), 1) * 0.85
    scale = 1e6  # → 百万
    prev = None
    for t in bk_ts:
        val = buckets[t] / scale
        col = GREY if prev is None else (GREEN if val >= prev else RED)
        ax.bar(to_num(t), val, width=w, color=col, alpha=0.8, zorder=2)
        prev = val
    ax.set_ylabel(ylabel)
    ax.grid(True, axis="y", alpha=0.25)
    ax.set_xlim(to_num(lo), to_num(hi))


def _draw_funding(ax, fund, bands, x0, x1, full):
    to_num = _to_num
    w = (1.0 / 24) * (0.7 if full else 0.8)
    _bands(ax, bands)
    lo, hi = ms(x0), ms(x1)
    for r in fund:
        if not (lo <= r["t"] <= hi):
            continue
        pct = r["rate"] * 100
        col = RED if pct < 0 else GREEN
        ax.bar(to_num(r["t"]), pct, width=w, color=col, zorder=2)
    ax.axhline(0, color="#333", linewidth=0.8)
    ax.set_ylabel("资金费率 %")
    ax.grid(True, axis="y", alpha=0.25)
    ax.set_xlim(to_num(lo), to_num(hi))
    if full:
        ax.xaxis.set_major_locator(mdates.DayLocator(interval=3))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    else:
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=4))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %Hh"))
    for lab in ax.get_xticklabels():
        lab.set_rotation(30)
        lab.set_ha("right")


def _draw_volume(ax, cvol, svol, bands, x0, x1, resample_hours):
    """成交量柱状图: 合约(左轴·蓝) + 现货(右轴·橙), 按resample_hours分桶。"""
    to_num = _to_num
    _bands(ax, bands)
    lo, hi = ms(x0), ms(x1)
    bucket_ms = resample_hours * 3600_000
    cv_buckets = {}
    for k in cvol:
        if lo <= k["t"] <= hi:
            bk = (k["t"] // bucket_ms) * bucket_ms
            cv_buckets[bk] = cv_buckets.get(bk, 0) + k.get("v", 0)
    sv_buckets = {}
    for s in svol:
        if lo <= s["t"] <= hi:
            bk = (s["t"] // bucket_ms) * bucket_ms
            sv_buckets[bk] = sv_buckets.get(bk, 0) + s.get("vol", 0)
    all_bk = sorted(set(cv_buckets) | set(sv_buckets))
    if not all_bk:
        return
    scale = 1e6
    w = (to_num(hi) - to_num(lo)) / max(len(all_bk), 1) * 0.85
    ax_s = ax.twinx()  # 右轴给现货
    for bk in all_bk:
        cv = cv_buckets.get(bk, 0) / scale
        sv = sv_buckets.get(bk, 0) / scale
        x = to_num(bk)
        if cv > 0:
            ax.bar(x, cv, width=w, color="#6a9fb5", alpha=0.6, zorder=3)
        if sv > 0:
            ax_s.bar(x, sv, width=w * 0.6, color="#e67e22", alpha=0.7, zorder=4)
    ax.set_ylabel("合约量\n(百万 USDT)", color="#4a7a9a")
    ax_s.set_ylabel("现货量\n(百万 USDT)", color="#c06014")
    ax_s.tick_params(axis="y", colors="#c06014")
    ax.grid(True, axis="y", alpha=0.2)
    ax.set_xlim(to_num(lo), to_num(hi))
    from matplotlib.patches import Patch
    ax.legend(handles=[
        Patch(fc="#6a9fb5", alpha=0.6, label="合约(左轴)"),
        Patch(fc="#e67e22", alpha=0.7, label="现货(右轴)")],
        loc="upper left", fontsize=7, framealpha=0.8)


def _draw_ls_ratio(ax, oi, bands, x0, x1, resample_hours):
    """大户多空比(top_ls_ratio)折线图, 1.0=中性线。"""
    to_num = _to_num
    _bands(ax, bands)
    lo, hi = ms(x0), ms(x1)
    bucket_ms = resample_hours * 3600_000
    buckets = {}
    for r in oi:
        if not (lo <= r["t"] <= hi):
            continue
        v = r.get("top_ls_ratio")
        if v is None:
            continue
        bk = (r["t"] // bucket_ms) * bucket_ms
        buckets[bk] = v  # 取末值
    if not buckets:
        ax.text(0.5, 0.5, "无大户多空比数据", ha="center", transform=ax.transAxes)
        return
    bts = sorted(buckets)
    xs = [to_num(t) for t in bts]
    ys = [buckets[t] for t in bts]
    ax.plot(xs, ys, color="#8e44ad", linewidth=1.2, zorder=3)
    ax.axhline(1.0, color="#555", ls="--", lw=0.8, alpha=0.5)
    ax.fill_between(xs, 1.0, ys, where=[y >= 1.0 for y in ys],
                    color=GREEN, alpha=0.12)
    ax.fill_between(xs, 1.0, ys, where=[y < 1.0 for y in ys],
                    color=RED, alpha=0.12)
    ax.set_ylabel("大户多空比\n(>1=净多)")
    ax.grid(True, axis="y", alpha=0.25)
    ax.set_xlim(to_num(lo), to_num(hi))


# ══════════════════════════════════════════════════════════════════
# 标注与策略
# ══════════════════════════════════════════════════════════════════

def _phase_narrative(fig, ax, price_data, oi_data, fund_data,
                     bands, x0, x1):
    """在价格全景图上标阶段叙事文字——纯逻辑,不吐数据。
    根据每阶段 OI(币本位)+费率+价格方向自动生成描述。"""
    p_map = {k["t"]: k["c"] for k in price_data}
    pts = sorted(p_map)
    if not pts:
        return

    lo, hi = ms(x0), ms(x1)
    y_bot = min(p_map[t] for t in pts if lo <= t <= hi)
    y_top = max(p_map[t] for t in pts if lo <= t <= hi)
    span = y_top - y_bot or 1.0

    for phase_idx, (b0, b1, _, label) in enumerate(bands):
        b0m, b1m = ms(b0), ms(b1)
        p_seg = [p_map[t] for t in pts if b0m <= t <= b1m]
        if not p_seg:
            continue
        p_chg = (p_seg[-1] / p_seg[0] - 1) if p_seg[0] else 0

        # OI 币本位(判断仓位真实变化的核心指标)
        _, _, oic_chg, _, _, _ = _stat_segment(oi_data, b0m, b1m, "oi")
        # OI USDT
        _, _, oiu_chg, _, _, _ = _stat_segment(oi_data, b0m, b1m, "oi_val")
        # 费率
        fund_seg = [r["rate"] for r in fund_data if b0m <= r["t"] <= b1m]
        fr_neg_n = sum(1 for r in fund_seg if r < 0)
        fr_any_neg = any(r < 0 for r in fund_seg) if fund_seg else False

        # 根据数据特征生成纯叙事,不写具体数字
        narrative = _build_narrative(label, p_chg, oic_chg, oiu_chg,
                                     fr_any_neg, fr_neg_n, len(fund_seg))

        x_center = mdates.date2num(b0 + (b1 - b0) / 2)
        y_text = y_bot + span * (0.06 + phase_idx * 0.14)
        bgc = {"pre · 4h结算": "#e8f0fe", "1h 区间": "#ffe8e8",
               "post · 恢复4h": "#e6f5ea"}.get(label, "#f8f8f8")
        ec_col = {"pre · 4h结算": "#3a6ea5", "1h 区间": "#b33",
                  "post · 恢复4h": "#2d7a3a"}.get(label, "#555")
        ax.text(x_center, y_text, narrative, ha="center",
                va="bottom", fontsize=8.5, zorder=20,  # zorder 确保不被K线挡
                bbox=dict(boxstyle="round,pad=0.6", fc=bgc,
                          ec=ec_col, lw=1.5, alpha=0.97),
                gid=f"phase-{label.replace(' ','_')}")  # SVG gid for Inkscape


def _build_narrative(label, p_chg, oic_chg, oiu_chg,
                     fr_any_neg, fr_neg_n, fr_total):
    """根据数据特征生成纯叙事文本,不暴露数字。"""
    if label == "pre · 4h结算":
        if p_chg > 0.05:
            return "pre · 上涨中\n正常4h结算\n费率随行就市"
        elif p_chg < -0.05:
            return "pre · 已开始下跌\n费率尚未异常\n市场正常运转"
        else:
            return "pre · 横盘整理\n常规4h结算\n费率平稳"
    elif label == "1h 区间":
        parts = ["1h 区间 · 极端事件"]
        if oic_chg is not None and oic_chg > 0.05:
            parts.append("币本位OI反增→做空资金大量涌入")
        elif oic_chg is not None and oic_chg < -0.15:
            parts.append("币本位OI锐减→持仓被迫出清")
        if p_chg < -0.3:
            parts.append("价格崩塌式下跌")
        elif p_chg < -0.1:
            parts.append("价格持续承压")
        elif p_chg > 0.1:
            parts.append("触底后强力反弹")
        if fr_any_neg and fr_total > 0 and fr_neg_n > fr_total * 0.5:
            parts.append("费率持续为负→逼空压力积聚")
        elif fr_any_neg:
            parts.append("费率转负→恐慌做空情绪")
        return "\n".join(parts)
    elif label == "post · 恢复4h":
        parts = ["post · 恢复期"]
        if p_chg > 0.1:
            parts.append("价格反弹回升")
        elif p_chg < -0.1:
            parts.append("跌势延续,抄底被套")
        else:
            parts.append("价格低位盘整")
        if oic_chg is not None and oic_chg < -0.2:
            parts.append("币本位OI持续下降→空头逐步平仓")
        elif oic_chg is not None and oic_chg > 0.1:
            parts.append("币本位OI回升→新资金重新进场")
        if fr_any_neg:
            parts.append("费率一度仍负→余波未平")
        else:
            parts.append("费率恢复正常→情绪出清")
        return "\n".join(parts)
    return label


def _mark_strategy(ax, kl, strat, x0, x1):
    """在价格全景图标出入场(▲绿)/出场(▼橙)点位 + 核心逻辑标签。
    只标叙事逻辑,不堆数据。添加 gid 供 Inkscape 定位。"""
    if not strat or not kl:
        return
    series = {t: (o, h, l, c) for t, o, h, l, c in kl}
    times = sorted(series)
    for i, ev in enumerate(strat):
        dt = datetime.strptime(ev["time"], "%Y-%m-%d %H:%M").replace(
            tzinfo=timezone.utc)
        m = ms(dt)
        if not (x0 <= m <= x1):
            continue
        x = mdates.date2num(dt)
        y = ev.get("price") or series[min(times, key=lambda t: abs(t - m))][3]
        is_in = ev.get("side", "long_in") == "long_in"
        mk, mcol, voff = ("^", "#1b8a3a", -1) if is_in else ("v", "#e07b00", 1)
        gid_base = f"strat-{ev.get('label','').replace(' ','_')}"

        # 标记点
        ax.scatter([x], [y], marker=mk, s=200, c=mcol,
                   edgecolors="white", linewidths=1.5, zorder=25,
                   gid=gid_base)

        # 核心逻辑(取 reason 第一句, 纯叙事)
        reason = ev.get("reason", "")
        core = reason.split("。")[0].strip() if reason else ""
        score_line = (f"当时{ev.get('score_live','?')}/10"
                      f" · 事后{ev.get('score_actual','?')}/10")
        label_full = f"{ev.get('label','')}  {score_line}\n{core}"

        ax.annotate(label_full, xy=(x, y), xytext=(0, voff * 52),
                    textcoords="offset points", ha="center",
                    va="bottom" if voff > 0 else "top", fontsize=8,
                    zorder=25, color="#222", fontweight="bold",
                    gid=f"{gid_base}-label",
                    bbox=dict(boxstyle="round,pad=0.4",
                              fc="#eafbea" if is_in else "#fff2e0",
                              ec=mcol, lw=1.4, alpha=0.98))


def _price_legend(ax, bands, annot):
    leg = [Patch(facecolor=c, label=lab) for _, _, c, lab in bands]
    if annot.get("panorama"):
        leg += [Patch(fc="#e8f0fe", ec="#1a73e8", label="逻辑/结构"),
                Patch(fc="#fdecea", ec="#c0392b", label="新闻/事件")]
    if annot.get("strategy"):
        leg += [plt.Line2D([], [], marker="^", color="w",
                           markerfacecolor="#1b8a3a", markersize=11,
                           label="做多入场"),
                plt.Line2D([], [], marker="v", color="w",
                           markerfacecolor="#e07b00", markersize=11,
                           label="做多出场")]
    ax.legend(handles=leg, loc="upper left", framealpha=0.9, fontsize=8, ncol=2)


def _bottom_tables(fig, phases, strat):
    """图底部阶段详解 + 策略评分, 合并为一个文本块避免重叠。"""
    lines = []
    if phases:
        lines.append("━━━ 阶段详解 ━━━")
        for ph in phases:
            lines.append(f"  {ph.get('label','')}  {ph.get('period','')}")
            lines.append(f"     {ph.get('narrative','').strip()}")
    if strat:
        lines.append("")
        lines.append("━━━ 策略评分 (满分10 · 当时=决策时合理性 / 事后=真实价格验证) ━━━")
        for ev in strat:
            side = "入" if ev.get("side") == "long_in" else "出"
            lines.append(
                f"  [{side}] {ev.get('label','?')} @ {ev.get('price','?')}  "
                f"当时 {ev.get('score_live','?')} · 事后 {ev.get('score_actual','?')}")
    if not lines:
        return
    # y=0 是图底部, 负值往下。用 va=top 确保所有文字在图下方。
    fig.text(0.008, -0.006, "\n".join(lines), ha="left", va="top",
             fontsize=7.8, wrap=True, linespacing=1.25,
             bbox=dict(boxstyle="round,pad=0.5", fc="#fcfcfc",
                       ec="#bbb", lw=0.8))


def _render_structure(fig, structs):
    """右栏渲染市场结构分析——连续文本块, 每阶段用 P1▸ 标记隔开, 无框无分隔线。"""
    if not structs:
        return
    # 拼接所有阶段的叙事为一段连续文本
    parts = []
    for st in structs:
        label = st.get("band_label", "?")
        parts.append(f"【{label}】")
        parts.append(st.get("narrative", ""))
        parts.append("")  # 空行隔开
    full_text = "\n".join(parts).strip()

    fig.text(0.55, 0.97, full_text,
             fontsize=5.5, ha="left", va="top",
             color="#333", linespacing=1.15, wrap=True)


def _annotate(ax, kl, events, x0, x1, top_frac):
    """标注事件文本框 + 箭头。纯叙事,不标数据。gid 供 Inkscape 编辑。"""
    if not events:
        return
    series = {t: (o, h, l, c) for t, o, h, l, c in kl}
    times = sorted(series)
    if not times:
        return
    pmin = min(series[t][2] for t in times)
    pmax = max(series[t][1] for t in times)
    span = pmax - pmin or 1.0
    xspan = (x1 - x0) or 1.0

    def price_near(m):
        return series[min(times, key=lambda t: abs(t - m))]

    # 错开纵向位置避免重叠
    yslots = [1.55, 1.32, 1.10, 1.44, 1.22, 1.35]
    for i, ev in enumerate(events):
        dt = datetime.strptime(ev["time"], "%Y-%m-%d %H:%M").replace(
            tzinfo=timezone.utc)
        m = ms(dt)
        x = mdates.date2num(dt)
        rel = (m - x0) / xspan
        dx = (0.5 - rel) * (xspan / 86400000.0) * 0.15
        _, h, _, _ = price_near(m)
        y_text = pmin + span * yslots[i % len(yslots)]
        k = ev.get("kind", "logic")
        face = "#e8f0fe" if k == "logic" else "#fdecea"
        edge = "#1a73e8" if k == "logic" else "#c0392b"
        gid = f"annot-{i}-{k}"
        ax.annotate(
            ev["text"], xy=(x, h), xytext=(x + dx, y_text),
            ha="center", va="bottom", fontsize=8.5, zorder=20,
            gid=gid,
            bbox=dict(boxstyle="round,pad=0.4", fc=face, ec=edge,
                      lw=1.3, alpha=0.97),
            arrowprops=dict(arrowstyle="->", color=edge, lw=1.5,
                            connectionstyle="arc3,rad=0.15"))
    ax.set_ylim(pmin - span * 0.05, pmin + span * top_frac)
