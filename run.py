#!/usr/bin/env python3
"""研究管线 CLI — 分步或全流程。接受命令行参数覆盖 config/research.yaml。

用法:
  python run.py all                                                   全流程
  python run.py all --symbols GUAUSDT,HIVEUSDT --prefix 6.27_
  python run.py collect --symbols GUAUSDT                             只采集指定币
  python run.py plot --prefix 6.27_                                   仅出图(用前缀)
  python run.py metrics

覆盖: --symbols 只在 collect 生效(控制采集范围)。
      --prefix 只在 plot/all 生效(控制输出文件名)。
      --show-structure 只在 plot/all 生效。
      --window-start/end 只在 collect/all 生效。

网络: 沙箱代理截断 >100B 响应体, collect/plot 需关沙箱运行。
"""

import argparse
import os
import sys
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.join(HERE, "config", "research.yaml")
OUT = os.path.join(HERE, "out")


def main():
    p = argparse.ArgumentParser(description="币安资金费率极端事件研究管线")
    p.add_argument("step", nargs="?", default="all",
                   choices=["all", "collect", "metrics", "plot", "report"])
    p.add_argument("--symbols", help="逗号分隔币种, 如 GUAUSDT,HIVEUSDT (collect/all)")
    p.add_argument("--prefix", default=None, help="输出文件名前缀, 如 6.27_ (plot/all)")
    p.add_argument("--window-start", help="窗口起点 YYYY-MM-DD (collect/all)")
    p.add_argument("--window-end", help="窗口终点 YYYY-MM-DD (collect/all)")
    p.add_argument("--show-structure", action="store_true",
                   help="启用右栏市场结构分析 (plot/all)")
    args = p.parse_args()
    step = args.step

    # 加载原始配置
    with open(CFG) as f:
        cfg = yaml.safe_load(f)

    # CLI 覆盖 —— 直接改 cfg dict, 传给各阶段
    if args.symbols:
        cfg["symbols"] = [s.strip() for s in args.symbols.split(",") if s.strip()]
    if args.window_start:
        cfg["window"]["start"] = args.window_start
    if args.window_end:
        cfg["window"]["end"] = args.window_end
    if args.prefix is not None:
        cfg.setdefault("plot", {})["filename_prefix"] = args.prefix
    if args.show_structure:
        cfg.setdefault("plot", {})["show_structure"] = True

    plot_overrides = {
        k: v for k, v in cfg.get("plot", {}).items()
    }

    # ---- collect ----
    if step in ("collect", "all"):
        from pipeline import collect
        collect.run_with_cfg(cfg, OUT)

    # ---- metrics ----
    if step in ("metrics", "all"):
        from pipeline import metrics
        dp = os.path.join(OUT, "dataset.json")
        if os.path.exists(dp):
            metrics.run(dp, OUT)
        else:
            print("dataset.json not found — run collect first", file=sys.stderr)

    # ---- plot ----
    if step in ("plot", "all"):
        from pipeline import plotting
        dp = os.path.join(OUT, "dataset.json")
        ann = os.path.join(HERE, "config", "annotations")
        mp = os.path.join(OUT, "metrics.json")
        if os.path.exists(dp):
            plotting.run(dp, ann, OUT, mp, plot_overrides)
        else:
            print("dataset.json not found — run collect first", file=sys.stderr)

    # ---- report ----
    if step in ("report", "all"):
        from pipeline import report
        dp = os.path.join(OUT, "dataset.json")
        mp = os.path.join(OUT, "metrics.json")
        nd = os.path.join(HERE, "config", "narratives")
        if os.path.exists(dp) and os.path.exists(mp):
            report.run(dp, mp, nd, OUT)
        else:
            print("dataset.json or metrics.json not found", file=sys.stderr)


if __name__ == "__main__":
    main()
