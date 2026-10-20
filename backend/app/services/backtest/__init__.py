"""回测子系统(阶段2)。

```text
backtest/
├── engine.py     日线事件驱动引擎(纯逻辑)
├── cost_model.py A 股真实费率(复用 core/cost_engine)
└── metrics.py    绩效指标(纯函数)
```
"""
from app.services.backtest.cost_model import DEFAULT_COST_MODEL, CostModel
from app.services.backtest.engine import (
    BacktestEngine,
    BacktestResult,
    Position,
    Trade,
)
from app.services.backtest.metrics import PerformanceMetrics, compute_metrics

__all__ = [
    "BacktestEngine",
    "BacktestResult",
    "CostModel",
    "DEFAULT_COST_MODEL",
    "PerformanceMetrics",
    "Position",
    "Trade",
    "compute_metrics",
]
