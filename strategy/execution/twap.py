"""
TWAP (Time-Weighted Average Price) execution.

TWAP breaks up large orders into smaller pieces executed over time.
This minimizes market impact and helps achieve a better average price.

When to use TWAP:
- Large orders relative to market depth
- Non-urgent trades where you can wait
- When you want to minimize price impact
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Callable

from data.models import Order, Side, OrderType


@dataclass
class TWAPConfig:
    """Configuration for TWAP execution."""
    total_size: float           # Total size to execute
    duration_minutes: int       # How long to spread execution
    num_slices: int             # Number of individual orders
    randomize_timing: bool      # Add randomness to timing
    max_slice_slippage: float   # Max slippage per slice


@dataclass
class TWAPProgress:
    """Progress of a TWAP execution."""
    total_size: float
    filled_size: float
    remaining_size: float
    slices_completed: int
    slices_total: int
    average_fill_price: float
    started_at: datetime
    expected_completion: datetime


class TWAPExecutor:
    """
    Executes orders using TWAP strategy.

    TWAP (Time-Weighted Average Price) is a strategy that breaks
    large orders into smaller pieces and executes them over time.

    Benefits:
    - Reduces market impact
    - Achieves better average price
    - Hides order intent from other traders

    Example usage:
        executor = TWAPExecutor(client)

        config = TWAPConfig(
            total_size=100,
            duration_minutes=30,
            num_slices=10,
            randomize_timing=True,
            max_slice_slippage=0.01
        )

        # Start TWAP execution
        await executor.execute(
            token_id="btc_yes",
            side=Side.BUY,
            target_price=0.45,
            config=config,
            on_progress=lambda p: print(f"Progress: {p.filled_size}/{p.total_size}")
        )
    """

    def __init__(self, client):
        """
        Initialize the TWAP executor.

        Args:
            client: PolymarketClient for order execution
        """
        self.client = client
        self._active_executions: dict[str, TWAPProgress] = {}

    async def execute(
        self,
        token_id: str,
        side: Side,
        target_price: float,
        config: TWAPConfig,
        on_progress: Optional[Callable[[TWAPProgress], None]] = None,
    ) -> TWAPProgress:
        """
        Execute a TWAP order.

        Args:
            token_id: Token to trade
            side: BUY or SELL
            target_price: Target price (will adjust for slippage)
            config: TWAP configuration
            on_progress: Optional callback for progress updates

        Returns:
            Final TWAPProgress with execution results
        """
        import random

        # Calculate timing
        slice_size = config.total_size / config.num_slices
        base_interval = (config.duration_minutes * 60) / config.num_slices

        # Initialize progress
        progress = TWAPProgress(
            total_size=config.total_size,
            filled_size=0,
            remaining_size=config.total_size,
            slices_completed=0,
            slices_total=config.num_slices,
            average_fill_price=0,
            started_at=datetime.utcnow(),
            expected_completion=datetime.utcnow() + timedelta(minutes=config.duration_minutes),
        )

        fill_prices = []

        for i in range(config.num_slices):
            # Get current market price
            current_price = self.client.get_midpoint_price(token_id) or target_price

            # Calculate this slice's price (with slippage allowance)
            if side == Side.BUY:
                slice_price = min(
                    current_price * (1 + config.max_slice_slippage),
                    target_price * (1 + config.max_slice_slippage)
                )
            else:
                slice_price = max(
                    current_price * (1 - config.max_slice_slippage),
                    target_price * (1 - config.max_slice_slippage)
                )

            # Execute slice
            order = self.client.place_order(
                token_id=token_id,
                side=side,
                price=slice_price,
                size=slice_size,
                order_type=OrderType.IOC,
            )

            if order and order.filled_size > 0:
                progress.filled_size += order.filled_size
                fill_prices.append((order.price, order.filled_size))

            progress.remaining_size = config.total_size - progress.filled_size
            progress.slices_completed = i + 1

            # Calculate weighted average price
            if fill_prices:
                total_value = sum(p * s for p, s in fill_prices)
                total_size = sum(s for _, s in fill_prices)
                progress.average_fill_price = total_value / total_size if total_size > 0 else 0

            # Notify progress
            if on_progress:
                on_progress(progress)

            # Wait for next slice (except on last one)
            if i < config.num_slices - 1:
                wait_time = base_interval
                if config.randomize_timing:
                    # Add ±20% randomness
                    wait_time *= (0.8 + random.random() * 0.4)
                await asyncio.sleep(wait_time)

        return progress

    def cancel_execution(self, execution_id: str) -> bool:
        """
        Cancel an active TWAP execution.

        Note: Already executed slices cannot be undone.
        """
        if execution_id in self._active_executions:
            del self._active_executions[execution_id]
            return True
        return False

    def get_progress(self, execution_id: str) -> Optional[TWAPProgress]:
        """Get progress of an active execution."""
        return self._active_executions.get(execution_id)
