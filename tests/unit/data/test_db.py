"""
Unit tests for database operations.
"""

import pytest
from datetime import datetime, date

from data.db import Database
from data.models import (
    Order, Trade, Position, Side, OrderType, OrderStatus, DailyStats,
)


class TestDatabaseInitialization:
    """Tests for database initialization."""

    def test_database_creates_tables(self, temp_db):
        """Verify all tables are created."""
        with temp_db._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = {row[0] for row in cursor.fetchall()}

        expected_tables = {
            "orders", "trades", "positions",
            "daily_stats", "llm_budget", "probability_estimates",
        }
        assert expected_tables.issubset(tables)

    def test_database_creates_indexes(self, temp_db):
        """Verify indexes are created."""
        with temp_db._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
            indexes = {row[0] for row in cursor.fetchall()}

        assert "idx_orders_market" in indexes
        assert "idx_trades_market" in indexes


class TestOrderOperations:
    """Tests for order CRUD operations."""

    def test_save_and_get_order(self, temp_db, sample_order):
        temp_db.save_order(sample_order)
        retrieved = temp_db.get_order(sample_order.id)

        assert retrieved is not None
        assert retrieved.id == sample_order.id
        assert retrieved.price == sample_order.price
        assert retrieved.size == sample_order.size
        assert retrieved.side == sample_order.side

    def test_get_open_orders(self, temp_db):
        # Create open and closed orders
        open_order = Order(
            id="open_1", market_id="m1", token_id="t1",
            side=Side.BUY, price=0.5, size=10.0,
            status=OrderStatus.OPEN,
        )
        closed_order = Order(
            id="closed_1", market_id="m1", token_id="t1",
            side=Side.BUY, price=0.5, size=10.0,
            status=OrderStatus.FILLED,
        )

        temp_db.save_order(open_order)
        temp_db.save_order(closed_order)

        open_orders = temp_db.get_open_orders()
        assert len(open_orders) == 1
        assert open_orders[0].id == "open_1"

    def test_update_order(self, temp_db, sample_order):
        temp_db.save_order(sample_order)

        # Update status
        sample_order.status = OrderStatus.FILLED
        sample_order.filled_size = sample_order.size
        temp_db.save_order(sample_order)

        retrieved = temp_db.get_order(sample_order.id)
        assert retrieved.status == OrderStatus.FILLED
        assert retrieved.filled_size == sample_order.size


class TestTradeOperations:
    """Tests for trade operations."""

    def test_save_and_get_trade(self, temp_db):
        trade = Trade(
            id="trade_1",
            order_id="order_1",
            market_id="m1",
            token_id="t1",
            side=Side.BUY,
            price=0.45,
            size=10.0,
            cost=4.50,
        )

        temp_db.save_trade(trade)
        trades = temp_db.get_trades_by_market("m1")

        assert len(trades) == 1
        assert trades[0].id == "trade_1"
        assert trades[0].cost == 4.50

    def test_get_recent_trades(self, temp_db):
        # Create multiple trades
        for i in range(25):
            trade = Trade(
                id=f"trade_{i}",
                order_id=f"order_{i}",
                market_id="m1",
                token_id="t1",
                side=Side.BUY,
                price=0.45,
                size=1.0,
                cost=0.45,
            )
            temp_db.save_trade(trade)

        recent = temp_db.get_recent_trades(limit=10)
        assert len(recent) == 10


class TestPositionOperations:
    """Tests for position operations."""

    def test_save_and_get_position(self, temp_db):
        position = Position(
            market_id="m1",
            token_id="t1",
            market_question="Test?",
            outcome="Yes",
            size=10.0,
            avg_entry_price=0.45,
            cost_basis=4.50,
        )

        temp_db.save_position(position)
        retrieved = temp_db.get_position("m1", "t1")

        assert retrieved is not None
        assert retrieved.size == 10.0
        assert retrieved.avg_entry_price == 0.45

    def test_get_open_positions(self, temp_db):
        # Open position
        open_pos = Position(
            market_id="m1", token_id="t1",
            size=10.0, avg_entry_price=0.45, cost_basis=4.50,
        )
        # Closed position
        closed_pos = Position(
            market_id="m2", token_id="t2",
            size=0.0, avg_entry_price=0.50, cost_basis=5.00,
            resolved=True,
        )

        temp_db.save_position(open_pos)
        temp_db.save_position(closed_pos)

        open_positions = temp_db.get_open_positions()
        assert len(open_positions) == 1
        assert open_positions[0].market_id == "m1"

    def test_position_update(self, temp_db):
        position = Position(
            market_id="m1",
            token_id="t1",
            size=10.0,
            avg_entry_price=0.45,
            cost_basis=4.50,
        )
        temp_db.save_position(position)

        # Update position
        position.current_price = 0.55
        position.update_mark(0.55)
        temp_db.save_position(position)

        retrieved = temp_db.get_position("m1", "t1")
        assert retrieved.current_price == 0.55
        assert retrieved.unrealized_pnl > 0


class TestDailyStatsOperations:
    """Tests for daily stats operations."""

    def test_get_today_stats_creates_new(self, temp_db):
        stats = temp_db.get_today_stats()

        assert stats is not None
        assert stats.date == date.today().isoformat()
        assert stats.trades_count == 0

    def test_save_and_retrieve_stats(self, temp_db):
        stats = temp_db.get_today_stats()
        stats.trades_count = 5
        stats.wins = 3
        stats.losses = 2
        stats.realized_pnl = 1.50

        temp_db.save_daily_stats(stats)

        retrieved = temp_db.get_today_stats()
        assert retrieved.trades_count == 5
        assert retrieved.wins == 3
        assert retrieved.realized_pnl == 1.50


class TestLLMBudgetOperations:
    """Tests for LLM budget tracking."""

    def test_get_llm_budget_creates_default(self, temp_db):
        budget = temp_db.get_llm_budget()

        assert budget is not None
        assert budget.anthropic_budget == 4.50
        assert budget.openai_budget == 5.00

    def test_record_llm_call(self, temp_db):
        temp_db.record_llm_call("anthropic", 0.005)
        temp_db.record_llm_call("openai", 0.001)

        budget = temp_db.get_llm_budget()
        assert budget.anthropic_spent == 0.005
        assert budget.anthropic_calls == 1
        assert budget.openai_spent == 0.001
        assert budget.openai_calls == 1

    def test_budget_accumulation(self, temp_db):
        for _ in range(10):
            temp_db.record_llm_call("openai", 0.001)

        budget = temp_db.get_llm_budget()
        assert budget.openai_spent == 0.01
        assert budget.openai_calls == 10


class TestAggregateQueries:
    """Tests for aggregate queries."""

    def test_get_total_realized_pnl(self, temp_db):
        # Create resolved positions
        for i, pnl in enumerate([1.00, -0.50, 2.00]):
            pos = Position(
                market_id=f"m{i}",
                token_id=f"t{i}",
                size=0,
                avg_entry_price=0.5,
                cost_basis=5.0,
                resolved=True,
                realized_pnl=pnl,
            )
            temp_db.save_position(pos)

        total = temp_db.get_total_realized_pnl()
        assert total == 2.50

    def test_get_total_exposure(self, temp_db):
        for i in range(3):
            pos = Position(
                market_id=f"m{i}",
                token_id=f"t{i}",
                size=10,
                avg_entry_price=0.5,
                cost_basis=5.0,
            )
            temp_db.save_position(pos)

        exposure = temp_db.get_total_exposure()
        assert exposure == 15.0

    def test_count_open_positions(self, temp_db):
        for i in range(5):
            pos = Position(
                market_id=f"m{i}",
                token_id=f"t{i}",
                size=10 if i < 3 else 0,  # 3 open, 2 closed
                avg_entry_price=0.5,
                cost_basis=5.0,
            )
            temp_db.save_position(pos)

        count = temp_db.count_open_positions()
        assert count == 3
