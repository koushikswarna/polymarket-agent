"""
Portfolio and position management.
"""

from datetime import datetime
from typing import Optional

from config import settings
from data.models import Position, Market, Trade, Side
from data.db import Database
from utils.logger import get_logger, TradingLogger

from .client import PolymarketClient

logger = get_logger("polymarket.portfolio")
trade_logger = TradingLogger()


class PortfolioManager:
    """
    Manages positions, P&L tracking, and resolution handling.

    Responsibilities:
    - Track open positions
    - Calculate unrealized P&L
    - Handle market resolution
    - Mark positions to market
    """

    def __init__(self, client: PolymarketClient, db: Database):
        self.client = client
        self.db = db

    def open_position(
        self,
        market: Market,
        token_id: str,
        outcome: str,
        size: float,
        entry_price: float,
    ) -> Position:
        """
        Open or add to a position.
        """
        existing = self.db.get_position(market.id, token_id)

        if existing and existing.size > 0:
            # Add to existing position (average up/down)
            new_cost = existing.cost_basis + (size * entry_price)
            new_size = existing.size + size
            new_avg = new_cost / new_size if new_size > 0 else 0

            existing.size = new_size
            existing.avg_entry_price = new_avg
            existing.cost_basis = new_cost
            existing.updated_at = datetime.utcnow()

            self.db.save_position(existing)

            logger.info(
                f"Added to position {outcome} on '{market.question[:30]}...': "
                f"+{size} shares @ ${entry_price:.3f}"
            )
            return existing

        # New position
        position = Position(
            market_id=market.id,
            token_id=token_id,
            market_question=market.question,
            outcome=outcome,
            size=size,
            avg_entry_price=entry_price,
            cost_basis=size * entry_price,
            current_price=entry_price,
            market_value=size * entry_price,
        )

        self.db.save_position(position)

        trade_logger.position_opened(
            market=market.question,
            outcome=outcome,
            size=size,
            price=entry_price,
        )

        return position

    def close_position(
        self,
        market_id: str,
        token_id: str,
        exit_price: float,
    ) -> Optional[Position]:
        """
        Close a position and record P&L.
        """
        position = self.db.get_position(market_id, token_id)
        if not position:
            return None

        # Calculate realized P&L
        exit_value = position.size * exit_price
        realized_pnl = exit_value - position.cost_basis

        position.realized_pnl = realized_pnl
        position.size = 0
        position.closed_at = datetime.utcnow()
        position.updated_at = datetime.utcnow()

        self.db.save_position(position)

        pnl_pct = realized_pnl / position.cost_basis if position.cost_basis > 0 else 0

        trade_logger.position_closed(
            market=position.market_question,
            outcome=position.outcome,
            pnl=realized_pnl,
            pnl_pct=pnl_pct,
        )

        return position

    def resolve_position(
        self,
        market_id: str,
        token_id: str,
        is_winner: bool,
    ) -> Optional[Position]:
        """
        Resolve a position when market settles.

        Winner gets $1.00 per share, loser gets $0.
        """
        position = self.db.get_position(market_id, token_id)
        if not position:
            return None

        position.resolved = True
        position.winning = is_winner

        if is_winner:
            # Winner: each share pays out $1.00
            payout = position.size * 1.0
        else:
            # Loser: shares worth $0
            payout = 0.0

        position.realized_pnl = payout - position.cost_basis
        position.closed_at = datetime.utcnow()
        position.updated_at = datetime.utcnow()

        self.db.save_position(position)

        pnl_pct = position.realized_pnl / position.cost_basis if position.cost_basis > 0 else 0

        trade_logger.position_closed(
            market=position.market_question,
            outcome=position.outcome,
            pnl=position.realized_pnl,
            pnl_pct=pnl_pct,
        )

        return position

    def mark_to_market(self, position: Position, current_price: float) -> Position:
        """
        Update position with current market price.
        """
        position.update_mark(current_price)
        self.db.save_position(position)
        return position

    def refresh_all_positions(self):
        """
        Refresh all open positions with current market prices.
        """
        open_positions = self.db.get_open_positions()

        for position in open_positions:
            try:
                price = self.client.get_midpoint_price(position.token_id)
                if price is not None:
                    self.mark_to_market(position, price)
            except Exception as e:
                logger.warning(f"Failed to refresh position {position.market_id}: {e}")

        logger.info(f"Refreshed {len(open_positions)} positions")

    def check_resolutions(self, markets_to_check: list[str] = None):
        """
        Check for resolved markets and settle positions.
        """
        open_positions = self.db.get_open_positions()

        for position in open_positions:
            if markets_to_check and position.market_id not in markets_to_check:
                continue

            try:
                market_data = self.client.get_market(position.market_id)
                if market_data and market_data.get("resolved"):
                    # Determine winner
                    # In binary markets, check which outcome won
                    winning_outcome = market_data.get("winner")

                    if winning_outcome:
                        is_winner = (
                            position.outcome.lower() == winning_outcome.lower()
                        )
                        self.resolve_position(
                            position.market_id,
                            position.token_id,
                            is_winner,
                        )
                        logger.info(
                            f"Resolved position: {position.outcome} on "
                            f"'{position.market_question[:30]}...' -> "
                            f"{'WIN' if is_winner else 'LOSS'}"
                        )

            except Exception as e:
                logger.warning(
                    f"Failed to check resolution for {position.market_id}: {e}"
                )

    def get_open_positions(self) -> list[Position]:
        """Get all open positions."""
        return self.db.get_open_positions()

    def get_position_summary(self) -> dict:
        """
        Get portfolio summary.
        """
        open_positions = self.db.get_open_positions()
        all_positions = self.db.get_all_positions()

        total_cost = sum(p.cost_basis for p in open_positions)
        total_value = sum(p.market_value for p in open_positions)
        total_unrealized = sum(p.unrealized_pnl for p in open_positions)
        total_realized = sum(p.realized_pnl for p in all_positions if p.resolved)

        return {
            "open_positions": len(open_positions),
            "total_cost_basis": total_cost,
            "total_market_value": total_value,
            "unrealized_pnl": total_unrealized,
            "unrealized_pnl_pct": total_unrealized / total_cost if total_cost > 0 else 0,
            "realized_pnl": total_realized,
            "total_pnl": total_realized + total_unrealized,
        }

    def get_balance_summary(self) -> dict:
        """
        Get account balance summary.
        """
        usdc_balance = self.client.get_balance()
        position_summary = self.get_position_summary()

        return {
            "usdc_balance": usdc_balance,
            "position_value": position_summary["total_market_value"],
            "total_value": usdc_balance + position_summary["total_market_value"],
            "unrealized_pnl": position_summary["unrealized_pnl"],
            "realized_pnl": position_summary["realized_pnl"],
        }

    def get_position_by_market(self, market_id: str) -> list[Position]:
        """Get all positions for a market."""
        all_positions = self.db.get_all_positions()
        return [p for p in all_positions if p.market_id == market_id]

    def has_position(self, market_id: str) -> bool:
        """Check if we have any position in a market."""
        positions = self.get_position_by_market(market_id)
        return any(p.size > 0 for p in positions)

    def export_positions_table(self) -> list[dict]:
        """
        Export positions in a table-friendly format.
        """
        positions = self.db.get_open_positions()

        return [
            {
                "Market": p.market_question[:40] + "...",
                "Outcome": p.outcome,
                "Size": f"{p.size:.2f}",
                "Entry": f"${p.avg_entry_price:.3f}",
                "Current": f"${p.current_price:.3f}",
                "P&L": f"${p.unrealized_pnl:+.2f}",
                "P&L %": f"{p.unrealized_pnl_pct:+.1%}",
            }
            for p in positions
        ]
