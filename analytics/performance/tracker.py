"""
Real-time performance tracking.
"""

from datetime import datetime, date
from typing import Optional
from dataclasses import dataclass, field

from data.db import Database
from data.models import Position, Trade
from .metrics import PerformanceMetrics


@dataclass
class DailySnapshot:
    """Daily portfolio snapshot."""
    date: str
    starting_value: float
    ending_value: float
    realized_pnl: float
    unrealized_pnl: float
    trades_count: int
    wins: int
    losses: int


class PerformanceTracker:
    """
    Tracks and calculates real-time performance metrics.

    Maintains daily snapshots for time-series analysis.
    """

    def __init__(self, db: Database, starting_capital: float = 10.0):
        self.db = db
        self.starting_capital = starting_capital
        self.daily_snapshots: list[DailySnapshot] = []

    def record_daily_snapshot(self):
        """Record end-of-day snapshot."""
        today = date.today().isoformat()

        # Get current state
        positions = self.db.get_open_positions()
        daily_stats = self.db.get_today_stats()

        # Calculate values
        position_value = sum(p.market_value for p in positions)
        balance = self.starting_capital  # Would come from API in production

        snapshot = DailySnapshot(
            date=today,
            starting_value=self.starting_capital,
            ending_value=balance + position_value,
            realized_pnl=daily_stats.realized_pnl,
            unrealized_pnl=daily_stats.unrealized_pnl,
            trades_count=daily_stats.trades_count,
            wins=daily_stats.wins,
            losses=daily_stats.losses,
        )

        self.daily_snapshots.append(snapshot)
        return snapshot

    def get_current_metrics(self) -> PerformanceMetrics:
        """Calculate current performance metrics."""
        # Get all trades
        trades = self.db.get_recent_trades(limit=1000)
        trade_dicts = [
            {
                "pnl": t.cost if t.side.value == "BUY" else -t.cost,
                "size": t.size,
                "price": t.price,
            }
            for t in trades
        ]

        # Get current portfolio value
        positions = self.db.get_open_positions()
        position_value = sum(p.market_value for p in positions)
        realized = self.db.get_total_realized_pnl()
        current_value = self.starting_capital + realized + sum(
            p.unrealized_pnl for p in positions
        )

        # Calculate daily returns if we have snapshots
        daily_returns = []
        for i in range(1, len(self.daily_snapshots)):
            prev = self.daily_snapshots[i - 1].ending_value
            curr = self.daily_snapshots[i].ending_value
            if prev > 0:
                daily_returns.append((curr - prev) / prev)

        return PerformanceMetrics.calculate(
            trades=trade_dicts,
            starting_capital=self.starting_capital,
            current_value=current_value,
            daily_returns=daily_returns,
        )

    def get_equity_curve(self) -> list[dict]:
        """Get equity curve data for charting."""
        curve = [{"date": "start", "value": self.starting_capital}]

        for snapshot in self.daily_snapshots:
            curve.append({
                "date": snapshot.date,
                "value": snapshot.ending_value,
            })

        return curve

    def get_drawdown_series(self) -> list[dict]:
        """Get drawdown over time."""
        series = []
        peak = self.starting_capital

        for snapshot in self.daily_snapshots:
            if snapshot.ending_value > peak:
                peak = snapshot.ending_value

            drawdown = (peak - snapshot.ending_value) / peak if peak > 0 else 0

            series.append({
                "date": snapshot.date,
                "drawdown": drawdown,
                "peak": peak,
                "value": snapshot.ending_value,
            })

        return series

    def get_rolling_sharpe(self, window: int = 30) -> list[dict]:
        """Calculate rolling Sharpe ratio."""
        series = []

        for i in range(window, len(self.daily_snapshots)):
            window_snapshots = self.daily_snapshots[i - window:i]

            # Calculate returns in window
            returns = []
            for j in range(1, len(window_snapshots)):
                prev = window_snapshots[j - 1].ending_value
                curr = window_snapshots[j].ending_value
                if prev > 0:
                    returns.append((curr - prev) / prev)

            if returns:
                from .metrics import calculate_volatility
                import math

                mean_return = sum(returns) / len(returns)
                volatility = calculate_volatility(returns)

                sharpe = 0
                if volatility > 0:
                    annualized_return = mean_return * 252
                    annualized_vol = volatility * math.sqrt(252)
                    sharpe = annualized_return / annualized_vol

                series.append({
                    "date": window_snapshots[-1].date,
                    "sharpe": sharpe,
                })

        return series

    def get_win_rate_by_category(self) -> dict:
        """Get win rate breakdown by market category."""
        # This would require category tracking in trades
        # Placeholder for now
        return {}

    def get_pnl_by_strategy(self) -> dict:
        """Get P&L breakdown by strategy type."""
        trades = self.db.get_recent_trades(limit=1000)

        strategies = {}
        for trade in trades:
            reason = trade.reason
            strategy = "unknown"

            if "Edge" in reason:
                strategy = "edge"
            elif "Arbitrage" in reason:
                strategy = "arbitrage"

            if strategy not in strategies:
                strategies[strategy] = {"count": 0, "pnl": 0}

            strategies[strategy]["count"] += 1
            # Would need actual PnL tracking per trade

        return strategies

    def summary_report(self) -> str:
        """Generate text summary report."""
        metrics = self.get_current_metrics()
        return metrics.summary()
