#!/usr/bin/env python3
"""历史展期收益率的兼容入口。"""

from src.pipelines.factor_pipeline import ResearchConfig, run_history


def main() -> None:
    run_history(ResearchConfig())


if __name__ == "__main__":
    main()
