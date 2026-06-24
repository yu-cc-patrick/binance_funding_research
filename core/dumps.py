"""data.binance.vision 公开数据转储的路径与枚举工具。
所有 URL 模板集中管理——换数据源只需改这里。"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

from .http import http_get

# ---- 资产 ----
VISION = "https://data.binance.vision"
# S3 XML 列表（点写法区域域名是唯一稳定返回 XML 的变体）
S3_LIST = "https://s3.ap-northeast-1.amazonaws.com/data.binance.vision"
FUND_PREFIX = "data/futures/um/monthly/fundingRate/"

# ---- 下载 URL 模板（{sym}/{ym}/{ymd} 由调用方填入）----
DUMP_FUNDING = VISION + "/data/futures/um/monthly/fundingRate/{sym}/{sym}-fundingRate-{ym}.zip"
DUMP_KLINES_M = VISION + "/data/futures/um/monthly/klines/{sym}/1h/{sym}-1h-{ym}.zip"
DUMP_KLINES_D = VISION + "/data/futures/um/daily/klines/{sym}/1h/{sym}-1h-{ymd}.zip"
# 日线(全程视图/周线聚合用)
DUMP_KLINES_1D_M = VISION + "/data/futures/um/monthly/klines/{sym}/1d/{sym}-1d-{ym}.zip"
DUMP_KLINES_1D_D = VISION + "/data/futures/um/daily/klines/{sym}/1d/{sym}-1d-{ymd}.zip"
# 持仓量+多空比(metrics, 5min 粒度, 仅日度 dump, 约保留近期)
DUMP_METRICS_D = VISION + "/data/futures/um/daily/metrics/{sym}/{sym}-metrics-{ymd}.zip"


def months_in(start: datetime, end: datetime) -> list[str]:
    """生成窗口内所有 YYYY-MM 字符串。"""
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def days_in(start: datetime, end: datetime) -> list[str]:
    """生成窗口内所有 YYYY-MM-DD 字符串。"""
    out, d = [], start.replace(hour=0, minute=0, second=0, microsecond=0)
    d_end = end.replace(hour=0, minute=0, second=0, microsecond=0)
    while d <= d_end:
        out.append(f"{d:%Y-%m-%d}")
        d += timedelta(days=1)
    return out


def list_all_symbols() -> list[str]:
    """
    通过 S3 XML 索引枚举所有曾有 funding rate dump 的 USDⓈ-M 永续
    （含已下架、含中文名代币）。path-style 点写法区域域名是唯一稳定
    返回 XML 的变体。
    """
    syms = set()
    marker = None
    while True:
        params = {"delimiter": "/", "prefix": FUND_PREFIX,
                  "max-keys": "1000"}
        if marker:
            params["marker"] = marker
        body = http_get(S3_LIST, params).decode("utf-8")
        root = ET.fromstring(body)
        ns = ({"s3": root.tag.split("}")[0].strip("{")}
              if "}" in root.tag else {})
        cps_q = (".//s3:CommonPrefixes/s3:Prefix" if ns
                 else ".//CommonPrefixes/Prefix")
        last_pref = None
        for cp in root.findall(cps_q, ns):
            last_pref = cp.text
            p = cp.text.rstrip("/").split("/")[-1]
            if p.endswith("USDT") or p.endswith("USDC"):
                syms.add(p)
        trunc_q = (".//s3:IsTruncated" if ns else ".//IsTruncated")
        trunc = root.find(trunc_q, ns)
        if trunc is not None and trunc.text == "true" and last_pref:
            marker = last_pref
        else:
            break
    return sorted(syms)
