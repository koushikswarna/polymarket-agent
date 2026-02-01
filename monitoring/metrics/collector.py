"""
Metrics collection for observability.

Collects and tracks key metrics about the trading system:
- Trading performance metrics
- System health metrics
- API usage metrics

These metrics help you understand how the bot is performing
and identify issues before they become problems.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
from collections import defaultdict
import json
from pathlib import Path


@dataclass
class MetricPoint:
    """A single metric measurement."""
    name: str
    value: float
    timestamp: datetime = field(default_factory=datetime.utcnow)
    tags: Dict[str, str] = field(default_factory=dict)


class MetricsCollector:
    """
    Collects and stores trading metrics.

    Metrics are useful for:
    - Understanding performance over time
    - Identifying trends and patterns
    - Debugging issues
    - Optimizing strategy parameters

    Example usage:
        collector = MetricsCollector()

        # Record metrics
        collector.record("trades.executed", 1, tags={"side": "buy"})
        collector.record("pnl.realized", 1.50)
        collector.record("api.latency_ms", 150, tags={"api": "gamma"})

        # Get metrics summary
        print(collector.summary())
    """

    def __init__(self, storage_path: Optional[Path] = None):
        """
        Initialize the metrics collector.

        Args:
            storage_path: Optional path to persist metrics
        """
        self.storage_path = storage_path
        self.metrics: Dict[str, List[MetricPoint]] = defaultdict(list)
        self.counters: Dict[str, float] = defaultdict(float)

        # Load existing metrics if available
        if storage_path and storage_path.exists():
            self._load()

    def record(
        self,
        name: str,
        value: float,
        tags: Optional[Dict[str, str]] = None,
    ):
        """
        Record a metric value.

        Args:
            name: Metric name (use dots for hierarchy, e.g., "trades.executed")
            value: The metric value
            tags: Optional tags for filtering/grouping
        """
        point = MetricPoint(
            name=name,
            value=value,
            tags=tags or {},
        )
        self.metrics[name].append(point)

        # Keep only last 10000 points per metric
        if len(self.metrics[name]) > 10000:
            self.metrics[name] = self.metrics[name][-10000:]

    def increment(self, name: str, amount: float = 1.0):
        """
        Increment a counter metric.

        Counters are useful for things like:
        - Number of trades
        - Number of API calls
        - Number of errors
        """
        self.counters[name] += amount
        self.record(name, self.counters[name])

    def gauge(self, name: str, value: float):
        """
        Set a gauge metric (current value).

        Gauges are useful for things like:
        - Current balance
        - Open positions count
        - Current P&L
        """
        self.record(name, value)

    def timer(self, name: str, duration_ms: float):
        """
        Record a timing metric.

        Useful for tracking latency and performance.
        """
        self.record(name, duration_ms, tags={"unit": "ms"})

    def get_latest(self, name: str) -> Optional[float]:
        """Get the most recent value for a metric."""
        points = self.metrics.get(name, [])
        return points[-1].value if points else None

    def get_average(self, name: str, last_n: int = 100) -> Optional[float]:
        """Get the average of the last N values."""
        points = self.metrics.get(name, [])[-last_n:]
        if not points:
            return None
        return sum(p.value for p in points) / len(points)

    def get_min_max(self, name: str) -> tuple[Optional[float], Optional[float]]:
        """Get min and max values for a metric."""
        points = self.metrics.get(name, [])
        if not points:
            return None, None
        values = [p.value for p in points]
        return min(values), max(values)

    def summary(self) -> str:
        """Generate a summary of all metrics."""
        lines = ["Metrics Summary", "=" * 40]

        # Counters
        if self.counters:
            lines.append("\nCounters:")
            for name, value in sorted(self.counters.items()):
                lines.append(f"  {name}: {value:.2f}")

        # Recent values
        lines.append("\nRecent Values:")
        for name in sorted(self.metrics.keys()):
            latest = self.get_latest(name)
            avg = self.get_average(name)
            if latest is not None:
                lines.append(f"  {name}: {latest:.4f} (avg: {avg:.4f})")

        return "\n".join(lines)

    def to_dict(self) -> dict:
        """Export metrics to a dictionary."""
        return {
            "counters": dict(self.counters),
            "latest_values": {
                name: self.get_latest(name)
                for name in self.metrics
            },
            "averages": {
                name: self.get_average(name)
                for name in self.metrics
            },
        }

    def _save(self):
        """Persist metrics to disk."""
        if not self.storage_path:
            return

        data = {
            "counters": self.counters,
            "metrics": {
                name: [
                    {
                        "value": p.value,
                        "timestamp": p.timestamp.isoformat(),
                        "tags": p.tags,
                    }
                    for p in points[-1000:]  # Only save last 1000 per metric
                ]
                for name, points in self.metrics.items()
            },
        }

        with open(self.storage_path, "w") as f:
            json.dump(data, f)

    def _load(self):
        """Load metrics from disk."""
        if not self.storage_path or not self.storage_path.exists():
            return

        try:
            with open(self.storage_path) as f:
                data = json.load(f)

            self.counters = defaultdict(float, data.get("counters", {}))

            for name, points in data.get("metrics", {}).items():
                for p in points:
                    self.metrics[name].append(MetricPoint(
                        name=name,
                        value=p["value"],
                        timestamp=datetime.fromisoformat(p["timestamp"]),
                        tags=p.get("tags", {}),
                    ))
        except Exception:
            pass  # Ignore load errors


# Standard metrics names for consistency
class MetricNames:
    """Standard metric names used throughout the system."""

    # Trading metrics
    TRADES_EXECUTED = "trades.executed"
    TRADES_FAILED = "trades.failed"
    POSITIONS_OPENED = "positions.opened"
    POSITIONS_CLOSED = "positions.closed"

    # P&L metrics
    PNL_REALIZED = "pnl.realized"
    PNL_UNREALIZED = "pnl.unrealized"
    PNL_TOTAL = "pnl.total"

    # Risk metrics
    EXPOSURE_CURRENT = "risk.exposure"
    DRAWDOWN_CURRENT = "risk.drawdown"

    # API metrics
    API_CALLS_GAMMA = "api.calls.gamma"
    API_CALLS_CLOB = "api.calls.clob"
    API_LATENCY_GAMMA = "api.latency.gamma"
    API_LATENCY_CLOB = "api.latency.clob"

    # LLM metrics
    LLM_CALLS_CLAUDE = "llm.calls.claude"
    LLM_CALLS_GPT = "llm.calls.gpt"
    LLM_COST_CLAUDE = "llm.cost.claude"
    LLM_COST_GPT = "llm.cost.gpt"

    # System metrics
    LOOP_DURATION = "system.loop_duration"
    ERRORS = "system.errors"
