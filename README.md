# 镍/不锈钢期货研究系统

## 项目结构

```
nickel_research/
├── config/
│   └── settings.py          ← 配置文件（填写 refresh_token）
├── src/
│   ├── data_fetcher/
│   │   └── ths_client.py    ← 同花顺API客户端
│   └── factors/
│       └── roll_yield.py    ← 展期收益率因子
├── run_factors.py           ← 🚀 因子监控脚本
└── requirements.txt
```

## 快速开始

### 1. 安装依赖

```bash
cd nickel_research
pip3 install -r requirements.txt
```

### 2. 配置 refresh_token

编辑 `config/settings.py`，填入 refresh_token：

```python
REFRESH_TOKEN = "你的refresh_token"
```

获取方式：
1. 打开 https://quantapi.10jqka.com.cn/gwstatic/static/ds_web/super-command-web/index.html#/AccountDetails
2. 用公司账号登录 (xmxy399 /)
3. 复制页面上的 refresh_token

### 3. 运行因子监控

```bash
python3 run_factors.py
```

## 因子说明

### 展期收益率 (Roll Yield)

**公式**：
```
展期收益率 = [ln(远月价格) - ln(近月价格)] × 365 / (远月剩余天数 - 近月剩余天数)
```

**含义**：
- **负值（贴水/backwardation）**：现货紧张，持有多头有额外收益 → 看涨信号
- **正值（升水/contango）**：供应充足，持有多头有展期损失 → 看跌信号

**来源**：银河期货《CTA截面策略》研报
