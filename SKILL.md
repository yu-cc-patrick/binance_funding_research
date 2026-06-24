# funding-event-research

币安永续「资金费率极端事件」研究方法论与工作流。触发时机：用户说"找资金费率变成 1 小时且为负费率的币"、"研究费率极端事件"、"跑费率研究管线"、"collet 费率数据"等。

## 前置条件

1. **网络**: 数据采集(`collect`)和制图(`plot`)需联网（从 `data.binance.vision` 拉 dump），且必须**关闭沙箱**运行（沙箱代理把 >100B 响应体截为 0B，已验证）。
2. **Python**: `python3` + `matplotlib` + `python-docx` + `pyyaml`。
3. **数据时效**: Binance funding dump 按月发布，当前月数据在月底才出。研究窗口可配 `config/research.yaml`。

## 工作流（逐步执行）

### 1. 数据采集 & 区间检测

```bash
python run.py collect
```
读取 `config/research.yaml`（窗口、启用的数据源、目标币种），枚举全市场(或指定)币种，跑每个启用的数据源（funding + price），检测 1h+负费率区间，输出 `out/dataset.json`。

`config/research.yaml` 核心配置：
```yaml
window:
  start: "2026-05-01"
  end: "2026-06-14"          # 月 dump 发布后更新
  pre_lookback_days: 7
  post_horizon_days: 14
regime:
  one_hour: 1
  min_run: 3
sources:
  enabled: [funding, price]   # 加新数据源在这里
symbols: []                    # 空=全扫
```

### 2. 指标计算

```bash
python run.py metrics
```
从 `out/dataset.json` 算衍生指标（区间内价格变化、退出后 14 天极值、累计负费率），输出 `out/metrics.json`。

### 3. 查叙事原因（人工 + AI 辅助）

对于每个命中币种，搜索并查证其费率变极端的原因（代币解锁、上币/下架、暴雷、逼空等），写入：
- `config/annotations/<SYM>.yaml` — 图上标注事件（时间 / 文字 / kind: logic|news）
- `config/narratives/<SYM>.yaml` — 叙事正文、参考来源 URL、verdict（✓ / ✗ / △）

标注 YAML 格式：
```yaml
panorama:
  - time: "2026-05-10 14:00"
    text: "折价→负费率\n切1h结算"
    kind: logic
  - time: "2026-05-10 22:00"
    text: "最负 -0.09%"
    kind: news
zoom:
  - time: "2026-05-11 13:00"
    text: "费率回正"
    kind: logic
```

叙事 YAML 格式：
```yaml
label: "C 类 · 股票永续休市"
body: "AAPLUSDT 是币安的苹果股票永续..."
sources:
  - https://...
verdict: "✓ 较好"
```

### 4. 制图

```bash
python run.py plot
```
从 `out/dataset.json` + `config/annotations/*.yaml` 生成双栏 PNG（左全景三段背景色 + 右 1h 放大），图上带事件标注框（蓝=逻辑/市场结构，红=客观新闻/事件）。

### 5. 出报告

```bash
python run.py report
```
从 `out/dataset.json` + `out/metrics.json` + `config/narratives/*.yaml` 直接生成 Word 报告（含执行摘要、机会评估表、全量数据表、带标注配图），`out/资金费率1h负费率事件分析报告.docx`。

### 一键全流程

```bash
python run.py all
```

## 加新数据源（如 OpenInterest）

1. 写 `sources/open_interest.py`，继承 `sources.base.DataSource`，实现 `fetch(symbol, start, end) → list[dict]`。
2. 在 `config/research.yaml` 的 `sources.enabled` 里加 `open_interest`。
3. 重跑 `collect` → `metrics`（如果需要新指标，在 `pipeline/metrics.py` 里加计算逻辑）。
4. 备选：在 `pipeline/plotting.py` 里加新子图（如 OI 柱状图）。

## 关键限制

1. **沙箱代理截断**: 本机沙箱代理把 >100B 响应体截为 0B，collect/plot 必须 `dangerouslyDisableSandbox: true` 或在本机终端跑。
2. **fapi 地理封锁**: 实时 API `fapi.binance.com` 对本机出口 IP TLS 封锁，全部改用公开转储 `data.binance.vision`。
3. **月度数据滞后**: funding dump 按月发布，当月数据要到月底才有。6 月数据发布后更新 `window.end` 即可重跑。
4. **标注「(推断)」**: 叙事原因中标注"(推断)"的部分是行情结构与时间吻合的推测，非逐篇核验的确证。

## 模块结构速查

```
binance_funding_research/
├── config/
│   ├── research.yaml          # 窗口/阈值/启用的数据源
│   ├── annotations/<SYM>.yaml # 图上标注（用户可手编）
│   └── narratives/<SYM>.yaml  # 叙事/来源/verdict（用户可手编）
├── core/                      # 通用工具（不涉及具体数据源）
│   ├── http.py                # HTTP GET + ZIP/CSV 下载
│   ├── dumps.py               # data.binance.vision URL 模板 + S3 枚举
│   ├── timewin.py             # ms/dt 转换 + 三阶段窗口
│   └── regimes.py             # 1h+负费率区间检测（纯函数）
├── sources/                   # 插件式数据源
│   ├── base.py                # DataSource 抽象
│   ├── funding.py             # 资金费率
│   └── price.py               # 价格(OHLC)
├── pipeline/                  # 执行管线
│   ├── collect.py             # 编排→dataset.json
│   ├── metrics.py             # 指标→metrics.json
│   ├── plotting.py            # 制图→*.png
│   └── report.py              # Word 报告→.docx
├── out/                       # 产物（dataset/metrics/png/docx）
└── run.py                     # CLI 入口
```
