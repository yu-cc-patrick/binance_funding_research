"""采集编排器 — 加载配置、枚举币种、跑启用数据源、检测区间 → dataset.json。
dataset.json 是唯一中间真相，所有下游（metrics/plot/report）只读它。"""

from __future__ import annotations

import json
import os
import sys
import yaml
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from datetime import datetime, timezone
from importlib import import_module

from core.dumps import list_all_symbols
from core.regimes import detect
from core.timewin import parse_utc, three_phase, ms


def load_config(cfg_path: str) -> dict:
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)
    return cfg


def load_source(name: str):
    """从 name 字符串动态加载 sources/<name>.py → 实例化。"""
    mod = import_module(f"sources.{name}")
    # 查找该模块中第一个 DataSource 子类
    for attr in dir(mod):
        obj = getattr(mod, attr)
        if (isinstance(obj, type) and hasattr(obj, "name")
                and getattr(obj, "name", None) == name):
            return obj()
    raise ValueError(f"sources.{name} 中没有找到 name='{name}' 的 DataSource")


def run(cfg_path: str, out_dir: str) -> list[str]:
    """返回命中的 symbol 列表。输出 out_dir/dataset.json。"""
    cfg = load_config(cfg_path)
    return _run_with_cfg(cfg, out_dir)


def run_with_cfg(cfg: dict, out_dir: str) -> list[str]:
    """同 run(), 但不读磁盘 config, 直接用传入的 cfg dict。"""
    return _run_with_cfg(cfg, out_dir)


def _run_with_cfg(cfg: dict, out_dir: str) -> list[str]:
    ws, we = cfg["window"]["start"], cfg["window"]["end"]
    import datetime as _dt
    pre_days = cfg["window"].get("pre_lookback_days", 7)
    lt_start_str = cfg["window"].get("lifetime_start", ws)
    lt_start = datetime.strptime(lt_start_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    # 采集窗口下界: 取 lifetime_start 和 (window.start - pre_days) 中更早的,
    # 确保即使 regime 卡在数据边界, 也能看到 8h→1h 切换前的正常状态
    candidate_start = (datetime.strptime(ws, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                       - _dt.timedelta(days=pre_days))
    window_start = min(lt_start, candidate_start)
    window_end = (datetime.strptime(we, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                  + _dt.timedelta(days=1) - _dt.timedelta(seconds=1))
    window = (window_start, window_end)
    # lifetime 窗口(全程视图数据源用): 从 lifetime_start 到 end
    lifetime_window = (lt_start, window[1])
    # 币种列表
    syms = cfg.get("symbols") or list_all_symbols()
    if not cfg.get("symbols"):
        print(f"全市场扫描: {len(syms)} 个币种", file=sys.stderr)

    names = cfg["sources"]["enabled"]
    sources = {n: load_source(n) for n in names}
    print(f"已加载数据源: {list(sources.keys())}", file=sys.stderr)

    dataset = {"config": cfg, "matches": {}, "all_funding_without_regime": []}
    lock = threading.Lock()
    done_count = [0]  # mutable counter for thread-safe progress

    def process_one(sym: str) -> tuple[str, list, dict] | None:
        """处理单个币种, 返回 (sym, regimes, src_data) 或 None。"""
        import time as _time
        try:
            src_data = {}
            for sn, src in sources.items():
                win = lifetime_window if getattr(src, "lifetime", False) else window
                src_data[sn] = src.fetch(sym, win[0], win[1])
            if "funding" not in src_data or not src_data["funding"]:
                return None
            regimes = detect(src_data["funding"],
                             cfg["regime"]["one_hour"])
            if not regimes:
                return None
            with lock:
                done_count[0] += 1
                print(f"  [{done_count[0]}/{len(syms)}] MATCH {sym}: {len(regimes)} regime(s)",
                      file=sys.stderr)
            return (sym, regimes, src_data)
        except Exception as e:
            with lock:
                done_count[0] += 1
                print(f"  [{done_count[0]}/{len(syms)}] {sym} ERROR: {e}", file=sys.stderr)
            return None

    with ThreadPoolExecutor(max_workers=16) as ex:
        futures = {ex.submit(process_one, s): s for s in syms}
        for fut in as_completed(futures):
            result = fut.result()
            if result:
                sym, regimes, src_data = result
                dataset["matches"][sym] = {
                    "regimes": regimes,
                    "raw": src_data,
                }

    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "dataset.json")
    json.dump(dataset, open(path, "w"), indent=1, default=str)
    print(f"saved {path}  ({len(dataset['matches'])} matches)", file=sys.stderr)
    return list(dataset["matches"].keys())
