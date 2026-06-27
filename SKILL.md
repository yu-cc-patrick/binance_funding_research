# funding-event-chart

币安永续「资金费率结算周期变 1h + 负费率」极端事件 —— 从 data.binance.vision 公开转储爬数据，到生成多维标注 K 线图的**完整制图流程**。

**触发**：用户说"跑费率研究管线"、"研究费率极端事件"、"给 XXX 币出图"、"找费率变 1h 负费率的币"、"重新出图"等。

---

## ⚠️ 文字策略（最重要，2026-06 定版）

**图上文字只保留客观事实，不做主观市场分析。**

- ✅ **保留**：客观新闻/事件（如"Upbit 成交暴增"、"私钥泄露 1498万枚被劫持"、"美股休市"、"解锁"）、价格里程碑（"单日+33%"、"退出后14天-26%"）、爆拉点位标识。
- ❌ **不做**：主观推断 FR/OI 的含义（如"空头在补贴多头"、"主力在派发"、"逼空概率 70%"这类）。
- 之前花大量精力做的 `pipeline/structure.py` 市场结构评分引擎和右栏叙事 **默认关闭**（`config/research.yaml` → `plot.show_structure: false`）。代码保留但不出现在图上。

爬取爆拉新闻时，用 WebSearch 查证催化剂（交易所上线、解锁、暴雷、休市），标注到 K 线爆拉点，**只陈述事件本身**，不要写"这意味着…"的分析。

---

## 前置条件

1. **网络**：`collect` 和 `plot` 都要联网拉 dump，且**必须关沙箱**（`dangerouslyDisableSandbox: true`）——本机沙箱代理把 >100B 响应体截为 0B，已验证。
2. **数据源**：全部从 `data.binance.vision`（CDN，不受封锁）。实时 API `fapi.binance.com` 对本机出口 IP TLS 封锁，**不可用**。
3. **Python**：`python3 + matplotlib + pyyaml`（report 才需 python-docx）。
4. **中文字体**：`/System/Library/Fonts/Supplemental/Arial Unicode.ttf`，已在 plotting 顶部注册。
5. **数据时效**：funding/kline 月度 dump 当月数据月底才发布；OI metrics 仅日度 dump 且只留近期（更早 404）。

---

## 工作流

项目根目录：`/Users/cr/binance_funding_research`。CLI：`python run.py {collect|metrics|plot|report|all}`。

### 1. 配置 `config/research.yaml`

```yaml
window:
  start: "2026-05-01"
  end: "2026-06-18"           # 月 dump 发布后更新到当天
  lifetime_start: "2025-11-01" # 周线全程视图起点(取合约上市月)
  pre_lookback_days: 7
  post_horizon_days: 20
sources:
  enabled: [funding, price, open_interest, daily, spot_volume]
symbols: ["IDUSDT"]            # 留空=全市场扫描; 指定则只跑这些
plot:
  show_structure: false        # 保持 false(文字策略)
  filename_prefix: "6.26_"     # 输出文件名日期前缀
```

### 2. 采集 `python run.py collect`（关沙箱）

枚举币种 → 跑每个数据源 → 检测 1h+负费率区间 → `out/dataset.json`（唯一中间真相）。
全量 11 币约几分钟（OI 是 5min 粒度，量大）。

### 3. 指标 `python run.py metrics`

从 dataset 算 → `out/metrics.json`：高低位判断（ATH/ATL/区间位置/近30日涨幅）、流通市值、OI 区间变化。

### 4. 制图 `python run.py plot`（关沙箱）

从 `dataset.json` + `metrics.json` + `config/annotations/<SYM>.yaml` → `out/<prefix><SYM>.png` + `.svg`。
SVG 文字是真实 text 元素、带 gid，可在 Inkscape 里改字、拖箭头。

### 爆拉新闻标注流程（每个币）

1. 看该币 regime 附近 1h K 线，找单小时涨幅 >8% 的爆拉点。
2. `WebSearch` 查证催化剂（"XXX币 暴涨 日期 上线/解锁/新闻"）。
3. 写 `config/annotations/<SYM>.yaml`，在爆拉点标 `kind: news` 框，**只写客观事件**。
4. 出图，打开 SVG 核对箭头指向。

annotation YAML 结构：
```yaml
panorama:                       # 全景图标注
- time: 2026-05-30 03:00
  text: 'Upbit成交暴增\n\n单日暴涨+33%'
  kind: news                    # news=红框(客观事件) / logic=蓝框(价格里程碑)
zoom:                           # 1h放大图标注
- time: 2026-05-30 03:00
  text: '爆拉+18.9%/h'
  kind: news
```

---

## 图表结构（7 行网格，每行左=全景 pre→1h→post，右=1h放大）

| 行 | 内容 |
|----|------|
| 通栏 | 周线全程（上市→现在）+ 历史高低点 + 高点市值 + 高低位裁定 |
| 1 | 价格 K 线 + 事件标注框（蓝=逻辑/红=新闻）|
| 2 | 持仓量 OI（USDT 名义价值，绿增红减）|
| 3 | 持仓量 OI（币本位，判断真实仓位变化的黄金标准）|
| 4 | 成交量（合约左轴蓝柱 + 现货右轴橙柱）|
| 5 | 大户多空比（折线，>1 净多）|
| 6 | 资金费率（柱，负红正绿）|
底部：策略点位评分表（如 annotation 里有 `strategy` 字段）。

---

## 数据源清单（`sources/`，插件式）

| 源 | dump 路径 | 字段 | 备注 |
|----|-----------|------|------|
| funding | `monthly/fundingRate` | rate, interval | 检测区间用；只月度 |
| price | `monthly+daily/klines/1h` | OHLC + v(成交额) | 合约 1h |
| open_interest | `daily/metrics` | oi(币), oi_val(USDT), ls_ratio, top_ls_ratio | 5min；仅日度且只留近期 |
| daily | `monthly+daily/klines/1d` | OHLC, v | lifetime 窗口；周线聚合用 |
| spot_volume | `spot/monthly+daily/klines/1h` | vol(USDT), vol_coin | **现货 openTime 是微秒!** 要 //1000 |

加新源：写 `sources/<name>.py` 继承 `DataSource` 实现 `fetch()` → 在 `research.yaml` 的 `sources.enabled` 加名字 → 如需新子图改 `pipeline/plotting.py`。

---

## 已知坑

1. **沙箱截断**：collect/plot 必须 `dangerouslyDisableSandbox: true`。
2. **regimes.detect 第二参**：是 `one_hour: int`，不是 dict。传错会 0 matches。
3. **现货 K 线时间戳是微秒**（16 位），合约是毫秒（13 位），spot_volume 源要 `//1000`。
4. **S3 枚举端点**：点写法 `s3.ap-northeast-1.amazonaws.com`，path-style。
5. **AAPL/MSFT 无现货**（股票永续），spot_volume 返回空，正常。
6. **机制三分类**：A 暴涨逼空 / B 暴雷砸盘 / C 股票休市折价。只有 C 是可重复的低风险做多机会；A/B 的负费率是行情过热/暴雷的伴生品，做多=接飞刀。

---

## 模块结构速查

```
binance_funding_research/
├── config/research.yaml          # 窗口/阈值/数据源/plot开关/币种
├── config/annotations/<SYM>.yaml # 图上标注(用户可手编, 只客观事件)
├── core/{http,dumps,timewin,regimes}.py  # 通用工具
├── sources/{funding,price,open_interest,daily,spot_volume}.py
├── pipeline/{collect,metrics,plotting,report,structure}.py
│   └── structure.py 默认不启用(show_structure:false)
├── out/                          # dataset.json/metrics.json/<prefix><SYM>.png+svg
└── run.py                        # CLI: collect|metrics|plot|report|all
```
