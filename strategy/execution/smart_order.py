"""
Smart order routing for optimal execution.

This module routes orders intelligently to minimize slippage
and maximize fill rates. It analyzes order book depth and
chooses the best execution strategy.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from data.models import Order, OrderType, Side


class ExecutionStrategy(Enum):
    """Available execution strategies."""
    LIMIT = "limit"           # Place and wait
    IOC = "ioc"               # Immediate or cancel
    TWAP = "twap"             # Time-weighted average price
    AGGRESSIVE = "aggressive"  # Take liquidity immediately


@dataclass
class ExecutionPlan:
    """
    A plan for executing a trade.

    The smart order router creates this plan based on market conditions.
    """
    strategy: ExecutionStrategy
    orders: list[dict]  # List of order specifications
    expected_fill_price: float
    expected_slippage: float
    estimated_time_seconds: int
    reason: str


class SmartOrderRouter:
    """
    Routes orders optimally based on market conditions.

    The router analyzes:
    - Order book depth
    - Spread
    - Trade size relative to liquidity
    - Urgency of the trade

    And chooses the best execution strategy.

    Example usage:
        router = SmartOrderRouter(client)
        plan = router.plan_execution(
            token_id="btc_yes",
            side=Side.BUY,
            size=100,
            max_slippage=0.02
        )

        if plan.expected_slippage < 0.01:
            # Execute the plan
            for order_spec in plan.orders:
                client.place_order(**order_spec)
    """

    def __init__(self, client):
        """
        Initialize the router.

        Args:
            client: PolymarketClient for market data
        """
        self.client = client

    def plan_execution(
        self,
        token_id: str,
        side: Side,
        size: float,
        max_slippage: float = 0.02,
        urgent: bool = False,
    ) -> ExecutionPlan:
        """
        Create an execution plan for a trade.

        Args:
            token_id: The token to trade
            side: BUY or SELL
            size: Number of shares
            max_slippage: Maximum acceptable slippage
            urgent: Whether this is a time-sensitive trade

        Returns:
            ExecutionPlan with recommended strategy
        """
        # Get market data
        spread_info = self.client.get_spread(token_id)
        book = self.client.get_order_book(token_id)

        best_bid = spread_info.get("best_bid", 0)
        best_ask = spread_info.get("best_ask", 1)
        spread = spread_info.get("spread", 0.02)
        depth = spread_info.get("ask_depth" if side == Side.BUY else "bid_depth", 0)

        # Determine strategy based on conditions
        if urgent:
            # Use aggressive strategy for urgent trades
            return self._plan_aggressive(token_id, side, size, best_bid, best_ask)

        if size <= depth * 0.1:
            # Small order relative to depth - use limit order
            return self._plan_limit(token_id, side, size, best_bid, best_ask, spread)

        if size <= depth * 0.5:
            # Medium order - use IOC with slight aggression
            return self._plan_ioc(token_id, side, size, best_bid, best_ask)

        # Large order - use TWAP to minimize impact
        return self._plan_twap(token_id, side, size, best_bid, best_ask)

    def _plan_limit(
        self,
        token_id: str,
        side: Side,
        size: float,
        best_bid: float,
        best_ask: float,
        spread: float,
    ) -> ExecutionPlan:
        """Plan a limit order execution."""
        # For buys, bid slightly below the ask
        # For sells, ask slightly above the bid
        if side == Side.BUY:
            price = best_bid + spread * 0.3  # Join bid, slight improvement
        else:
            price = best_ask - spread * 0.3

        return ExecutionPlan(
            strategy=ExecutionStrategy.LIMIT,
            orders=[{
                "token_id": token_id,
                "side": side.value,
                "price": price,
                "size": size,
                "order_type": OrderType.GTC.value,
            }],
            expected_fill_price=price,
            expected_slippage=abs(price - (best_ask if side == Side.BUY else best_bid)),
            estimated_time_seconds=300,  # May take up to 5 min
            reason="Small order - using passive limit order",
        )

    def _plan_ioc(
        self,
        token_id: str,
        side: Side,
        size: float,
        best_bid: float,
        best_ask: float,
    ) -> ExecutionPlan:
        """Plan an IOC order execution."""
        if side == Side.BUY:
            price = best_ask * 1.005  # Slight premium for fill
        else:
            price = best_bid * 0.995

        return ExecutionPlan(
            strategy=ExecutionStrategy.IOC,
            orders=[{
                "token_id": token_id,
                "side": side.value,
                "price": price,
                "size": size,
                "order_type": OrderType.IOC.value,
            }],
            expected_fill_price=price,
            expected_slippage=0.005,
            estimated_time_seconds=1,
            reason="Medium order - using IOC for immediate execution",
        )

    def _plan_aggressive(
        self,
        token_id: str,
        side: Side,
        size: float,
        best_bid: float,
        best_ask: float,
    ) -> ExecutionPlan:
        """Plan an aggressive market-taking execution."""
        if side == Side.BUY:
            price = best_ask * 1.01  # 1% premium to ensure fill
        else:
            price = best_bid * 0.99

        return ExecutionPlan(
            strategy=ExecutionStrategy.AGGRESSIVE,
            orders=[{
                "token_id": token_id,
                "side": side.value,
                "price": price,
                "size": size,
                "order_type": OrderType.IOC.value,
            }],
            expected_fill_price=price,
            expected_slippage=0.01,
            estimated_time_seconds=1,
            reason="Urgent - aggressive execution",
        )

    def _plan_twap(
        self,
        token_id: str,
        side: Side,
        size: float,
        best_bid: float,
        best_ask: float,
        num_slices: int = 5,
    ) -> ExecutionPlan:
        """Plan a TWAP (time-weighted) execution."""
        slice_size = size / num_slices

        orders = []
        for i in range(num_slices):
            # Vary price slightly for each slice
            if side == Side.BUY:
                price = best_ask * (1 + 0.002 * i)
            else:
                price = best_bid * (1 - 0.002 * i)

            orders.append({
                "token_id": token_id,
                "side": side.value,
                "price": price,
                "size": slice_size,
                "order_type": OrderType.GTC.value,
                "delay_seconds": i * 60,  # 1 minute between slices
            })

        avg_price = sum(o["price"] for o in orders) / len(orders)

        return ExecutionPlan(
            strategy=ExecutionStrategy.TWAP,
            orders=orders,
            expected_fill_price=avg_price,
            expected_slippage=0.008,
            estimated_time_seconds=num_slices * 60,
            reason=f"Large order - TWAP over {num_slices} slices",
        )
