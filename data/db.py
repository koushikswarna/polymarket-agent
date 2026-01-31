"""
SQLite database for persistent storage of trades, positions, and metrics.
"""

import json
import sqlite3
from datetime import datetime, date
from pathlib import Path
from typing import Optional
from contextlib import contextmanager

from .models import (
    Trade,
    Position,
    Order,
    OrderStatus,
    Side,
    OrderType,
    DailyStats,
    LLMBudget,
)


class Database:
    """SQLite database wrapper for trading data persistence."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_schema()

    @contextmanager
    def _get_conn(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self):
        """Initialize database schema."""
        with self._get_conn() as conn:
            cursor = conn.cursor()

            # Orders table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    id TEXT PRIMARY KEY,
                    market_id TEXT NOT NULL,
                    token_id TEXT NOT NULL,
                    side TEXT NOT NULL,
                    order_type TEXT NOT NULL,
                    price REAL NOT NULL,
                    size REAL NOT NULL,
                    filled_size REAL DEFAULT 0,
                    status TEXT NOT NULL,
                    reason TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # Trades table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id TEXT PRIMARY KEY,
                    order_id TEXT NOT NULL,
                    market_id TEXT NOT NULL,
                    token_id TEXT NOT NULL,
                    side TEXT NOT NULL,
                    price REAL NOT NULL,
                    size REAL NOT NULL,
                    cost REAL NOT NULL,
                    fees REAL DEFAULT 0,
                    reason TEXT,
                    executed_at TEXT NOT NULL,
                    FOREIGN KEY (order_id) REFERENCES orders(id)
                )
            """)

            # Positions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    market_id TEXT NOT NULL,
                    token_id TEXT NOT NULL,
                    market_question TEXT,
                    outcome TEXT,
                    size REAL NOT NULL,
                    avg_entry_price REAL NOT NULL,
                    cost_basis REAL NOT NULL,
                    current_price REAL,
                    market_value REAL,
                    unrealized_pnl REAL,
                    unrealized_pnl_pct REAL,
                    resolved INTEGER DEFAULT 0,
                    winning INTEGER,
                    realized_pnl REAL DEFAULT 0,
                    opened_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    closed_at TEXT,
                    UNIQUE(market_id, token_id)
                )
            """)

            # Daily stats table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS daily_stats (
                    date TEXT PRIMARY KEY,
                    realized_pnl REAL DEFAULT 0,
                    unrealized_pnl REAL DEFAULT 0,
                    total_pnl REAL DEFAULT 0,
                    trades_count INTEGER DEFAULT 0,
                    wins INTEGER DEFAULT 0,
                    losses INTEGER DEFAULT 0,
                    claude_calls INTEGER DEFAULT 0,
                    gpt_calls INTEGER DEFAULT 0,
                    claude_cost REAL DEFAULT 0,
                    gpt_cost REAL DEFAULT 0,
                    max_drawdown REAL DEFAULT 0,
                    consecutive_losses INTEGER DEFAULT 0
                )
            """)

            # LLM budget table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS llm_budget (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    anthropic_spent REAL DEFAULT 0,
                    anthropic_budget REAL DEFAULT 4.5,
                    anthropic_calls INTEGER DEFAULT 0,
                    openai_spent REAL DEFAULT 0,
                    openai_budget REAL DEFAULT 5.0,
                    openai_calls INTEGER DEFAULT 0,
                    last_updated TEXT NOT NULL
                )
            """)

            # Probability estimates table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS probability_estimates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    market_id TEXT NOT NULL,
                    probability REAL NOT NULL,
                    confidence REAL NOT NULL,
                    model TEXT NOT NULL,
                    reasoning TEXT,
                    market_price REAL,
                    edge REAL,
                    news_summary TEXT,
                    created_at TEXT NOT NULL
                )
            """)

            # Create indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_market ON orders(market_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_market ON trades(market_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_positions_market ON positions(market_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_estimates_market ON probability_estimates(market_id)")

    # Order operations
    def save_order(self, order: Order) -> str:
        """Save or update an order."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO orders
                (id, market_id, token_id, side, order_type, price, size,
                 filled_size, status, reason, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                order.id,
                order.market_id,
                order.token_id,
                order.side.value,
                order.order_type.value,
                order.price,
                order.size,
                order.filled_size,
                order.status.value,
                order.reason,
                order.created_at.isoformat(),
                order.updated_at.isoformat(),
            ))
            return order.id

    def get_order(self, order_id: str) -> Optional[Order]:
        """Get order by ID."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
            row = cursor.fetchone()
            if row:
                return self._row_to_order(row)
            return None

    def get_open_orders(self) -> list[Order]:
        """Get all open orders."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM orders WHERE status IN (?, ?)",
                (OrderStatus.PENDING.value, OrderStatus.OPEN.value)
            )
            return [self._row_to_order(row) for row in cursor.fetchall()]

    def _row_to_order(self, row) -> Order:
        return Order(
            id=row["id"],
            market_id=row["market_id"],
            token_id=row["token_id"],
            side=Side(row["side"]),
            order_type=OrderType(row["order_type"]),
            price=row["price"],
            size=row["size"],
            filled_size=row["filled_size"],
            status=OrderStatus(row["status"]),
            reason=row["reason"] or "",
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    # Trade operations
    def save_trade(self, trade: Trade):
        """Save a trade."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO trades
                (id, order_id, market_id, token_id, side, price, size, cost, fees, reason, executed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade.id,
                trade.order_id,
                trade.market_id,
                trade.token_id,
                trade.side.value,
                trade.price,
                trade.size,
                trade.cost,
                trade.fees,
                trade.reason,
                trade.executed_at.isoformat(),
            ))

    def get_trades_by_market(self, market_id: str) -> list[Trade]:
        """Get all trades for a market."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM trades WHERE market_id = ? ORDER BY executed_at",
                (market_id,)
            )
            return [self._row_to_trade(row) for row in cursor.fetchall()]

    def get_recent_trades(self, limit: int = 20) -> list[Trade]:
        """Get most recent trades."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM trades ORDER BY executed_at DESC LIMIT ?",
                (limit,)
            )
            return [self._row_to_trade(row) for row in cursor.fetchall()]

    def _row_to_trade(self, row) -> Trade:
        return Trade(
            id=row["id"],
            order_id=row["order_id"],
            market_id=row["market_id"],
            token_id=row["token_id"],
            side=Side(row["side"]),
            price=row["price"],
            size=row["size"],
            cost=row["cost"],
            fees=row["fees"],
            reason=row["reason"] or "",
            executed_at=datetime.fromisoformat(row["executed_at"]),
        )

    # Position operations
    def save_position(self, position: Position):
        """Save or update a position."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO positions
                (market_id, token_id, market_question, outcome, size, avg_entry_price,
                 cost_basis, current_price, market_value, unrealized_pnl, unrealized_pnl_pct,
                 resolved, winning, realized_pnl, opened_at, updated_at, closed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                position.market_id,
                position.token_id,
                position.market_question,
                position.outcome,
                position.size,
                position.avg_entry_price,
                position.cost_basis,
                position.current_price,
                position.market_value,
                position.unrealized_pnl,
                position.unrealized_pnl_pct,
                1 if position.resolved else 0,
                1 if position.winning else (0 if position.winning is False else None),
                position.realized_pnl,
                position.opened_at.isoformat(),
                position.updated_at.isoformat(),
                position.closed_at.isoformat() if position.closed_at else None,
            ))

    def get_position(self, market_id: str, token_id: str) -> Optional[Position]:
        """Get position by market and token."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM positions WHERE market_id = ? AND token_id = ?",
                (market_id, token_id)
            )
            row = cursor.fetchone()
            if row:
                return self._row_to_position(row)
            return None

    def get_open_positions(self) -> list[Position]:
        """Get all open (unresolved) positions."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM positions WHERE resolved = 0 AND size > 0"
            )
            return [self._row_to_position(row) for row in cursor.fetchall()]

    def get_all_positions(self) -> list[Position]:
        """Get all positions including resolved."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM positions ORDER BY opened_at DESC")
            return [self._row_to_position(row) for row in cursor.fetchall()]

    def _row_to_position(self, row) -> Position:
        return Position(
            market_id=row["market_id"],
            token_id=row["token_id"],
            market_question=row["market_question"] or "",
            outcome=row["outcome"] or "",
            size=row["size"],
            avg_entry_price=row["avg_entry_price"],
            cost_basis=row["cost_basis"],
            current_price=row["current_price"] or 0,
            market_value=row["market_value"] or 0,
            unrealized_pnl=row["unrealized_pnl"] or 0,
            unrealized_pnl_pct=row["unrealized_pnl_pct"] or 0,
            resolved=bool(row["resolved"]),
            winning=bool(row["winning"]) if row["winning"] is not None else None,
            realized_pnl=row["realized_pnl"] or 0,
            opened_at=datetime.fromisoformat(row["opened_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            closed_at=datetime.fromisoformat(row["closed_at"]) if row["closed_at"] else None,
        )

    # Daily stats operations
    def get_today_stats(self) -> DailyStats:
        """Get or create today's stats."""
        today = date.today().isoformat()
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM daily_stats WHERE date = ?", (today,))
            row = cursor.fetchone()
            if row:
                return DailyStats(
                    date=row["date"],
                    realized_pnl=row["realized_pnl"],
                    unrealized_pnl=row["unrealized_pnl"],
                    total_pnl=row["total_pnl"],
                    trades_count=row["trades_count"],
                    wins=row["wins"],
                    losses=row["losses"],
                    claude_calls=row["claude_calls"],
                    gpt_calls=row["gpt_calls"],
                    claude_cost=row["claude_cost"],
                    gpt_cost=row["gpt_cost"],
                    max_drawdown=row["max_drawdown"],
                    consecutive_losses=row["consecutive_losses"],
                )
            # Create new entry
            stats = DailyStats(date=today)
            self.save_daily_stats(stats)
            return stats

    def save_daily_stats(self, stats: DailyStats):
        """Save daily stats."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO daily_stats
                (date, realized_pnl, unrealized_pnl, total_pnl, trades_count,
                 wins, losses, claude_calls, gpt_calls, claude_cost, gpt_cost,
                 max_drawdown, consecutive_losses)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                stats.date,
                stats.realized_pnl,
                stats.unrealized_pnl,
                stats.total_pnl,
                stats.trades_count,
                stats.wins,
                stats.losses,
                stats.claude_calls,
                stats.gpt_calls,
                stats.claude_cost,
                stats.gpt_cost,
                stats.max_drawdown,
                stats.consecutive_losses,
            ))

    # LLM budget operations
    def get_llm_budget(self) -> LLMBudget:
        """Get current LLM budget state."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM llm_budget WHERE id = 1")
            row = cursor.fetchone()
            if row:
                return LLMBudget(
                    anthropic_spent=row["anthropic_spent"],
                    anthropic_budget=row["anthropic_budget"],
                    anthropic_calls=row["anthropic_calls"],
                    openai_spent=row["openai_spent"],
                    openai_budget=row["openai_budget"],
                    openai_calls=row["openai_calls"],
                    last_updated=datetime.fromisoformat(row["last_updated"]),
                )
            # Initialize budget
            budget = LLMBudget()
            self.save_llm_budget(budget)
            return budget

    def save_llm_budget(self, budget: LLMBudget):
        """Save LLM budget state."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO llm_budget
                (id, anthropic_spent, anthropic_budget, anthropic_calls,
                 openai_spent, openai_budget, openai_calls, last_updated)
                VALUES (1, ?, ?, ?, ?, ?, ?, ?)
            """, (
                budget.anthropic_spent,
                budget.anthropic_budget,
                budget.anthropic_calls,
                budget.openai_spent,
                budget.openai_budget,
                budget.openai_calls,
                datetime.utcnow().isoformat(),
            ))

    def record_llm_call(self, provider: str, cost: float):
        """Record an LLM API call."""
        budget = self.get_llm_budget()
        if provider == "anthropic":
            budget.anthropic_spent += cost
            budget.anthropic_calls += 1
        elif provider == "openai":
            budget.openai_spent += cost
            budget.openai_calls += 1
        self.save_llm_budget(budget)

        # Also update daily stats
        stats = self.get_today_stats()
        if provider == "anthropic":
            stats.claude_calls += 1
            stats.claude_cost += cost
        elif provider == "openai":
            stats.gpt_calls += 1
            stats.gpt_cost += cost
        self.save_daily_stats(stats)

    # Probability estimate operations
    def save_probability_estimate(
        self,
        market_id: str,
        probability: float,
        confidence: float,
        model: str,
        reasoning: str,
        market_price: float,
        edge: float,
        news_summary: str = "",
    ):
        """Save a probability estimate."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO probability_estimates
                (market_id, probability, confidence, model, reasoning,
                 market_price, edge, news_summary, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                market_id,
                probability,
                confidence,
                model,
                reasoning,
                market_price,
                edge,
                news_summary,
                datetime.utcnow().isoformat(),
            ))

    def get_latest_estimate(self, market_id: str) -> Optional[dict]:
        """Get the most recent probability estimate for a market."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM probability_estimates
                WHERE market_id = ?
                ORDER BY created_at DESC LIMIT 1
            """, (market_id,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None

    # Aggregate queries
    def get_total_realized_pnl(self) -> float:
        """Get total realized P&L across all resolved positions."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT SUM(realized_pnl) FROM positions WHERE resolved = 1")
            result = cursor.fetchone()[0]
            return result or 0.0

    def get_total_unrealized_pnl(self) -> float:
        """Get total unrealized P&L across all open positions."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT SUM(unrealized_pnl) FROM positions WHERE resolved = 0")
            result = cursor.fetchone()[0]
            return result or 0.0

    def get_total_exposure(self) -> float:
        """Get total cost basis of open positions."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT SUM(cost_basis) FROM positions WHERE resolved = 0 AND size > 0")
            result = cursor.fetchone()[0]
            return result or 0.0

    def count_open_positions(self) -> int:
        """Count number of open positions."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM positions WHERE resolved = 0 AND size > 0")
            return cursor.fetchone()[0]
