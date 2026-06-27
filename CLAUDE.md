# binance_funding_research · 项目记忆

> 本文件供新会话加载,使 Claude 能立即理解项目结构、关键发现、踩过的坑。

## 项目目标

从币安公开数据转储(`data.binance.vision`)自动发现 USDⓈ-M 永续合约中「资金费率结算周期突变为 1 小时 + 费率转负」的极端事件,生成带标注的 K 线图 + Word 报告。

## ⚠️ 图上文字策略（2026-06 定版）

**只保留客观事实，不做主观市场分析。**

- ✅ **保留**：客观新闻/事件、价格里程碑、爆拉点位标识
- ❌ **不做**：FR/OI 主观分析（"主力在派发"、"逼空概率70%"等）
- `pipeline/structure.py` 市场结构评分默认关闭（`plot.show_structure: false`）
- 爬爆拉新闻用 WebSearch → 标注到 K 线图上，**只陈述事件本身**

## 项目目标（原文）

## 模块结构(重构成品)

```
binance_funding_research/
├── config/
│   ├── research.yaml              # 窗口/阈值/启用的数据源(集中配置)
│   ├── annotations/<SYM>.yaml     # 图上事件标注(用户手编,蓝=逻辑/红=新闻)
│   └── narratives/<SYM>.yaml      # 叙事原因/参考来源/verdict(用户手编)
├── core/                          # 通用工具(不涉及具体数据源)
│   ├── http.py                    # HTTP GET + ZIP/CSV 下载(6次重试,支持404)
│   ├── dumps.py                   # 转储 URL 模板 + S3 XML 枚举全部币种
│   ├── timewin.py                 # ms/dt 转换 + 三阶段窗口(pre/core/post) + 采样网格
│   └── regimes.py                 # 1h+负费率区间检测(纯函数,有单测)
├── sources/                       # ★ 插件式数据源(加新维度只动这里)
│   ├── base.py                    # DataSource 抽象(fetch + align_to_grid)
│   ├── funding.py                 # 资金费率(含 funding_interval_hours)
│   └── price.py                   # 价格(OHLC, month+daily dump 混合)
├── pipeline/                      # 执行管线
│   ├── collect.py                 # 编排→out/dataset.json(唯一中间真相)
│   ├── metrics.py                 # 价量指标→out/metrics.json
│   ├── plotting.py                # 双栏图(全景+放大,三段背景色,事件标注框)
│   └── report.py                  # Word 报告(直接读 json+yaml,不解析 md)
├── out/                           # 产物(dataset.json / metrics.json / *.png / docx)
├── run.py                         # CLI: collect|metrics|plot|report|all
└── SKILL.md                       # 研究方法论(触发: "研究费率极端事件")
```

**核心原则**: `out/dataset.json` 是唯一中间真相,所有下游(metrics/plot/report)只读它,不存在反向解析。

## 网络环境(最重要——每个新会话必须知道)

### 1. 沙箱代理截断响应体
本机沙箱(`sandbox.enabled: true`)通过 `localhost:60981` 代理强制过滤网络。**该代理把 >~100 字节的响应体截为 0 字节**,已验证(98 字节 CHECKSUM 能下,980 字节 zip 变空,pypi JSON 也空)。结论:**所有需要联网的操作(collect/plot)必须 `dangerouslyDisableSandbox: true`**。

### 2. fapi.binance.com 被地理封锁
实时 API `fapi.binance.com` 的 TLS 握手被 Binance 从本机出口 IP 丢弃(关沙箱也连不上)。**全部数据从公开转储 `data.binance.vision` 取**,这是 CDN,不受封锁。

### 3. S3 XML 枚举的正确端点
列币种的正确端点不是老横线格式 `s3-ap-northeast-1.amazonaws.com`,而是**点写法**`s3.ap-northeast-1.amazonaws.com`。走 path-style:`https://s3.ap-northeast-1.amazonaws.com/data.binance.vision?delimiter=/&prefix=...`。已写入 `core/dumps.py`。

## 已查证的发现(2026年5月)

### 命中币种与机制分类
扫描 772 个币种,11 个命中「1h 结算 + 负费率」,退出后 14 天实际价格:

| 类型 | 机制 | 币种 | 退出后走向 | 结论 |
|------|------|------|-----------|------|
| **C** 股票永续休市 | 美股休市时指数冻结→永续折价→负费率(结构性) | AAPL, MSFT | +7.1%, +3.4% | ✓ 确定性较好 |
| **A** 暴涨逼空 | 现货被买爆→永续被做空压制→负费率→空头踩踏 | IRYS,ID,HIVE,ORCA,PROVE,PROMPT,PRL | 跌 21-34% | ✗ 接飞刀 |
| **B** 暴雷砸盘 | 解锁/私钥泄露→瞬间崩盘→恐慌做空→负费率封顶 | GUA(私钥泄露-2%), LAYER(解锁-0.29%) | 跌 21-23% | ✗ 接飞刀 |

**核心洞察**: 负费率 ≠ 做多机会。A/B 类的高负费率是行情过热/暴雷的伴生品,退出后价格继续跌,靠吃几个百分点的费率完全覆盖不了本金两位数的下跌(典型的"接飞刀")。只有股票永续的结构性折价才是可重复的低风险机会。

### 数据限制
- funding dump **只有月度版本**(无日度),当月数据月底才发布。2026-06 数据截至项目创建时未出。
- HIVE 的 1h 区间卡在 5/31 23:00,实际上大概率延续进 6 月。
- 价格用 1h K 线收盘价,不是 tick 级标记价格。

## 代码规范(本项目的)

- Python 3.9: 所有带 `X | None` 类型注解的模块第一行 import 必须是 `from __future__ import annotations`(否则 eval 时报 `TypeError: unsupported operand type(s) for |`)。
- 中文绘图字体: `Arial Unicode.ttf`(`/System/Library/Fonts/Supplemental/Arial Unicode.ttf`),已在 `pipeline/plotting.py` 顶部注册。
- 联网函数全部有重试(`http_get` 6 次 + back-off),404 可容错返回 `None`。

## 加新数据源的步骤

1. 写 `sources/<name>.py`,继承 `sources.base.DataSource`,实现 `fetch(symbol,start,end) → list[dict]`
2. 在 `config/research.yaml` → `sources.enabled` 里加 `name`
3. 如需新指标:在 `pipeline/metrics.py` 加计算
4. 如需新子图:在 `pipeline/plotting.py` 加 axes
5. 重跑 `python run.py all`

用户已点名想加: OpenInterest、多空比。

## 旧项目(保留)

`binance_funding_1h_negative/` 是第一版原型(4 个脚本,fetch/plot/annotate/make_report,已验证出正确结果)。保留作历史参考,不会被新项目覆盖。新项目是对它的模块化重构。

## 相关文件

- `SKILL.md` — 研究方法论 skill 文档
- `config/research.yaml` — 所有可调参数(窗口/阈值/启用的数据源)
- `out/dataset.json` — 最新一次采集的完整数据集(11 币)
- `out/资金费率1h负费率事件分析报告.docx` — 最新完整报告
