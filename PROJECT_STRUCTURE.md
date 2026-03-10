# 镍/不锈钢研究系统 - 项目结构详解

## 目录结构

```
nickel_research/
│
├── config/                     # 🔧 配置层
│   ├── __init__.py            
│   ├── settings.py            # API配置、合约代码等
│   └── .token_cache.json      # access_token缓存（自动生成）
│
├── src/                        # 📦 核心代码层
│   ├── __init__.py
│   │
│   ├── data_fetcher/          # 数据获取模块
│   │   ├── __init__.py
│   │   └── ths_client.py      # 同花顺API客户端
│   │
│   └── factors/               # 因子计算模块
│       ├── __init__.py
│       ├── roll_yield.py      # 展期收益率因子
│       ├── momentum.py        # [待添加] 动量因子
│       ├── basis.py           # [待添加] 基差因子
│       └── inventory.py       # [待添加] 库存因子
│
├── data/                       # 📊 数据存储层
│   ├── raw/                   # 原始数据
│   └── processed/             # 处理后数据
│
├── logs/                       # 📝 日志
│
├── run_factors.py             # 🚀 主运行脚本
├── requirements.txt           # 依赖包
└── README.md                  # 说明文档
```

---

## 各文件职责

### 1. config/settings.py — 配置中心

```python
# 存放所有配置，方便统一修改

REFRESH_TOKEN = "xxx"                    # 同花顺API令牌
API_BASE_URL = "https://quantapi.51ifind.com/api/v1"

# 合约代码
CONTRACTS = {
    'ni_main': 'niZL.SHF',      # 沪镍主力
    'ss_main': 'ssZL.SHF',      # 不锈钢主力
}

# 你可以添加更多配置，比如：
# ALERT_THRESHOLD = 0.05       # 信号阈值
# DATA_START_DATE = '20260101' # 数据起始日期
```

**何时修改**：更换API token、调整参数阈值、添加新品种

---

### 2. src/data_fetcher/ths_client.py — 数据获取

```python
class THSClient:
    """同花顺API的封装，所有数据请求都通过它"""
    
    def get_realtime_quote(self, codes):
        """获取实时行情（盘中）"""
        pass
    
    def get_history_quote(self, codes, start_date, end_date):
        """获取历史行情（更稳定）"""
        pass
```

**何时修改**：
- API返回格式变了 → 修改解析逻辑
- 需要新接口（如获取持仓量）→ 添加新方法

**添加新数据源示例**：
```python
# 如果以后要加Mysteel数据，创建新文件
# src/data_fetcher/mysteel_client.py

class MysteelClient:
    def get_inventory(self, product):
        """获取库存数据"""
        pass
```

---

### 3. src/factors/ — 因子计算

每个因子一个文件，结构统一：

```python
# src/factors/roll_yield.py

class RollYieldFactor:
    """展期收益率因子"""
    
    def __init__(self, ths_client=None):
        """初始化，可传入数据客户端"""
        pass
    
    def calculate(self, near_price, far_price, near_days, far_days):
        """核心计算逻辑（纯数学）"""
        pass
    
    def fetch_roll_yield(self, product):
        """获取数据 + 计算 + 返回结果"""
        pass
```

**添加新因子步骤**：

1. 创建文件 `src/factors/momentum.py`
2. 按相同结构写类
3. 在 `src/factors/__init__.py` 中注册：
   ```python
   from .roll_yield import RollYieldFactor
   from .momentum import MomentumFactor  # 新增
   ```
4. 在 `run_factors.py` 中调用

---

### 4. run_factors.py — 主入口

```python
"""
这是你日常运行的脚本
职责：调用各个因子，汇总输出结果
"""

def main():
    # 1. 加载配置/token
    token = load_token()
    
    # 2. 计算各因子
    analyze_product(token, 'ni', '沪镍')    # 展期收益率
    # calculate_momentum(token, 'ni')       # [待添加] 动量
    # calculate_basis(token, 'ni')          # [待添加] 基差
    
    # 3. 输出结果

if __name__ == '__main__':
    main()
```

**何时修改**：添加新因子后，在这里调用

---

## 如何添加新因子（以动量因子为例）

### 第一步：创建因子文件

```python
# src/factors/momentum.py

import math
from datetime import date, timedelta

class MomentumFactor:
    """
    动量因子
    
    公式: 过去N日收益率
    含义: 正动量 = 趋势向上，负动量 = 趋势向下
    """
    
    def __init__(self, lookback_days=20):
        self.lookback_days = lookback_days
    
    def calculate(self, prices: list) -> float:
        """
        计算动量
        
        Args:
            prices: 价格序列，从旧到新
            
        Returns:
            动量值（收益率）
        """
        if len(prices) < 2:
            return 0.0
        return (prices[-1] / prices[0]) - 1
    
    def fetch_momentum(self, token, product):
        """获取并计算动量"""
        # 1. 调用API获取历史价格
        # 2. 计算动量
        # 3. 返回结果
        pass
```

### 第二步：注册因子

```python
# src/factors/__init__.py

from .roll_yield import RollYieldFactor
from .momentum import MomentumFactor  # 新增这行
```

### 第三步：在主脚本中调用

```python
# run_factors.py

from src.factors.momentum import MomentumFactor

def main():
    # ... 现有代码 ...
    
    # 添加动量因子
    print('\n【动量因子】')
    momentum = MomentumFactor(lookback_days=20)
    result = momentum.fetch_momentum(token, 'ni')
    print(f'  沪镍20日动量: {result}')
```

---

## 数据流向图

```
┌─────────────────┐
│  同花顺API       │
│  (外部数据源)    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  ths_client.py  │  ← 数据获取层
│  (API封装)       │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  factors/       │  ← 因子计算层
│  - roll_yield   │
│  - momentum     │
│  - basis        │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  run_factors.py │  ← 展示层
│  (汇总输出)      │
└─────────────────┘
```
````
# print_analysis_report 里的循环
for period in [5, 10, 20]:
    result = self.calc_quantile_spread(period)
```

每个周期都独立执行一遍：
```
┌─────────────────────────────────────────────────────────────────┐
│  周期 = 5日                                                      │
├─────────────────────────────────────────────────────────────────┤
│  1. 计算每日的5日后收益                                          │
│     df['fwd_ret_5d'] = close[T+5] / close[T] - 1                │
│                                                                  │
│  2. 去掉末尾5行（无法计算收益）                                   │
│     valid = df.dropna()  → 有效样本N-5行                         │
│                                                                  │
│  3. 计算分位数阈值（基于有效样本）                                │
│     25%分位 = -2.39%                                             │
│     75%分位 = +2.96%                                             │
│                                                                  │
│  4. 筛选做多组/做空组                                            │
│     做多组: RY ≤ -2.39%                                          │
│     做空组: RY ≥ +2.96%                                          │
│                                                                  │
│  5. 计算各组的平均收益和胜率                                      │
└─────────────────────────────────────────────────────────────────┘
                              ↓
                         重复执行
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  周期 = 10日                                                     │
│  ...（同上，但有效样本是N-10行，阈值略有不同）                    │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  周期 = 20日                                                     │
│  ...（同上，但有效样本是N-20行）                                  │
└─────────────────────────────────────────────────────────────────┘


````
````
df[f'fwd_ret_{n}d'] = df['close'].shift(-n) / df['close'] - 1
```

这行代码对**每一行**（每一个交易日）都计算一个5日收益：

| 行 | T日 (信号日) | close[T] | T+5日 | close[T+5] | fwd_ret_5d |
|---|-------------|----------|-------|------------|------------|
| 0 | 2025-01-02 | 120000 | 2025-01-09 | 125000 | +4.17% |
| 1 | 2025-01-03 | 121000 | 2025-01-10 | 124000 | +2.48% |
| 2 | 2025-01-06 | 119000 | 2025-01-13 | 122000 | +2.52% |
| 3 | 2025-01-07 | 122000 | 2025-01-14 | 121000 | -0.82% |
| 4 | 2025-01-08 | 123000 | 2025-01-15 | 126000 | +2.44% |
| ... | ... | ... | ... | ... | ... |

---

## 图示
```
2025-01-02  01-03  01-06  01-07  01-08  01-09  01-10  01-13  01-14  01-15
    │        │      │      │      │      │      │      │      │      │
    T₀───────────────────────────►T₀+5   │      │      │      │
             T₁────────────────────────►T₁+5   │      │      │
                    T₂─────────────────────────►T₂+5  │      │
                           T₃──────────────────────────►T₃+5 │
                                  T₄───────────────────────────►T₄+5
````
---

## 命名规范

| 类型 | 规范 | 示例 |
|------|------|------|
| 文件名 | 小写+下划线 | `roll_yield.py` |
| 类名 | 大驼峰 | `RollYieldFactor` |
| 函数名 | 小写+下划线 | `calculate_roll_yield()` |
| 常量 | 全大写 | `API_BASE_URL` |

---

## 常见操作速查

| 我想要... | 修改哪里 |
|----------|---------|
| 换API token | `config/settings.py` |
| 添加新品种 | `run_factors.py` 中添加调用 |
| 添加新因子 | 创建 `src/factors/xxx.py` |
| 添加新数据源 | 创建 `src/data_fetcher/xxx.py` |
| 修改信号阈值 | `run_factors.py` 中的 `get_signal()` |
| 保存计算结果 | 写入 `data/processed/` |

---

## 下一步建议

1. **动量因子** — 最简单，只需要价格数据
2. **基差因子** — 需要现货价格
3. **库存因子** — 需要LME/上期所库存数据
4. **综合信号** — 多因子加权打分
