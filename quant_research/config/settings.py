"""
项目配置中心。

优先从环境变量读取敏感配置；如果项目根目录存在 `.env` 文件，
会在导入时做一次轻量加载，便于本地研究使用。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict


def _load_local_env() -> None:
    """从项目根目录加载简单的 KEY=VALUE 配置。"""
    project_root = Path(__file__).resolve().parent.parent
    env_file = project_root / ".env"

    if not env_file.exists():
        return

    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')

        if key and key not in os.environ:
            os.environ[key] = value


_load_local_env()


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"

REFRESH_TOKEN = os.getenv("THS_REFRESH_TOKEN", "eyJzaWduX3RpbWUiOiIyMDI2LTA0LTAyIDE1OjQwOjQzIn0=.eyJ1aWQiOiI2ODY0MjMzODciLCJ1c2VyIjp7InJlZnJlc2hUb2tlbkV4cGlyZWRUaW1lIjoiMjAyNy0wMy0zMSAwOToyNTowMSIsInVzZXJJZCI6IjY4NjQyMzM4NyJ9fQ==.B14C81B62AC7C6E353E16AC6AE38B26F3EEEFC4CC5237A8BC32314F46EF9DF8C")
API_BASE_URL = os.getenv("THS_API_BASE_URL", "https://quantapi.51ifind.com/api/v1")

TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "d756df50b2e02826dd08d959aa08b933d52966a2eeb867eecb504b11")
TUSHARE_BASE_URL = os.getenv("TUSHARE_BASE_URL", "http://tushare.xyz")
FRED_API_KEY = os.getenv("FRED_API_KEY", "")

CONTRACTS: Dict[str, str] = {
    "ni_main": "niZL.SHF",
    "ss_main": "ssZL.SHF",
}

QUOTE_FIELDS = "open;high;low;close;volume;amount;openInterest;settlement"

PRODUCT_CONFIG: Dict[str, Dict[str, str]] = {
    "NI": {"name": "沪镍", "exchange": "SHFE"},
    "SS": {"name": "不锈钢", "exchange": "SHFE"},
    "CU": {"name": "沪铜", "exchange": "SHFE"},
}

DEFAULT_PRODUCT = "NI"
DEFAULT_START_DATE = "20150401"
DEFAULT_MIN_OI = 1000
DEFAULT_RY_METHOD = "weighted_avg"
