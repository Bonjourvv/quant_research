# 镍/不锈钢研究系统 - 项目结构

## 当前结构

```text
nickel_research/
├── config/                         # 配置层
│   ├── __init__.py
│   ├── settings.py                 # 环境变量、默认参数、品种配置
│   └── .token_cache.json           # 同花顺 access_token 缓存（自动生成）
├── data/
│   ├── raw/                        # 原始外部数据缓存
│   │   └── fred/
│   │       ├── sp500.csv
│   │       └── vixcls.csv
│   ├── processed/                  # 研究结果与图表输出
│   │   ├── ni/                     # 沪镍因子输出
│   │   ├── ss/                     # 不锈钢因子输出
│   │   ├── summary/                # 双品种汇总页
│   │   ├── comparison/             # 品种影响对比回测
│   │   ├── vix_panic_reversion/    # 标普版 VIX+RSI 策略结果
│   │   └── ni_vix_panic_reversion/ # 沪镍版 VIX+RSI 策略结果
│   ├── ni_contracts_test.csv       # 临时测试数据
│   └── VIXCLS.csv                  # 旧版手工下载文件
├── scripts/
│   └── fetch_fred_series.py        # FRED 时间序列抓取脚本
├── src/
│   ├── __init__.py
│   ├── plotting.py                 # 中文字体与图表公共配置
│   ├── data_fetcher/               # 数据源客户端
│   │   ├── __init__.py
│   │   ├── ths_client.py           # 同花顺实时/高频
│   │   ├── tushare_client.py       # Tushare 历史期货数据
│   │   └── fred_client.py          # FRED 宏观序列
│   ├── factors/                    # 因子研究模块
│   │   ├── __init__.py
│   │   ├── roll_yield.py           # 展期收益率因子
│   │   ├── momentum.py             # 价格动量因子
│   │   ├── macd.py                 # MACD 因子
│   │   ├── virtual_real_ratio.py   # 虚实盘比因子
│   │   ├── threshold.py            # 分位数阈值
│   │   └── ic_analysis.py          # IC / 分组收益 / 回测图
│   ├── strategies/                 # 单标的策略回测模块
│   │   ├── __init__.py
│   │   ├── vix_panic_reversion.py  # 标普500 + VIX + RSI 策略
│   │   └── ni_vix_panic_reversion.py
│   │                                  # 沪镍主力连续 + VIX + RSI 策略
│   └── pipelines/
│       ├── __init__.py
│       └── factor_pipeline.py      # 所有模式的编排层
├── run_factors.py                  # 统一 CLI 入口
├── roll_yield_history.py           # 历史展期收益率兼容入口
├── README.md                       # 使用说明
├── PROJECT_STRUCTURE.md            # 本文件
├── requirements.txt                # 依赖
├── .env.example                    # 环境变量模板
└── .env                            # 本地私有配置（不提交）
```

---

## 架构分层

### 1. 配置层

核心文件：
[`config/settings.py`](/Users/vv/Downloads/nickel_research/config/settings.py)

职责：

- 加载 `.env`
- 提供 `THS / Tushare / FRED` 密钥
- 定义默认参数
- 维护品种配置，如 `NI / SS`

这层只负责“配置”，不负责业务逻辑。

---

### 2. 数据源层

目录：
[`src/data_fetcher`](/Users/vv/Downloads/nickel_research/src/data_fetcher)

包含三个客户端：

- [`src/data_fetcher/ths_client.py`](/Users/vv/Downloads/nickel_research/src/data_fetcher/ths_client.py)
  同花顺实时行情与分钟数据
- [`src/data_fetcher/tushare_client.py`](/Users/vv/Downloads/nickel_research/src/data_fetcher/tushare_client.py)
  期货历史日线、合约列表、主力映射
- [`src/data_fetcher/fred_client.py`](/Users/vv/Downloads/nickel_research/src/data_fetcher/fred_client.py)
  宏观序列，如 `VIXCLS`、`SP500`

职责：

- 对外部接口做统一封装
- 返回标准化 DataFrame
- 管理原始缓存

这层不负责因子判断和策略信号。

---

### 3. 因子研究层

目录：
[`src/factors`](/Users/vv/Downloads/nickel_research/src/factors)

当前包括：

- [`src/factors/roll_yield.py`](/Users/vv/Downloads/nickel_research/src/factors/roll_yield.py)
- [`src/factors/momentum.py`](/Users/vv/Downloads/nickel_research/src/factors/momentum.py)
- [`src/factors/macd.py`](/Users/vv/Downloads/nickel_research/src/factors/macd.py)
- [`src/factors/virtual_real_ratio.py`](/Users/vv/Downloads/nickel_research/src/factors/virtual_real_ratio.py)
- [`src/factors/threshold.py`](/Users/vv/Downloads/nickel_research/src/factors/threshold.py)
- [`src/factors/ic_analysis.py`](/Users/vv/Downloads/nickel_research/src/factors/ic_analysis.py)

职责：

- 计算因子值
- 生成因子信号
- 做 IC、分组收益、回测图

这层回答的是：
“这个指标有没有解释力？”

---

### 4. 策略回测层

目录：
[`src/strategies`](/Users/vv/Downloads/nickel_research/src/strategies)

当前包括：

- [`src/strategies/vix_panic_reversion.py`](/Users/vv/Downloads/nickel_research/src/strategies/vix_panic_reversion.py)
- [`src/strategies/ni_vix_panic_reversion.py`](/Users/vv/Downloads/nickel_research/src/strategies/ni_vix_panic_reversion.py)

职责：

- 定义开平仓规则
- 生成仓位序列
- 做单标的净值回测
- 输出绩效指标和策略图

这层回答的是：
“这套交易规则能不能赚钱？”

---

### 5. 编排层

核心文件：
[`src/pipelines/factor_pipeline.py`](/Users/vv/Downloads/nickel_research/src/pipelines/factor_pipeline.py)

职责：

- 串联数据获取、因子计算、导出结果
- 管理各模式入口
- 生成汇总页与对比页

支持的模式包括：

- `realtime`
- `history`
- `threshold`
- `ic`
- `momentum`
- `macd`
- `virtual_ratio`
- `summary`
- `compare`
- `vix_panic`
- `ni_vix_panic`
- `all`

---

### 6. 入口层

核心文件：
[`run_factors.py`](/Users/vv/Downloads/nickel_research/run_factors.py)

职责：

- 解析命令行参数
- 创建 `ResearchConfig`
- 调用 `run_mode`

你日常基本只需要用这个文件。

---

## 数据流

### 因子研究主线

```text
外部数据源
  -> data_fetcher
  -> factors
  -> ic_analysis / 图表
  -> data/processed/{ni|ss}/...
```

### 策略回测主线

```text
FRED / Tushare
  -> strategies
  -> 回测净值 / 绩效指标
  -> data/processed/vix_panic_reversion 或 ni_vix_panic_reversion
```

---

## 当前最重要的输出目录

### 品种因子结果

- [`data/processed/ni`](/Users/vv/Downloads/nickel_research/data/processed/ni)
- [`data/processed/ss`](/Users/vv/Downloads/nickel_research/data/processed/ss)

### 双品种汇总

- [`data/processed/summary`](/Users/vv/Downloads/nickel_research/data/processed/summary)

### 品种影响对比

- [`data/processed/comparison`](/Users/vv/Downloads/nickel_research/data/processed/comparison)

### 策略回测

- [`data/processed/vix_panic_reversion`](/Users/vv/Downloads/nickel_research/data/processed/vix_panic_reversion)
- [`data/processed/ni_vix_panic_reversion`](/Users/vv/Downloads/nickel_research/data/processed/ni_vix_panic_reversion)

---

## 当前存在的杂项

目前仓库里还有几个非核心残留：

- [`data/VIXCLS.csv`](/Users/vv/Downloads/nickel_research/data/VIXCLS.csv)
- [`data/ni_contracts_test.csv`](/Users/vv/Downloads/nickel_research/data/ni_contracts_test.csv)
- 异常目录 [`{config,src`](/Users/vv/Downloads/nickel_research/%7Bconfig,src)

这些不会影响运行，但属于后续可以继续清理的历史遗留物。
