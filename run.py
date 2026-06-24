#!/usr/bin/env python3
"""研究管线 CLI — 分步或全流程。

用法:
  python run.py all                    全流程（采集→指标→制图→报告）
  python run.py collect                只拉数据+检测区间 → dataset.json
  python run.py metrics                只从 dataset 算指标 → metrics.json
  python run.py plot                   只从 dataset 出图（需已有 dataset.json+标注yaml）
  python run.py report                 只从 dataset+metrics+narratives 出 docx

网络限制: 沙箱代理截断 >100B 响应体, collect/plot 需关沙箱运行。
"""
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.join(HERE, "config", "research.yaml")
OUT = os.path.join(HERE, "out")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"

    if cmd in ("collect", "all"):
        from pipeline import collect
        collect.run(CFG, OUT)

    if cmd in ("metrics", "all"):
        from pipeline import metrics
        dp = os.path.join(OUT, "dataset.json")
        if os.path.exists(dp):
            metrics.run(dp, OUT)
        else:
            print("dataset.json not found — run collect first", file=sys.stderr)

    if cmd in ("plot", "all"):
        from pipeline import plotting
        dp = os.path.join(OUT, "dataset.json")
        ann = os.path.join(HERE, "config", "annotations")
        mp = os.path.join(OUT, "metrics.json")
        if os.path.exists(dp):
            plotting.run(dp, ann, OUT, mp)
        else:
            print("dataset.json not found — run collect first", file=sys.stderr)

    if cmd in ("report", "all"):
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
