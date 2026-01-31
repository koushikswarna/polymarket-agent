"""
Order management for trade execution and tracking.
"""

import uuid
from datetime import datetime
from typing import Optional

from config import settings
from data.models import Order, OrderStatus, OrderType, Side, Trade
from data.db import Database
from utils.logger import get_logger, TradingLogger

from .client import PolymarketClient

logger = get_logger("polymarket.orders")
trade_logger = TradingLogger()


class OrderManager:
    """
    Manages order lifecycle from creation to completion.

    Responsibilities:
    - Create and submit orders
    - Track order status
    - Record fills as trades
    - Handle cancellations
    """

    def __init__(self, client: PolymarketClient, db: Database):
        self.client = client
        self.db = db

    def create_order(
        self,
        market_id: str,
        token_id: str,
        side: Side,
        price: float,
        size: float,
        order_type: OrderType = OrderType.GTC,
        reason: str = "",
    ) -> Order:
        """
        Create an order object (not yet submitted).
        """
        order = Order(
            id=f"ord_{uuid.uuid4().hex[:12]}",
            market_id=market_id,
            token_id=token_id,
            side=side,
            order_type=order_type,
            price=price,
            size=size,
            status=OrderStatus.PENDING,
            reason=reason,
        )
        return order

    def submit_order(self, order: Order) -> Optional[Order]:
        """
        Submit an order to the exchange.

        Returns updated order with exchange ID, or None if failed.
        """
        try:
            # Submit to CLOB
            result = self.client.place_order(
                token_id=order.token_id,
                side=order.side,
                price=order.price,
                size=order.size,
                order_type=order.order_type,
            )

            if result:
                # Update order with exchange info
                order.id = result.id or order.id
                order.status = result.status
                order.filled_size = result.filled_size
                order.updated_at = datetime.utcnow()

                # Save to database
                self.db.save_order(order)

                trade_logger.trade_placed(
                    side=order.side.value,
                    market=order.market_id[:50],
                    price=order.price,
                    size=order.size,
                    reason=order.reason,
                )

                # If immediately filled, record as trade
                if order.status == OrderStatus.FILLED:
                    self._record_fill(order)

                return order
            else:
                order.status = OrderStatus.FAILED
                self.db.save_order(order)
                logger.error(f"Order submission failed for {order.id}")
                return None

        except Exception as e:
            logger.error(f"Order submission error: {e}")
            order.status = OrderStatus.FAILED
            self.db.save_order(order)
            return None

    def _record_fill(self, order: Order):
        """Record a filled order as a trade."""
        trade = Trade(
            id=f"trd_{uuid.uuid4().hex[:12]}",
            order_id=order.id,
            market_id=order.market_id,
            token_id=order.token_id,
            side=order.side,
            price=order.price,
            size=order.filled_size,
            cost=order.price * order.filled_size,
            fees=0.0,  # Polymarket is fee-free on maker
            reason=order.reason,
        )

        self.db.save_trade(trade)

        trade_logger.trade_filled(
            side=order.side.value,
            market=order.market_id[:30],
            price=order.price,
            size=order.filled_size,
            cost=trade.cost,
        )

    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an open order.

        Returns True if successfully cancelled.
        """
        success = self.client.cancel_order(order_id)

        if success:
            order = self.db.get_order(order_id)
            if order:
                order.status = OrderStatus.CANCELLED
                order.updated_at = datetime.utcnow()
                self.db.save_order(order)

            logger.info(f"Order {order_id} cancelled")

        return success

    def update_order_status(self, order_id: str) -> Optional[Order]:
        """
        Fetch and update order status from exchange.
        """
        order = self.db.get_order(order_id)
        if not order:
            return None

        new_status = self.client.get_order_status(order_id)
        if new_status and new_status != order.status:
            old_status = order.status
            order.status = new_status
            order.updated_at = datetime.utcnow()
            self.db.save_order(order)

            logger.info(f"Order {order_id} status: {old_status} -> {new_status}")

            # Record fill if newly filled
            if new_status == OrderStatus.FILLED and old_status != OrderStatus.FILLED:
                order.filled_size = order.size
                self._record_fill(order)

        return order

    def get_open_orders(self) -> list[Order]:
        """Get all open orders."""
        return self.db.get_open_orders()

    def sync_orders(self):
        """
        Sync all open orders with exchange status.
        """
        open_orders = self.get_open_orders()

        for order in open_orders:
            try:
                self.update_order_status(order.id)
            except Exception as e:
                logger.warning(f"Failed to sync order {order.id}: {e}")

        logger.info(f"Synced {len(open_orders)} open orders")

    def place_market_buy(
        self,
        market_id: str,
        token_id: str,
        size: float,
        max_price: float = 0.99,
        reason: str = "",
    ) -> Optional[Order]:
        """
        Place a market-like buy order using IOC.

        Uses best ask price with a buffer.
        """
        # Get current spread
        spread = self.client.get_spread(token_id)
        best_ask = spread.get("best_ask", max_price)

        # Use ask price with small buffer
        price = min(best_ask * 1.01, max_price)

        order = self.create_order(
            market_id=market_id,
            token_id=token_id,
            side=Side.BUY,
            price=price,
            size=size,
            order_type=OrderType.IOC,  # Immediate or Cancel
            reason=reason,
        )

        return self.submit_order(order)

    def place_limit_buy(
        self,
        market_id: str,
        token_id: str,
        price: float,
        size: float,
        reason: str = "",
    ) -> Optional[Order]:
        """
        Place a limit buy order (GTC).
        """
        order = self.create_order(
            market_id=market_id,
            token_id=token_id,
            side=Side.BUY,
            price=price,
            size=size,
            order_type=OrderType.GTC,
            reason=reason,
        )

        return self.submit_order(order)

    def place_arb_orders(
        self,
        orders: list[dict],
    ) -> list[Order]:
        """
        Place multiple FOK orders for arbitrage.

        All orders should execute atomically (all or nothing).
        """
        submitted = []

        for order_spec in orders:
            order = self.create_order(
                market_id=order_spec["market_id"],
                token_id=order_spec["token_id"],
                side=Side(order_spec["side"]),
                price=order_spec["price"],
                size=order_spec["size"],
                order_type=OrderType.FOK,
                reason="Arbitrage",
            )

            result = self.submit_order(order)
            if result:
                submitted.append(result)
            else:
                # One leg failed - try to cancel others
                logger.warning("Arbitrage order failed, attempting to cancel other legs")
                for prev_order in submitted:
                    if prev_order.status == OrderStatus.OPEN:
                        self.cancel_order(prev_order.id)
                return []

        return submitted

    def calculate_entry_summary(self) -> dict:
        """
        Get summary of today's trading activity.
        """
        trades = self.db.get_recent_trades(limit=100)

        today = datetime.utcnow().date()
        today_trades = [
            t for t in trades
            if t.executed_at.date() == today
        ]

        total_bought = sum(
            t.cost for t in today_trades if t.side == Side.BUY
        )
        total_sold = sum(
            t.cost for t in today_trades if t.side == Side.SELL
        )

        return {
            "trades_today": len(today_trades),
            "total_bought": total_bought,
            "total_sold": total_sold,
            "net_flow": total_bought - total_sold,
        }
