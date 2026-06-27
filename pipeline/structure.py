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
# 叙事文本生成 —— 多指标联合推理, 模拟人工分析师的推理链
# ═══════════════════════════════════════════════════════════════

def _build_narrative_text(state, a1, a2, a3, dist,
                           oi_c, oi_u, fr_neg_r, fr_m, ls_t, ls_l,
                           sv_cv, div, long_s, pchg, vol):
    """生成多指标联合推理叙事。每段回答一个问题:
    - 谁在加仓? 谁在离场? (OI+价格)
    - 谁在付钱? 为什么? (FR)
    - 聪明钱在做什么? (大户多空比)
    - 当前最大的矛盾是什么?
    - 做多/做空的逻辑链
    """
    lines = []
    is_crash = pchg < -0.10
    is_pump = pchg > 0.10
    is_extreme_vol = vol > 0.50
    oi_exploded = oi_c > 0.50
    oi_surged = oi_c > 0.20
    oi_dropped = oi_c < -0.20
    oi_moderate_drop = -0.20 <= oi_c < -0.05
    fr_all_neg = fr_neg_r > 0.90
    fr_mostly_neg = fr_neg_r > 0.50
    fr_deeply_neg = fr_m < -0.005
    ls_whale_long = ls_l is not None and ls_l > 1.5
    ls_whale_short = ls_l is not None and ls_l < 0.8
    ls_whale_exiting = ls_t < -0.15
    ls_whale_entering = ls_t > 0.15
    spot_weak = sv_cv < 0.15
    oi_cleaned = oi_c < -0.15 and abs(pchg) < 0.05
    oi_stalemate = abs(oi_c) < 0.10 and abs(pchg) < 0.03
    crowding = oi_surged and pchg < 0.05

    # ═══════════════════════════════════════
    # 1. 状态 + OI×价格 联合解读
    # ═══════════════════════════════════════
    if is_crash and oi_dropped:
        lines.append(f"价格暴跌{abs(pchg)*100:.0f}%+持仓量锐减{abs(oi_c)*100:.0f}%")
        if oi_u < oi_c - 0.10:
            lines.append("OI_USDT降幅远超币本位→不止价格效应,杠杆多头正被大规模清算")
        else:
            lines.append("OI_USDT降幅≈币本位→减仓是价格下跌的被动结果,多头尚未踩踏出清")
        lines.append("→这是崩溃/踩踏结构。恐慌做空+多头爆仓形成负反馈螺旋")
        if fr_deeply_neg or fr_all_neg:
            lines.append("FR极端负值是被恐慌做空砸出来的,不是逼空→负费率≠做多信号")

    elif is_crash and oi_surged:
        lines.append(f"价格暴跌{abs(pchg)*100:.0f}%但持仓量反增{oi_c*100:.0f}%")
        lines.append("→资金在暴跌中逆势加仓。可能是抄底资金进场,也可能是空头在加码")
        lines.append("OI增加=市场分歧加大,暴跌尚未形成一致性踩踏,短期方向不明")

    elif is_pump and oi_exploded:
        lines.append(f"价格暴涨{abs(pchg)*100:.0f}%+持仓量暴增{abs(oi_c)*100:.0f}%")
        lines.append("持仓量翻倍甚至数倍→散户FOMO追多+空头被迫加仓对冲,双向踩踏")
        lines.append("→这是典型的climax pump。OI暴增远超价格涨幅=拥挤,不是健康趋势")
        if fr_deeply_neg:
            lines.append("费率被砸到深度负值→空头在踩踏中付钱,不是空头主动建仓")

    elif crowding:
        lines.append(f"价格几乎停滞({pchg*100:+.1f}%)但OI大增{oi_c*100:+.0f}%")
        lines.append("→高控盘信号。大量仓位在横盘中建立,价格不涨=主力可能在派发")
        lines.append("也可能是洗盘:用横盘消磨多头耐心,逼他们止损后主力接筹")
        if fr_mostly_neg:
            lines.append("FR持续负→空头在付钱扛仓。多空双方都被锁,就看谁先扛不住")

    elif oi_cleaned:
        lines.append(f"OI已下降{abs(oi_c)*100:.0f}%而价格稳定→洗盘完成信号")
        lines.append("多头已被洗出,空头尚未大规模进场,主力可以在低位重新吸筹")
        lines.append("→这是逼空的前置条件:仓位已清洗,剩下来的是坚定多头+等待中的主力")

    elif oi_stalemate:
        lines.append(f"价格窄幅震荡+OI几乎不动→多空双方僵持")
        if fr_mostly_neg:
            lines.append("FR持续负=空头在付钱,但价格不涨→买方力量不足,在等催化剂")
        else:
            lines.append("市场进入观望期,方向不明,等待突破")

    else:
        # generic synthesis
        oi_desc = "暴增" if oi_surged else ("下降" if oi_dropped else "稳定")
        p_desc = "上涨" if pchg > 0.03 else ("下跌" if pchg < -0.03 else "横盘")
        lines.append(f"价格{p_desc}+OI{oi_desc}。状态:{state['label']}({state['confidence']})")

    lines.append("")

    # ═══════════════════════════════════════
    # 2. 谁在付钱? 资金费率解读
    # ═══════════════════════════════════════
    if fr_all_neg:
        lines.append("FR全程负值→空头持续在付钱")
        if is_crash:
            lines.append("但价格在崩盘→空头付钱是被迫的(做空被套),不是主动缴械。负费率在此不是利多")
        elif oi_dropped:
            lines.append("OI下降+FR负→空头在撤退(平空仓付钱),而不是加仓。逼空燃料在减少")
        elif crowding:
            lines.append("OI高悬+FR负→空头被锁仓,多头等拉升。但谁先扛不住是未知数")
        else:
            lines.append("空头付钱+价格稳定→时间站在多头一边。但需要OI确认仓位在清洗而非堆积")
    elif fr_mostly_neg:
        lines.append(f"FR {fr_neg_r*100:.0f}%时间为负,均值{fr_m*100:+.3f}%→空头偏弱势,但未到极端")
    else:
        lines.append(f"FR以正为主(均值{fr_m*100:+.3f}%)→多头在付钱,市场偏多头主导")

    # ═══════════════════════════════════════
    # 3. 大户在做什么?
    # ═══════════════════════════════════════
    if ls_l is not None:
        if ls_whale_long:
            lines.append(f"大户多空比{ls_l:.2f}(>1.5)→大户净多头,聪明钱看好")
        elif ls_whale_short:
            lines.append(f"大户多空比{ls_l:.2f}(<0.8)→大户净空头,聪明钱看空")
        else:
            lines.append(f"大户多空比{ls_l:.2f}→中性")
        if ls_whale_exiting:
            lines.append(f"多空比下降{abs(ls_t):+.2f}→大户在减多/加空,信号偏空")
        elif ls_whale_entering:
            lines.append(f"多空比上升{ls_t:+.2f}→大户在加多,信号偏多")

    # ═══════════════════════════════════════
    # 4. 成交量与现货
    # ═══════════════════════════════════════
    if spot_weak and sv_cv > 0:
        lines.append(f"现货/合约量比仅{sv_cv:.2f}→现货买盘薄弱,涨势缺乏现货支撑")
    elif sv_cv > 0.3:
        lines.append(f"现货/合约比{sv_cv:.2f}→现货买盘活跃,涨势有真实需求支撑")

    # ═══════════════════════════════════════
    # 5. 矛盾信号
    # ═══════════════════════════════════════
    contradictions = []
    if fr_all_neg and is_crash:
        contradictions.append("FR全负但价格暴跌:这不是逼空,是恐慌做空的果")
    if oi_surged and pchg < -0.03:
        contradictions.append("OI大增+价格下跌:资金在逆势加仓→可能是抄底,也可能是空头加码")
    if ls_whale_long and pchg < -0.05:
        contradictions.append("大户净多但价格下跌:大户可能在扛仓或被套,需观察是否止损")
    if ls_whale_short and pchg > 0.05:
        contradictions.append("大户净空但价格上涨:大户方向错了,可能出现空头踩踏")
    if oi_dropped and not is_crash and fr_mostly_neg:
        contradictions.append("OI降+FR负:如果OI在降,空头在减少→逼空的燃料不够。需等OI再次堆积")
    if contradictions:
        lines.append("")
        lines.append("矛盾信号:")
        for c in contradictions:
            lines.append(f"  [!] {c}")

    # ═══════════════════════════════════════
    # 6. 做多/做空 逻辑链
    # ═══════════════════════════════════════
    bullish = []
    bearish = []
    if oi_cleaned:
        bullish.append("OI已充分清洗→逼空前提满足")
    if fr_all_neg and not is_crash:
        bullish.append("FR全程负=空头持续付钱,时间站在多头")
    if ls_whale_entering:
        bullish.append("大户在加多")
    if oi_surged and is_pump:
        bearish.append("OI暴增=散户全进来了→顶部信号")
    if crowding:
        bearish.append("OI堆积+价格不涨=派发嫌疑")
    if is_crash:
        bearish.append("价格崩盘=不要接飞刀,等OI和价格都企稳")
    if ls_whale_exiting:
        bearish.append("大户在撤→跟聪明钱反向危险")
    if fr_all_neg and is_crash:
        bearish.append("暴跌中的负费率不是做多理由")

    if bullish or bearish:
        lines.append("")
        if bullish:
            lines.append("做多逻辑:")
            for b in bullish:
                lines.append(f"  [+] {b}")
        if bearish:
            lines.append("做空/回避逻辑:")
            for b in bearish:
                lines.append(f"  [-] {b}")

    # ═══════════════════════════════════════
    # 7. 核心评分与高确定性标注
    # ═══════════════════════════════════════
    lines.append("")
    if long_s >= 70:
        lines.append(f"[!!] 做多确定性较高({long_s}) "
                     f"逼空{a1} 派发{dist} 趋势{a2}")
        if a1 >= 60:
            lines.append("[!!] 逼空结构成立,做多窗口")
        if dist <= 20:
            lines.append("[!!] 派发风险低,持仓安全")
    elif long_s >= 40:
        lines.append(f"做多确定性中性({long_s}) "
                     f"逼空{a1} 派发{dist} 趋势{a2}")
    elif dist >= 60:
        lines.append(f"[!!] 派发风险高({dist})→不建议做多 "
                     f"逼空{a1} 趋势{a2}")
    else:
        lines.append(f"[!] 做多确定性低({long_s}) →回避做多 "
                     f"逼空{a1} 派发{dist}")

    if is_crash and long_s <= 35:
        lines.append("[!!] 接飞刀风险极高")

    return "\n".join(lines)
