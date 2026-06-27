"""采集编排器 — 加载配置、枚举币种、跑启用数据源、检测区间 → dataset.json。
dataset.json 是唯一中间真相，所有下游（metrics/plot/report）只读它。"""

from __future__ import annotations

import json
import os
import sys
import time
import yaml
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
    window = (datetime.strptime(ws, "%Y-%m-%d").replace(tzinfo=timezone.utc),
              datetime.strptime(we, "%Y-%m-%d").replace(tzinfo=timezone.utc) +
              _dt.timedelta(days=1) - _dt.timedelta(seconds=1))
    # lifetime 窗口(全程视图数据源用): 从 lifetime_start 到 end
    lt_start = cfg["window"].get("lifetime_start", ws)
    lifetime_window = (
        datetime.strptime(lt_start, "%Y-%m-%d").replace(tzinfo=timezone.utc),
        window[1])
    # 币种列表
    syms = cfg.get("symbols") or list_all_symbols()
    if not cfg.get("symbols"):
        print(f"全市场扫描: {len(syms)} 个币种", file=sys.stderr)

    names = cfg["sources"]["enabled"]
    sources = {n: load_source(n) for n in names}
    print(f"已加载数据源: {list(sources.keys())}", file=sys.stderr)

    dataset = {"config": cfg, "matches": {}, "all_funding_without_regime": []}
    for n, sym in enumerate(syms, 1):
        try:
            src_data = {}
            for sn, src in sources.items():
                win = lifetime_window if getattr(src, "lifetime", False) else window
                src_data[sn] = src.fetch(sym, win[0], win[1])
            # funding 是必需的（检测区间）
            if "funding" not in src_data or not src_data["funding"]:
                continue
            regimes = detect(src_data["funding"],
                             cfg["regime"]["one_hour"])
            if not regimes:
                continue
            print(f"  [{n}/{len(syms)}] MATCH {sym}: {len(regimes)} regime(s)",
                  file=sys.stderr)
            dataset["matches"][sym] = {
                "regimes": regimes,
                "raw": src_data,
            }
        except Exception as e:
            print(f"  [{n}/{len(syms)}] {sym} ERROR: {e}", file=sys.stderr)
        time.sleep(0.05)

    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "dataset.json")
    json.dump(dataset, open(path, "w"), indent=1, default=str)
    print(f"saved {path}  ({len(dataset['matches'])} matches)", file=sys.stderr)
    return list(dataset["matches"].keys())
