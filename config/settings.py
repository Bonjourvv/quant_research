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

REFRESH_TOKEN = os.getenv("THS_REFRESH_TOKEN", "")
API_BASE_URL = os.getenv("THS_API_BASE_URL", "https://quantapi.51ifind.com/api/v1")

TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "")
TUSHARE_BASE_URL = os.getenv("TUSHARE_BASE_URL", "http://tushare.xyz")

CONTRACTS: Dict[str, str] = {
    "ni_main": "niZL.SHF",
    "ss_main": "ssZL.SHF",
}

QUOTE_FIELDS = "open;high;low;close;volume;amount;openInterest;settlement"

DEFAULT_PRODUCT = "NI"
DEFAULT_START_DATE = "20150401"
DEFAULT_MIN_OI = 1000
DEFAULT_RY_METHOD = "weighted_avg"
