"""
Backtesting engine for strategy evaluation.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Callable
import json

from data.models import Market, Token, Side
from strategy.kelly import KellyCriterion
from analytics.performance.metrics import PerformanceMetrics


@dataclass
class BacktestConfig:
    """Configuration for backtest run."""
    starting_capital: float = 10.0
    max_position_size: float = 3.0
    max_total_exposure: float = 8.0
    kelly_fraction: float = 0.25
    min_edge: float = 0.05
    slippage: float = 0.01  # 1% slippage assumption
    commission: float = 0.0  # Polymarket is fee-free


@dataclass
class BacktestTrade:
    """Record of a simulated trade."""
    timestamp: datetime
    market_id: str
    market_question: str
    side: Side
    outcome: str
    entry_price: float
    size: float
    cost: float
    estimated_prob: float
    edge: float
    exit_price: Optional[float] = None
    exit_timestamp: Optional[datetime] = None
    pnl: float = 0.0
    resolved: bool = False
    won: bool = False


@dataclass
class BacktestResult:
    """Results from a backtest run."""
    config: BacktestConfig
    trades: list[BacktestTrade] = field(default_factory=list)
    daily_values: list[dict] = field(default_factory=list)
    metrics: Optional[PerformanceMetrics] = None

    # Summary stats
    total_trades: int = 0
    profitable_trades: int = 0
    total_pnl: float = 0.0
    final_value: float = 0.0
    max_drawdown: float = 0.0

    def summary(self) -> str:
        """Generate summary string."""
        if not self.metrics:
            return "No metrics calculated"

        return (
            f"Backtest Results\n"
            f"================\n"
            f"Period: {len(self.daily_values)} days\n"
            f"Total Trades: {self.total_trades}\n"
            f"Final Value: ${self.final_value:.2f}\n"
            f"Total P&L: ${self.total_pnl:+.2f}\n"
            f"Return: {(self.total_pnl / self.config.starting_capital) * 100:+.1f}%\n"
            f"Win Rate: {self.profitable_trades / self.total_trades * 100:.1f}%\n"
            f"Sharpe Ratio: {self.metrics.sharpe_ratio:.2f}\n"
            f"Max Drawdown: {self.max_drawdown:.1%}\n"
        )


class BacktestEngine:
    """
    Engine for backtesting trading strategies on historical data.

    Usage:
        engine = BacktestEngine(config)
        result = engine.run(historical_data, strategy_func)
    """

    def __init__(self, config: Optional[BacktestConfig] = None):
        self.config = config or BacktestConfig()
        self.kelly = KellyCriterion(kelly_fraction=self.config.kelly_fraction)

    def run(
        self,
        historical_data: list[dict],
        strategy_func: Callable[[dict, float], Optional[dict]],
    ) -> BacktestResult:
        """
        Run backtest on historical data.

        Args:
            historical_data: List of market snapshots with prices and resolution
            strategy_func: Function that takes (market_data, bankroll) and returns
                          trade signal or None

        Returns:
            BacktestResult with all trades and metrics
        """
        result = BacktestResult(config=self.config)

        capital = self.config.starting_capital
        positions: dict[str, BacktestTrade] = {}
        daily_values = []

        current_date = None

        for snapshot in historical_data:
            timestamp = snapshot.get("timestamp", datetime.now())
            snapshot_date = timestamp.date() if isinstance(timestamp, datetime) else timestamp

            # New day - record value
            if current_date != snapshot_date:
                position_value = sum(
                    p.size * snapshot.get("prices", {}).get(p.market_id, p.entry_price)
                    for p in positions.values()
                )
                daily_values.append({
                    "date": str(snapshot_date),
                    "capital": capital,
                    "position_value": position_value,
                    "total_value": capital + position_value,
                })
                current_date = snapshot_date

            # Check for resolutions
            for market_id, trade in list(positions.items()):
                resolution = snapshot.get("resolutions", {}).get(market_id)
                if resolution is not None:
                    # Market resolved
                    won = (
                        (resolution == "Yes" and trade.outcome == "Yes") or
                        (resolution == "No" and trade.outcome == "No")
                    )

                    if won:
                        payout = trade.size * 1.0  # Winners pay $1/share
                    else:
                        payout = 0.0

                    trade.exit_price = 1.0 if won else 0.0
                    trade.exit_timestamp = timestamp
                    trade.pnl = payout - trade.cost
                    trade.resolved = True
                    trade.won = won

                    capital += payout
                    del positions[market_id]

            # Get strategy signal
            bankroll = capital - sum(p.cost for p in positions.values())
            signal = strategy_func(snapshot, bankroll)

            if signal and bankroll > 0:
                market_id = signal["market_id"]

                # Skip if already have position
                if market_id in positions:
                    continue

                # Check exposure limits
                current_exposure = sum(p.cost for p in positions.values())
                if current_exposure >= self.config.max_total_exposure:
                    continue

                # Calculate position size
                size = min(
                    signal.get("size", 1.0),
                    self.config.max_position_size,
                    self.config.max_total_exposure - current_exposure,
                    bankroll * 0.9,  # Keep some buffer
                )

                if size <= 0:
                    continue

                # Apply slippage
                entry_price = signal["price"] * (1 + self.config.slippage)
                cost = size

                # Record trade
                trade = BacktestTrade(
                    timestamp=timestamp,
                    market_id=market_id,
                    market_question=signal.get("question", ""),
                    side=Side.BUY,
                    outcome=signal.get("outcome", "Yes"),
                    entry_price=entry_price,
                    size=size / entry_price,  # Shares
                    cost=cost,
                    estimated_prob=signal.get("probability", 0.5),
                    edge=signal.get("edge", 0.0),
                )

                positions[market_id] = trade
                result.trades.append(trade)
                capital -= cost

        # Final value
        final_position_value = sum(
            p.cost for p in positions.values()  # Use cost as proxy
        )
        result.final_value = capital + final_position_value
        result.daily_values = daily_values
        result.total_trades = len(result.trades)
        result.profitable_trades = sum(1 for t in result.trades if t.pnl > 0)
        result.total_pnl = result.final_value - self.config.starting_capital

        # Calculate metrics
        daily_returns = []
        for i in range(1, len(daily_values)):
            prev = daily_values[i - 1]["total_value"]
            curr = daily_values[i]["total_value"]
            if prev > 0:
                daily_returns.append((curr - prev) / prev)

        trade_dicts = [
            {"pnl": t.pnl, "edge": t.edge, "size": t.cost}
            for t in result.trades
        ]

        result.metrics = PerformanceMetrics.calculate(
            trades=trade_dicts,
            starting_capital=self.config.starting_capital,
            current_value=result.final_value,
            daily_returns=daily_returns,
        )

        result.max_drawdown = result.metrics.max_drawdown_pct

        return result

    def run_parameter_sweep(
        self,
        historical_data: list[dict],
        strategy_func: Callable,
        param_grid: dict[str, list],
    ) -> list[BacktestResult]:
        """
        Run backtest with different parameter combinations.

        Args:
            historical_data: Historical market data
            strategy_func: Strategy function
            param_grid: Dict of param_name -> list of values to try

        Returns:
            List of BacktestResult for each parameter combination
        """
        import itertools

        results = []

        # Generate all combinations
        param_names = list(param_grid.keys())
        param_values = list(param_grid.values())

        for combination in itertools.product(*param_values):
            params = dict(zip(param_names, combination))

            # Update config
            config = BacktestConfig(
                starting_capital=params.get("starting_capital", 10.0),
                max_position_size=params.get("max_position_size", 3.0),
                kelly_fraction=params.get("kelly_fraction", 0.25),
                min_edge=params.get("min_edge", 0.05),
            )

            engine = BacktestEngine(config)
            result = engine.run(historical_data, strategy_func)
            results.append(result)

        # Sort by Sharpe ratio
        results.sort(key=lambda r: r.metrics.sharpe_ratio if r.metrics else 0, reverse=True)

        return results


def simple_edge_strategy(snapshot: dict, bankroll: float) -> Optional[dict]:
    """
    Simple edge-based strategy for backtesting.

    Buys when estimated probability > market price + min_edge.
    """
    min_edge = 0.05

    markets = snapshot.get("markets", [])

    for market in markets:
        market_price = market.get("price", 0.5)
        estimated_prob = market.get("estimated_prob")

        if estimated_prob is None:
            continue

        edge = estimated_prob - market_price

        if edge > min_edge:
            # Calculate Kelly size
            odds = (1 - market_price) / market_price if market_price > 0 else 1
            kelly = (estimated_prob * odds - (1 - estimated_prob)) / odds
            size = bankroll * kelly * 0.25  # Quarter Kelly

            return {
                "market_id": market["id"],
                "question": market.get("question", ""),
                "outcome": "Yes",
                "price": market_price,
                "probability": estimated_prob,
                "edge": edge,
                "size": min(size, 3.0),  # Cap at $3
            }

    return None
