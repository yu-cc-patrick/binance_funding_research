# funding-event-chart

币安永续「资金费率结算周期变 1h + 负费率」极端事件 —— 完整制图流程。支持**历史事件**（月度 dump 已发布）和**当下事件**（月度 dump 未发布，走 REST API）。

**触发**："跑费率研究管线"、"给 XXX 币出图"、"找费率变 1h 负费率的币"、"重新出图"等。

---

## ⚠️ 第一步：判断老币还是新币

| 判断 | 条件 | 数据源 | 示例 |
|------|------|--------|------|
| **老币** | 事件月份 ≤ 上个月（月度 dump 已发布）| `data.binance.vision` dump | RAVE (4月) |
| **新币** | 事件发生在**当月**（月度 dump 未发布）| `fapi.binance.com` REST API | NFP (7/1) |

**关键区别**：月度 dump 月底才发布，当月事件只能用 REST API。

---

## 文字策略

**图上文字只保留客观事实，不做主观市场分析。**

- ✅ 客观事件、价格里程碑、爆拉点位
- ✅ 即使查不到催化剂，也必须写"无实质性利好支撑XX%涨幅"
- ❌ 不做主观推断（"主力在派发"、"逼空概率70%"等）
- 所有 WebSearch 数据必须附来源 URL

---

## 老币工作流（示例：RAVE, 2026年4月）

```
① 配置 research.yaml → symbols, 窗口
② python run.py collect (关沙箱, 16线程并行)
③ python run.py metrics
④ WebSearch 查催化剂 + 流通量 → 写 annotation YAML + 填 market_cap.circulating
⑤ python run.py plot (关沙箱)
```

### 数据源（全部从 data.binance.vision dump）

| 源 | 覆盖 | 备注 |
|----|------|------|
| funding | 月度 `fundingRate` | 完整历史 |
| price | 月度+日度 `klines/1h` | 完整 |
| open_interest | 日度 `metrics` | 5min 粒度，仅近期 |
| daily | 月度+日度 `klines/1d` | 周线聚合 |
| spot_volume | 币安现货月度+日度 `klines/1h` | 仅限有币安现货的币 |
| coingecko_spot | CoinGecko `market_chart?days=365` | 币安无现货时的 fallback，daily 粒度 |

### 现货决策树

```
币安有现货？ → YES → 画 1h 柱，标"现货 币安"
    ↓ NO
CoinGecko tickers → 找最大现货主场
    ↓
找到？ → YES (如 KuCoin) → 能拉历史 K 线？ → 大概率不能（免费 API 只保留~7天）
    ↓                                              → 文字标注 "主战场: KuCoin, 峰值XX"
找不到单一主场 → "现货没有单一的主战场"
```

### RAVE 完整示例

- **事件**：4/12~4/24 1h 结算，+4057% → -96%，纯庄币拉砸
- **流通量**：2.52 亿（CMC），填 `market_cap.circulating.RAVEUSDT: 252480000`
- **现货**：币安无 → CoinGecko tickers → KuCoin 最大（4/17上市日峰值 $2.5 亿）→ 历史 API 过期不
可拉 → 用 CoinGecko daily 全市场量
- **标注**：WebSearch → ZachXBT 曝光、内部控盘 90-95%、无实质性利好 → 写 RAVEUSDT.yaml
- **spot_note**：`"现货主战场: KuCoin(4/17上市, 峰值24h约2.5亿, CMC); DEX仅8%; 币安无现货; 历史API过期不
可拉"`

---

## 新币工作流（示例：NFP, 2026年7/1）

```
① 判断为当月事件 → 用 fapi_rest 源
② 走 fapi_rest 构建 dataset（脚本方式，不走 run.py collect）
③ python run.py metrics（或用 from pipeline.metrics import run 直接调）
④ WebSearch 查催化剂 + CoinGecko 查流通量 + CoinGecko tickers 找现货主场
⑤ 写 annotation YAML（含 spot_note）
⑥ python run.py plot
```

### 数据源（全部从币安 REST API）

| 源 | REST API 端点 | Limit | 覆盖 |
|----|--------------|-------|------|
| funding | `fapi.binance.com/fapi/v1/fundingRate` | 1000 条 | ~42天 (4h结算) |
| price | `fapi.binance.com/fapi/v1/klines?interval=1h` | 1500 根 | ~62天 |
| open_interest | `fapi.binance.com/futures/data/openInterestHist?period=5m` | **500 条** | **仅 42 小时!** |
| 多空比 | `fapi.binance.com/futures/data/globalLongShortAccountRatio?period=5m` | 500 条 | 42 小时 |
| daily | `fapi.binance.com/fapi/v1/klines?interval=1d` | 500 根 | ~500天 |
| spot_volume | `api.binance.com/api/v3/klines?interval=1h` | 1000 根 | 币安现货 |

**⚠️ 关键局限**：OI 只有 42 小时——全景图 pre 区域无 OI 数据。等月度 dump 发布后才有完整历史。

### 走 fapi_rest 构建 dataset 的标准脚本模板

```python
import json, os, sys
from datetime import datetime, timezone
os.chdir('/Users/cr/binance_funding_research')
sys.path.insert(0, '.')

from sources.fapi_rest import (FapiFundingSource, FapiPriceSource,
    FapiDailySource, FapiOISource, FapiSpotSource)

sym = "NFPUSDT"
ws = datetime(2026, 7, 1, tzinfo=timezone.utc) - timedelta(days=7)  # pre 7d
we = datetime(2026, 7, 2, tzinfo=timezone.utc)
ls = datetime(2025, 12, 1, tzinfo=timezone.utc)  # lifetime start

funding = FapiFundingSource().fetch(sym, ws, we)
price   = FapiPriceSource().fetch(sym, ws, we)
daily   = FapiDailySource().fetch(sym, ls, we)
oi_data = FapiOISource().fetch(sym, ws, we)
spot    = FapiSpotSource().fetch(sym, ws, we)

from core.regimes import detect
regimes = detect(funding, 1)

cfg = {
    'window': {'pre_lookback_days': 7, 'post_horizon_days': 5,
               'lifetime_start': '2025-12-01', 'start': '2026-07-01', 'end': '2026-07-02'},
    'plot': {'show_structure': False, 'filename_prefix': 'NFP_'},
    'market_cap': {'circulating': {'NFPUSDT': 585640000}, 'default_circulating': None},
    'regime': {'one_hour': 1, 'min_run': 3, 'gap_tolerance_min': 75},
    'sampling': {'pre_interval_hours': 1, 'core_interval_hours': 1, 'post_interval_hours': 1}
}

dataset = {'config': cfg, 'matches': {sym: {
    'regimes': regimes,
    'raw': {'funding': funding, 'price': price, 'open_interest': oi_data,
            'daily': daily, 'spot_volume': spot, 'coingecko_spot': []}
}}}
json.dump(dataset, open('out/_tmp.json','w'), indent=1, default=str)

from pipeline.metrics import run as mr
mr('out/_tmp.json', 'out')
from pipeline.plotting import run as pr
pr('out/_tmp.json', 'config/annotations', 'out', 'out/metrics.json',
   {'filename_prefix': 'NFP_'})
os.remove('out/_tmp.json')
```

### NFP 完整示例

- **事件**：7/1 13:00 4h→1h 切换，12 个点全部负费率（最深 -1.94%）
- **催化剂**：6/26 Binance TH 宣布下架 NFP → -24%；4/30 被标记"监控标签"；99.2% ATH 回撤
- **流通量**：5.86 亿（CMC），OI 峰值 7.26 亿，**占流通 124%**（OI 超过流通量）
- **现货**：CoinGecko tickers → 币安 NFP/USDT $52 亿 → 用 `api.binance.com` 拉 1h K 线
- **spot_note**：`"现货主战场: 币安(NFP/USDT 24h约52亿, CoinGecko); 币安现货1h K线可用"`
- **结论**："无实质性利好——Binance TH下架+监控标签→恐慌做空→1h负费率"

---

## 共同步骤（新老通用）

### 流通市值

1. WebSearch 或 CMC 查流通量
2. 填入 `market_cap.circulating.<SYM>: <枚数>`
3. metrics 自动计算：市值 ATH/当前、OI/流通占比

### 标注 annotation YAML

```yaml
spot_note: '现货主战场: XXX'

panorama:
- time: 2026-04-12 06:00
  text: '+40.7%/h 史诗级爆拉\n74%仓位做空→逼空启动'
  kind: news         # news=红圈 / logic=蓝圈

zoom:
- time: 2026-04-18 18:00
  text: '-57.1%/h 史诗级踩踏'
  kind: news
```

**图上只标字母**，底部面板集中列文字。有 `spot_note` 就用，没有则自动生成默认文本。

### 制图

`python run.py plot`（关沙箱）。所有 bar（OI、成交量、费率）**1h 粒度**，和 K 线一一对应。多 regime 自动分文件 `_r1`/`_r2`。SVG 可在 Inkscape 编辑。

---

## 图表结构（7 行网格 + 通栏 + 底部面板）

| 行 | 内容 |
|----|------|
| 通栏 | 周线全程 + ATH/ATL + 市值 + OI/流通占比 + 高低位裁定 |
| 1 | 价格 K 线 + 字母标记（红=news，蓝=logic）|
| 2 | OI USDT 名义价值（柱，绿增红减，1h）|
| 3 | OI 币本位（柱，1h）|
| 4 | 成交量（合约左轴蓝 + 现货右轴橙，1h）|
| 5 | 大户多空比（折线）|
| 6 | 资金费率（柱，负红正绿，1h）|
| 底部 | 标注文字段落 + spot_note |

---

## 数据源对照

| 数据 | 老币源 | 新币源 | 限制 |
|------|--------|--------|------|
| Funding | dump `monthly/fundingRate` | `fapi.binance.com/fundingRate` | REST limit 1000 |
| 合约 1h K 线 | dump `klines/1h` | `fapi.binance.com/klines` | REST limit 1500 |
| OI + 多空比 | dump `daily/metrics` | `futures/data/openInterestHist` | **REST 仅 42h!** |
| 日线 | dump `klines/1d` | `fapi.binance.com/klines?interval=1d` | REST limit 500 |
| 币安现货 | dump `spot/klines/1h` | `api.binance.com/klines` | REST limit 1000 |
| 非币安现货 | CoinGecko `market_chart` daily | CoinGecko `tickers` + 个所 API | 历史过期 |

---

## 已知坑

1. **沙箱截断**：collect/plot 必须 `dangerouslyDisableSandbox: true`
2. **fapi.binance.com**：关沙箱后可用；`api.binance.com`（现货）同
3. **CoinGecko `total_volumes` 永远是 24h 滚动量**——bucket 时用 max 不求和
4. **新币 OI 只覆盖 42h**——全景图 pre 区域无 OI，等月度 dump 发布才完整
5. **REST API funding 无 `interval` 字段**——从时间戳间隔推算
6. **现货 K 线时间戳是微秒**（dump），合约是毫秒，spot_volume 源要 `//1000`
7. **annotation 文本含 `$` 触发 LaTeX 数学模式** → 全部去掉
8. **机制三分类**：A 暴涨逼空 / B 暴雷砸盘 / C 股票休市折价。A/B 做多=接飞刀
9. **多 regime 文件覆盖**：文件名加 `_r1`/`_r2` 后缀
10. **CoinGecko symbol 映射**：Binance symbol → CoinGecko id 需手动维护（`sources/coingecko_spot.py` 的 `SYM_TO_CG`）
