"""市场结构评分引擎。
对给定时间窗口，按以下框架输出定量评分+定性叙事：
  - 市场状态识别 (A~E)
  - A1二次逼空 / A2主升浪 / A3诱空 概率
  - 派发检测
  - 矛盾信号 + 剧本推演
输出格式: dict → 由 plotting 渲染为图上文本块。
"""

from __future__ import annotations

import math
from datetime import datetime, timezone


def analyze_window(raw: dict, window_ms: tuple[int, int],
                   price_map: dict[int, dict] | None = None,
                   oi_data: list[dict] | None = None,
                   fund_data: list[dict] | None = None,
                   svol_data: list[dict] | None = None,
                   ) -> dict:
    """对 [t0, t1] 窗口做结构分析，返回评分+叙事。

    raw 字段:
      price: [{t,o,h,l,c,v}]
      open_interest: [{t,oi,oi_val,ls_ratio,top_ls_ratio}]
      funding: [{t,rate,interval}]
      spot_volume: [{t,vol,vol_coin}]
    """
    t0, t1 = window_ms
    # ---- 切片 ----
    price = [k for k in raw.get("price", []) if t0 <= k["t"] <= t1]
    oi = [k for k in raw.get("open_interest", []) if t0 <= k["t"] <= t1]
    fund = [k for k in raw.get("funding", []) if t0 <= k["t"] <= t1]
    svol = [k for k in raw.get("spot_volume", []) if t0 <= k["t"] <= t1]

    if not price or not oi:
        return {"score_total": 0,
                "narrative": "数据不足，无法分析。"}

    p_first = price[0]["c"] if price[0]["c"] else 1
    p_last = price[-1]["c"]
    p_high = max(k["h"] for k in price)
    p_low = min(k["l"] for k in price)
    p_chg = (p_last / p_first - 1) if p_first else 0

    # OI 变化 (币本位是判断仓位真实变化的黄金标准)
    oi_first_c = oi[0]["oi"]
    oi_last_c = oi[-1]["oi"]
    oi_chg_c = (oi_last_c / oi_first_c - 1) if oi_first_c else 0
    oi_first_u = oi[0]["oi_val"]
    oi_last_u = oi[-1]["oi_val"]
    oi_chg_u = (oi_last_u / oi_first_u - 1) if oi_first_u else 0

    # 资金费率
    fr_neg_n = sum(1 for r in fund if r["rate"] < 0)
    fr_total = len(fund) or 1
    fr_neg_ratio = fr_neg_n / fr_total
    fr_min = min((r["rate"] for r in fund), default=0)
    fr_mean = (sum(r["rate"] for r in fund) / fr_total) if fund else 0

    # 成交量
    cv_sum = sum(k.get("v", 0) for k in price)
    sv_sum = sum(k.get("vol", 0) for k in svol)
    cv_avg = cv_sum / len(price) if price else 0
    sv_avg = sv_sum / len(svol) if svol else 0
    sv_cv_ratio = (sv_avg / cv_avg) if cv_avg else 0

    # 大户多空比
    top_ls_vals = [k["top_ls_ratio"] for k in oi
                   if k.get("top_ls_ratio") is not None]
    ls_first = top_ls_vals[0] if top_ls_vals else None
    ls_last = top_ls_vals[-1] if top_ls_vals else None
    ls_trend = (ls_last - ls_first) if (ls_first and ls_last) else 0

    # 价格波动性
    p_volatility = (p_high / p_low - 1) if p_low else 0

    # ================================================================
    # 第一步: 市场状态识别
    # ================================================================
    state = _identify_state(p_chg, oi_chg_c, p_volatility, fr_neg_ratio,
                            sv_cv_ratio)
    state_confidence = state["confidence"]

    # ================================================================
    # 第二步: A级结构评分
    # ================================================================
    a1_squeeze = _score_a1_squeeze(p_chg, oi_chg_c, fr_neg_ratio,
                                    sv_cv_ratio, top_ls_vals)
    a2_trend = _score_a2_trend(p_chg, oi_chg_c, fr_mean,
                                sv_cv_ratio)
    a3_trap = _score_a3_trap(p_chg, oi_chg_c, fr_min,
                              p_low, p_last, p_high)

    # ================================================================
    # 第三步: 派发检测
    # ================================================================
    dist = _score_distribution(p_chg, oi_chg_c, fr_mean, fr_neg_ratio,
                                p_high, p_last, sv_cv_ratio)

    # ================================================================
    # 第四步: OI/价格背离 (庄币专用简化)
    # ================================================================
    oi_vs_price_divergence = _divergence(p_chg, oi_chg_c, oi_chg_u)

    # ================================================================
    # 综合评分
    # ================================================================
    # 整体做多确定性 = f(逼空概率, -派发概率, 背离程度)
    long_score = round(
        max(0, min(100,
                   a1_squeeze * 0.4 + a2_trend * 0.2
                   + (100 - dist) * 0.3 + oi_vs_price_divergence["long_signal"] * 0.1
                   )))

    # ================================================================
    # 生成叙事文本
    # ================================================================
    narrative = _build_narrative_text(
        state, a1_squeeze, a2_trend, a3_trap, dist,
        oi_chg_c, oi_chg_u, fr_neg_ratio, fr_mean,
        ls_trend, ls_last, sv_cv_ratio,
        oi_vs_price_divergence, long_score,
        p_chg, p_volatility)

    return {
        "state": state,
        "a1_squeeze": a1_squeeze,
        "a2_trend": a2_trend,
        "a3_trap": a3_trap,
        "distribution": dist,
        "long_score": long_score,
        "oi_chg_coin_pct": round(oi_chg_c * 100, 1),
        "oi_chg_usdt_pct": round(oi_chg_u * 100, 1),
        "fr_neg_ratio": round(fr_neg_ratio * 100),
        "fr_min_pct": round(fr_min * 100, 3),
        "ls_last": ls_last,
        "ls_trend": round(ls_trend, 2),
        "sv_cv_ratio": round(sv_cv_ratio, 2),
        "narrative": narrative,
        "is_high_conviction": long_score >= 70 or (dist <= 20 and a1_squeeze >= 60),
    }


# ═══════════════════════════════════════════════════════════════
# 评分子函数
# ═══════════════════════════════════════════════════════════════

def _identify_state(p_chg, oi_chg, volatility, fr_neg_r, sv_cv_r):
    """A=趋势扩张, B=高位震荡, C=疑似派发, D=重新吸筹, E=崩溃踩踏"""
    if abs(p_chg) < 0.03 and abs(oi_chg) < 0.05 and volatility < 0.1:
        return {"state": "D", "label": "低波动整理",
                "confidence": 60}
    if p_chg > 0.05 and oi_chg > 0.1 and sv_cv_r > 0.2:
        return {"state": "A", "label": "趋势扩张",
                "confidence": min(90, 60 + int(p_chg * 100))}
    if p_chg < -0.1 and oi_chg < -0.1 and volatility > 0.15:
        return {"state": "E", "label": "崩溃/踩踏",
                "confidence": min(95, 70 + int(abs(p_chg) * 100))}
    if abs(p_chg) < 0.05 and oi_chg > 0.2 and volatility > 0.1:
        return {"state": "C", "label": "疑似派发",
                "confidence": min(80, 50 + int(oi_chg * 100))}
    if p_chg > 0.02 and oi_chg > 0 and volatility > 0.08:
        return {"state": "B", "label": "高位震荡",
                "confidence": 55}
    return {"state": "B", "label": "高位震荡(默认)",
            "confidence": 40}


def _score_a1_squeeze(p_chg, oi_chg, fr_neg_r, sv_cv_r, top_ls):
    """二次逼空概率 0-100。
    条件: 价格高位, OI下降, FR持续负, 现货卖压有限, 空头参与度提升。
    关键: 价格不能暴跌——暴跌不是逼空,是崩溃。"""
    # 价格暴跌直接否决逼空
    if p_chg < -0.15:
        return 10
    if p_chg < -0.08:
        return 25
    score = 50
    # 价格高位: 近段上涨或横盘
    if p_chg > 0.01:
        score += 10
    elif p_chg < -0.03:
        score -= 20
    # OI下降 = 多头被洗 = 逼空前提 (但价格不能同时暴跌)
    if oi_chg < -0.1:
        score += 20
    elif oi_chg > 0.2:
        score -= 30  # OI爆增不是逼空,是拥挤
    # FR持续负
    score += int(fr_neg_r * 20)
    # 现货卖压有限 (低现货量)
    if sv_cv_r < 0.3:
        score += 10
    # 大户多空趋势
    if top_ls and len(top_ls) >= 2:
        if top_ls[-1] > top_ls[0]:
            score += 5
        elif top_ls[-1] < 0.8:
            score -= 15
    return max(0, min(100, score))


def _score_a2_trend(p_chg, oi_chg, fr_mean, sv_cv_r):
    """趋势延续概率 0-100。
    条件: 价格突破, OI增加, 现货量增加, FR小幅为正。"""
    score = 50
    if p_chg > 0.03:
        score += 15
    elif p_chg < -0.02:
        score -= 20
    if oi_chg > 0.05:
        score += 10
    elif oi_chg < -0.05:
        score -= 10
    if 0 < fr_mean < 0.0005:
        score += 15  # 小幅正费率=健康
    elif fr_mean < -0.001:
        score -= 15
    if sv_cv_r > 0.2:
        score += 10
    return max(0, min(100, score))


def _score_a3_trap(p_chg, oi_chg, fr_min, p_low, p_last, p_high):
    """诱空概率 0-100。
    条件: 价格跌破支撑后快速收回, OI急增, FR急转负。"""
    score = 50
    recovery = (p_last - p_low) / (p_high - p_low + 1e-9)
    if recovery > 0.6:
        score += 25  # 大幅度收回
    elif recovery < 0.3:
        score -= 20
    if oi_chg > 0.1:
        score += 15
    if fr_min < -0.002:
        score += 10
    return max(0, min(100, score))


def _score_distribution(p_chg, oi_chg, fr_mean, fr_neg_r,
                         p_high, p_last, sv_cv_r):
    """派发概率 0-100。
    条件: 高位横盘或慢跌, OI持续增, FR持续正或转正, 反弹无量。"""
    score = 30
    # 高位横盘或阴跌
    if -0.03 < p_chg < 0.02:
        score += 20
    elif p_chg < -0.05:
        score += 10
    # OI增加 + 价格不涨 = 派发嫌疑
    if oi_chg > 0.1 and p_chg < 0.02:
        score += 30
    elif oi_chg < -0.1:
        score -= 20  # OI降=洗盘,不是派发
    # FR为正 = 多头付钱 (派发典型)
    if fr_mean > 0.0005:
        score += 15
    elif fr_neg_r > 0.5:
        score -= 15  # FR持续负,反而不是派发
    # 反弹无量
    if sv_cv_r < 0.15:
        score += 10
    # 离高点距离
    drop_from_high = (p_last / p_high - 1) if p_high else 0
    if drop_from_high < -0.1:
        score += 10
    return max(0, min(100, score))


def _divergence(p_chg, oi_chg_c, oi_chg_u):
    """OI/价格背离分析。
    返回 {long_signal: 0-100, narrative: str}。
    OI跌幅 > 价格跌幅 → 洗杠杆加分项。
    OI涨幅 > 价格涨幅 → 拥挤减分项。"""
    oi_drop_more = oi_chg_c < p_chg - 0.05  # OI比价格跌得多
    oi_rise_more = oi_chg_c > p_chg + 0.10  # OI比价格涨得多

    # USDT vs 币本位差异
    u_vs_c_gap = (oi_chg_u - oi_chg_c)

    long_sig = 50
    parts = []
    if oi_drop_more:
        long_sig += 25
        parts.append("[+] OI跌幅>价格跌幅: 洗杠杆,利多")
    if oi_rise_more:
        long_sig -= 30
        parts.append("[!] OI涨幅>价格涨幅: 拥挤,利空")
    if u_vs_c_gap > 0.1:
        parts.append("OI_USDT降幅小于币本位: 价格下跌是主因")
    elif u_vs_c_gap < -0.1:
        parts.append("OI_USDT降幅大于币本位: 真实减仓")

    if not parts:
        parts.append("OI与价格同向,无显著背离")

    return {"long_signal": max(0, min(100, long_sig)),
            "narrative": "; ".join(parts)}


# ═══════════════════════════════════════════════════════════════
# 叙事文本生成
# ═══════════════════════════════════════════════════════════════

def _build_narrative_text(state, a1, a2, a3, dist,
                           oi_c, oi_u, fr_neg_r, fr_m, ls_t, ls_l,
                           sv_cv, div, long_s, pchg, vol):
    """生成带颜色标记的分析文本。[!!]=高确定性信号, ⚪=中性, [!]=风险。"""
    lines = []

    # 市场状态
    lines.append(f"状态: {state['label']} (可信{state['confidence']})")
    lines.append("")

    # 核心三分数
    lines.append(f"二次逼空 {a1}  派发 {dist}  趋势 {a2}")
    if a3 > 50:
        lines.append(f"诱空 {a3}  [!]")

    # 做多确定性
    if long_s >= 70:
        lines.append(f"[!!] 做多确定性较高: {long_s}分")
    elif long_s >= 40:
        lines.append(f"做多确定性: {long_s}分 (中性)")
    else:
        lines.append(f"[!] 做多确定性低: {long_s}分")
    lines.append("")

    # 关键指标
    if abs(oi_c) > 0.1:
        tag = "[!!]" if oi_c < -0.1 else "[!]"
        lines.append(f"{tag} OI币本位变化 {oi_c:+.1f}%")
    if sv_cv < 0.15:
        lines.append(f"现货/合约量比 {sv_cv:.2f} (现货弱)")
    if fr_neg_r > 0.5:
        lines.append(f"[!!] FR {fr_neg_r:.0f}%时间负值 均值{fr_m*100:+.3f}%")
    if ls_l is not None:
        tag = "[!!]" if ls_l > 1.5 else ("[!]" if ls_l < 0.8 else "")
        if tag:
            lines.append(f"{tag} 大户多空比 {ls_l:.2f} (趋势 {ls_t:+.2f})")

    # 背离
    if div["narrative"] and "无显著" not in div["narrative"]:
        lines.append(div["narrative"])

    # 高确定性结论
    if long_s >= 70:
        lines.append("")
        lines.append("[!!] 高确定性:")
        if a1 >= 60:
            lines.append("  逼空结构成立,做多窗口")
        if dist <= 20:
            lines.append("  派发风险低,持仓安全")
        if oi_c < -0.15:
            lines.append("  持仓量已充分清洗")
    elif dist >= 60:
        lines.append("")
        lines.append("[!!] 高确定性(空): 派发信号强")
        lines.append("  不建议做多")

    if long_s <= 25:
        lines.append("")
        lines.append("[!!] 接飞刀风险极高,回避做多")

    return "\n".join(lines)
