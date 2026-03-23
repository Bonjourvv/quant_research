# 镍价因子研究系统

这是一个面向期货研究的 Python 项目，当前以沪镍 `NI` 为核心研究对象，兼顾不锈钢 `SS` 的实时期限结构观察。

项目的目标不是单纯抓数据，而是把一条完整的研究链路串起来：

- 实时获取期货行情
- 拉取历史全合约数据
- 计算因子
- 做历史检验
- 输出图表，直接用于内部研究和汇报

---

## 目前已实现的因子

### 1. 展期收益率因子

用于观察期限结构，判断市场处于升水还是贴水。

公式：

```text
展期收益率 = [ln(远月价格) - ln(近月价格)] × 365 / (远月剩余天数 - 近月剩余天数)
```

业务含义：

- 负值：贴水，通常对应现货偏紧
- 正值：升水，通常对应供应偏松

当前已支持：

- 实时期限结构表
- 历史因子序列
- IC 分析
- 分组收益分析
- 回测净值图
- 滚动 IC 图

### 2. 价格动量因子

用于观察价格趋势是否延续。

当前输出内容包括：

- 最近 `20` 日动量
- 短长均线趋势强度
- 趋势标签：上涨 / 下跌 / 震荡
- 历史 IC 分析
- 分组收益
- 回测净值图

### 3. MACD 因子

用于观察趋势拐点和当前趋势状态。

当前输出内容包括：

- 金叉 / 死叉信号
- 当前趋势状态
- 当前持仓方向
- MACD 趋势图
- 信号收益统计

### 4. 虚实盘比因子

用于观察成交与持仓的关系，识别市场是短线高换手，还是增仓沉淀。

定义：

```text
虚实盘比 = 成交量 / 持仓量
```

当前输出内容包括：

- 历史主力合约虚实盘比序列
- 历史 IC 分析
- 分组收益
- 回测净值图
- 实时主力合约快照解读

---

## 项目结构

```text
nickel_research/
├── config/
│   └── settings.py              # 配置中心
├── data/
│   └── processed/               # 历史缓存、分析结果、图表输出
├── src/
│   ├── data_fetcher/            # 数据源客户端
│   │   ├── ths_client.py        # 同花顺实时数据
│   │   └── tushare_client.py    # Tushare历史数据
│   ├── factors/                 # 因子模块
│   │   ├── roll_yield.py
│   │   ├── momentum.py
│   │   ├── macd.py
│   │   ├── threshold.py
│   │   └── ic_analysis.py
│   ├── pipelines/               # 研究流程编排
│   └── plotting.py              # 图表公共配置
├── run_factors.py               # 统一 CLI 入口
├── .env.example                 # 环境变量模板
└── requirements.txt
```

---

## 环境准备

### 1. 安装依赖

```bash
cd nickel_research
pip3 install -r requirements.txt
```

建议使用项目虚拟环境运行。

### 2. 配置密钥

先复制模板：

```bash
cp .env.example .env
```

然后填写：

```bash
THS_REFRESH_TOKEN=同花顺refresh_token
TUSHARE_TOKEN=tushare_token
```

说明：

- `THS_REFRESH_TOKEN` 用于实时行情
- `TUSHARE_TOKEN` 用于历史日线和合约数据

---

## 如何运行

### 统一入口

项目统一从 [`run_factors.py`](/Users/vv/Downloads/nickel_research/run_factors.py) 进入。

常用命令：

```bash
python3 run_factors.py all
python3 run_factors.py realtime
python3 run_factors.py history
python3 run_factors.py threshold
python3 run_factors.py ic
python3 run_factors.py momentum
python3 run_factors.py macd
python3 run_factors.py virtual_ratio
```

常用参数：

```bash
python3 run_factors.py history --start-date 20200101
python3 run_factors.py history --no-cache
python3 run_factors.py ic --product NI
```

参数说明：

- `--product`：研究品种，默认 `NI`
- `--start-date`：历史起始日期
- `--end-date`：历史结束日期，默认今天
- `--min-oi`：最小持仓量过滤
- `--ry-method`：展期收益率汇总方法
- `--no-cache`：强制重新拉取历史数据

---

## 数据更新说明

### 实时数据

实时期限结构来自同花顺 API，盘中运行时会拿到当天实时行情。

### 历史数据

历史数据来自 Tushare，默认使用 `data/processed/` 下的缓存文件。

如果你想强制更新历史缓存，请运行：

```bash
python3 run_factors.py history --no-cache
```

注意：

- 历史日线通常只能更新到最近一个完整交易日
- 如果今天还在交易时段，最新历史日期可能是昨天

---

## 输出结果

主要输出目录是 [`data/processed`](/Users/vv/Downloads/nickel_research/data/processed)。

常见文件：

- `ni_contracts_daily.csv`：沪镍历史全合约日线缓存
- `ni_roll_yield_weighted_avg.csv`：展期收益率历史序列
- `ic_summary.csv`：IC 汇总
- `group_returns.csv`：分组收益
- `factor_returns.csv`：因子与未来收益对照表
- `backtest_nav.csv`：回测净值序列

图表输出示例：

- `roll_yield_backtest_nav.png`
- `roll_yield_rolling_ic.png`
- `roll_yield_group_returns.png`
- `momentum/momentum_backtest_nav.png`
- `momentum/momentum_rolling_ic.png`
- `momentum/momentum_group_returns.png`
- `macd/macd_chart.png`
- `virtual_ratio/virtual_real_ratio_signals.csv`

图表标题、图例、坐标轴已经改成中文，方便直接用于汇报。

---

## 当前支持范围

### 已经比较完整支持

- 沪镍 `NI`
  历史数据、实时分析、因子分析、图表输出都已接通

### 已部分支持

- 不锈钢 `SS`
  当前主要用于实时期限结构观察

---

## 如果后续要扩展到其他品种

当前这套框架是可以扩品种的，但历史部分目前本质上还是以沪镍为主。

如果后续想加铜、铝、螺纹等品种，优先看这几个文件：

[`config/settings.py`](/Users/vv/Downloads/nickel_research/config/settings.py)
这里维护默认配置和合约映射。

[`src/data_fetcher/tushare_client.py`](/Users/vv/Downloads/nickel_research/src/data_fetcher/tushare_client.py)
这里最关键。现在很多历史数据逻辑默认按 `NI` 写的，扩品种主要改这里。

[`src/pipelines/factor_pipeline.py`](/Users/vv/Downloads/nickel_research/src/pipelines/factor_pipeline.py)
这里控制整条研究流程，底层数据通用化后，这里基本可以直接复用。

推荐扩展顺序：

1. 先在 `tushare_client.py` 里支持新品种历史合约列表和日线数据
2. 再验证展期收益率逻辑是否适用于该品种
3. 最后复用动量、MACD、IC 和图表输出

---

## 直接运行单个因子文件

以下文件可以直接单独运行，并且只使用真实历史数据，不再使用模拟数据：

```bash
python3 src/factors/macd.py
python3 src/factors/momentum.py
```

如果缺少真实缓存，会直接报错提示先生成历史数据。

---

## 当前状态总结

这套系统目前已经具备一条完整的研究闭环：

- 可以看实时市场结构
- 可以做历史因子检验
- 可以生成中文图表用于汇报
- 可以继续往多因子组合和真实策略回测扩展

