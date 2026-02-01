#!/usr/bin/env python3
"""
Run backtests on historical data.

Usage:
    python scripts/run_backtest.py --strategy edge --days 30
"""

import argparse
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from analytics.backtesting.engine import BacktestEngine, BacktestConfig, simple_edge_strategy


def main():
    parser = argparse.ArgumentParser(description="Run strategy backtests")
    parser.add_argument("--strategy", default="edge", help="Strategy to test")
    parser.add_argument("--days", type=int, default=30, help="Days of history")
    parser.add_argument("--capital", type=float, default=10.0, help="Starting capital")

    args = parser.parse_args()

    print(f"Running backtest: {args.strategy} strategy over {args.days} days")
    print(f"Starting capital: ${args.capital}")
    print("=" * 50)

    # Configure backtest
    config = BacktestConfig(
        starting_capital=args.capital,
        max_position_size=3.0,
        kelly_fraction=0.25,
    )

    engine = BacktestEngine(config)

    # Generate sample historical data (in production, load real data)
    from datetime import datetime, timedelta
    import random

    historical_data = []
    for day in range(args.days):
        timestamp = datetime.utcnow() - timedelta(days=args.days - day)

        # Simulate market data
        markets = []
        for i in range(5):
            base_price = 0.3 + random.random() * 0.4
            estimated_prob = base_price + (random.random() - 0.5) * 0.2

            markets.append({
                "id": f"market_{i}",
                "question": f"Test market {i}",
                "price": base_price,
                "estimated_prob": estimated_prob,
            })

        # Simulate some resolutions
        resolutions = {}
        if day > 10 and random.random() < 0.1:
            # Randomly resolve some markets
            market_id = f"market_{random.randint(0, 4)}"
            resolutions[market_id] = "Yes" if random.random() > 0.5 else "No"

        historical_data.append({
            "timestamp": timestamp,
            "markets": markets,
            "resolutions": resolutions,
            "prices": {f"market_{i}": markets[i]["price"] for i in range(5)},
        })

    # Run backtest
    result = engine.run(historical_data, simple_edge_strategy)

    # Print results
    print("\nBacktest Results")
    print("=" * 50)
    print(result.summary())

    return 0


if __name__ == "__main__":
    sys.exit(main())
