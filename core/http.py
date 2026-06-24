"""HTTP 工具层 — 对所有数据源的统一网络访问。
沙箱限制：沙箱代理把 >100B 响应体截为 0B，所以实际采集需关沙箱运行。"""

from __future__ import annotations

import io
import csv
import time
import zipfile
import urllib.request
import urllib.parse
import urllib.error


def http_get(url: str, params: dict | None = None,
             tries: int = 6, ok_404: bool = False) -> bytes | None:
    """带重试的 HTTP GET。ok_404=True 时返回 None 而非抛异常。"""
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "binance-research/1.0"})
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404 and ok_404:
                return None
            last = e
            time.sleep(1.0 * (i + 1))
        except Exception as e:
            last = e
            time.sleep(1.0 * (i + 1))
    if ok_404:
        return None
    raise RuntimeError(f"GET failed after {tries} tries: {url}\n  {last}")


def download_csv_rows(url: str) -> list[list[str]] | None:
    """下载 Binance 月度/日度 dump .zip 并返回 CSV 行。不存在则返回 None。"""
    blob = http_get(url, ok_404=True)
    if not blob:
        return None
    try:
        zf = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile:
        return None
    name = zf.namelist()[0]
    text = zf.read(name).decode("utf-8")
    return list(csv.reader(io.StringIO(text)))
