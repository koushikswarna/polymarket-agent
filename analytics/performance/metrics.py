"""
Performance metrics calculations.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class PerformanceMetrics:
    """
    Comprehensive trading performance metrics.

    Includes profitability, risk-adjusted returns, and trading statistics.
    """

    # Core P&L
    total_pnl: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0

    # Return metrics
    total_return_pct: float = 0.0
    daily_return_pct: float = 0.0
    annualized_return_pct: float = 0.0

    # Risk metrics
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    volatility: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0

    # Win/Loss stats
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0

    # Position stats
    avg_position_size: float = 0.0
    avg_holding_period_hours: float = 0.0
    max_concurrent_positions: int = 0

    # Edge stats
    avg_edge: float = 0.0
    edge_accuracy: float = 0.0  # How often edge direction was correct

    # LLM stats
    llm_cost: float = 0.0
    llm_roi: float = 0.0  # PnL / LLM cost

    # Time period
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    trading_days: int = 0

    @classmethod
    def calculate(
        cls,
        trades: list,
        starting_capital: float,
        current_value: float,
        daily_returns: list[float] = None,
        risk_free_rate: float = 0.05,  # 5% annual
    ) -> "PerformanceMetrics":
        """
        Calculate all performance metrics from trade history.

        Args:
            trades: List of trade dictionaries
            starting_capital: Initial capital
            current_value: Current portfolio value
            daily_returns: Optional list of daily returns for volatility calc
            risk_free_rate: Annual risk-free rate for Sharpe calculation

        Returns:
            PerformanceMetrics with all calculated fields
        """
        metrics = cls()

        if not trades:
            return metrics

        # Core P&L
        metrics.total_pnl = current_value - starting_capital
        metrics.total_return_pct = (
            metrics.total_pnl / starting_capital if starting_capital > 0 else 0
        )

        # Win/Loss stats
        metrics.total_trades = len(trades)
        wins = [t for t in trades if t.get("pnl", 0) > 0]
        losses = [t for t in trades if t.get("pnl", 0) < 0]

        metrics.winning_trades = len(wins)
        metrics.losing_trades = len(losses)
        metrics.win_rate = (
            metrics.winning_trades / metrics.total_trades
            if metrics.total_trades > 0
            else 0
        )

        # Average win/loss
        if wins:
            metrics.avg_win = sum(t["pnl"] for t in wins) / len(wins)
        if losses:
            metrics.avg_loss = abs(sum(t["pnl"] for t in losses) / len(losses))

        # Profit factor
        total_wins = sum(t["pnl"] for t in wins) if wins else 0
        total_losses = abs(sum(t["pnl"] for t in losses)) if losses else 0
        metrics.profit_factor = (
            total_wins / total_losses if total_losses > 0 else float("inf")
        )

        # Expectancy (expected value per trade)
        if metrics.total_trades > 0:
            metrics.expectancy = (
                metrics.win_rate * metrics.avg_win
                - (1 - metrics.win_rate) * metrics.avg_loss
            )

        # Volatility and Sharpe if we have daily returns
        if daily_returns and len(daily_returns) > 1:
            metrics.volatility = calculate_volatility(daily_returns)
            metrics.daily_return_pct = sum(daily_returns) / len(daily_returns)

            # Annualized metrics (assuming 252 trading days)
            metrics.annualized_return_pct = metrics.daily_return_pct * 252
            annualized_vol = metrics.volatility * math.sqrt(252)

            if annualized_vol > 0:
                metrics.sharpe_ratio = (
                    metrics.annualized_return_pct - risk_free_rate
                ) / annualized_vol

            # Sortino (only downside volatility)
            downside_returns = [r for r in daily_returns if r < 0]
            if downside_returns:
                downside_vol = calculate_volatility(downside_returns) * math.sqrt(252)
                if downside_vol > 0:
                    metrics.sortino_ratio = (
                        metrics.annualized_return_pct - risk_free_rate
                    ) / downside_vol

        # Max drawdown
        if daily_returns:
            metrics.max_drawdown, metrics.max_drawdown_pct = calculate_max_drawdown(
                daily_returns, starting_capital
            )

            # Calmar ratio (return / max drawdown)
            if metrics.max_drawdown_pct > 0:
                metrics.calmar_ratio = (
                    metrics.annualized_return_pct / metrics.max_drawdown_pct
                )

        # Edge stats
        edges = [t.get("edge", 0) for t in trades if "edge" in t]
        if edges:
            metrics.avg_edge = sum(edges) / len(edges)

            # Edge accuracy (was our direction correct?)
            correct = sum(
                1 for t in trades
                if (t.get("edge", 0) > 0 and t.get("pnl", 0) > 0)
                or (t.get("edge", 0) < 0 and t.get("pnl", 0) > 0)
            )
            metrics.edge_accuracy = correct / len(trades) if trades else 0

        return metrics

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "total_pnl": round(self.total_pnl, 2),
            "total_return_pct": round(self.total_return_pct * 100, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 2),
            "max_drawdown_pct": round(self.max_drawdown_pct * 100, 2),
            "win_rate": round(self.win_rate * 100, 2),
            "profit_factor": round(self.profit_factor, 2),
            "total_trades": self.total_trades,
            "expectancy": round(self.expectancy, 4),
        }

    def summary(self) -> str:
        """Generate human-readable summary."""
        return (
            f"Performance Summary\n"
            f"==================\n"
            f"Total P&L: ${self.total_pnl:+.2f} ({self.total_return_pct:+.1%})\n"
            f"Sharpe Ratio: {self.sharpe_ratio:.2f}\n"
            f"Max Drawdown: {self.max_drawdown_pct:.1%}\n"
            f"Win Rate: {self.win_rate:.1%} ({self.winning_trades}W/{self.losing_trades}L)\n"
            f"Profit Factor: {self.profit_factor:.2f}\n"
            f"Expectancy: ${self.expectancy:.4f}/trade\n"
        )


def calculate_volatility(returns: list[float]) -> float:
    """Calculate standard deviation of returns."""
    if len(returns) < 2:
        return 0.0

    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return math.sqrt(variance)


def calculate_max_drawdown(
    daily_returns: list[float],
    starting_capital: float,
) -> tuple[float, float]:
    """
    Calculate maximum drawdown.

    Returns:
        (max_drawdown_dollars, max_drawdown_pct)
    """
    peak = starting_capital
    max_dd = 0.0
    max_dd_pct = 0.0
    current = starting_capital

    for ret in daily_returns:
        current = current * (1 + ret)
        if current > peak:
            peak = current

        drawdown = peak - current
        drawdown_pct = drawdown / peak if peak > 0 else 0

        if drawdown > max_dd:
            max_dd = drawdown
            max_dd_pct = drawdown_pct

    return max_dd, max_dd_pct


def calculate_risk_adjusted_return(
    total_return: float,
    volatility: float,
    max_drawdown: float,
) -> dict:
    """Calculate various risk-adjusted return metrics."""
    return {
        "return_volatility_ratio": total_return / volatility if volatility > 0 else 0,
        "return_drawdown_ratio": total_return / max_drawdown if max_drawdown > 0 else 0,
    }
