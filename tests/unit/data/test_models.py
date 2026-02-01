"""
Unit tests for Pydantic data models.
"""

import pytest
from datetime import datetime, timedelta
from pydantic import ValidationError

from data.models import (
    Market, Token, Order, Trade, Position,
    Side, OrderType, OrderStatus,
    ProbabilityEstimate, ArbitrageOpportunity, RiskCheckResult,
    DailyStats, LLMBudget,
)


class TestToken:
    """Tests for Token model."""

    def test_token_creation(self):
        token = Token(token_id="abc123", outcome="Yes", price=0.65)
        assert token.token_id == "abc123"
        assert token.outcome == "Yes"
        assert token.price == 0.65
        assert token.winner is None

    def test_token_price_validation(self):
        # Valid prices
        Token(token_id="t1", outcome="Yes", price=0.0)
        Token(token_id="t2", outcome="Yes", price=1.0)
        Token(token_id="t3", outcome="Yes", price=0.5)

        # Invalid prices should raise error
        with pytest.raises(ValidationError):
            Token(token_id="t4", outcome="Yes", price=-0.1)

        with pytest.raises(ValidationError):
            Token(token_id="t5", outcome="Yes", price=1.1)


class TestMarket:
    """Tests for Market model."""

    def test_market_creation(self, sample_market):
        assert sample_market.id == "condition_123"
        assert "Fed" in sample_market.question
        assert len(sample_market.tokens) == 2

    def test_yes_no_prices(self, sample_market):
        assert sample_market.yes_price == 0.65
        assert sample_market.no_price == 0.35

    def test_hours_to_resolution(self, sample_market):
        hours = sample_market.hours_to_resolution
        assert hours is not None
        assert 336 - 1 <= hours <= 336 + 1  # ~14 days in hours

    def test_days_to_resolution(self, sample_market):
        days = sample_market.days_to_resolution
        assert days is not None
        assert 13.9 <= days <= 14.1

    def test_market_without_end_date(self):
        market = Market(
            id="no_date",
            question="Test?",
            tokens=[],
        )
        assert market.hours_to_resolution is None
        assert market.days_to_resolution is None


class TestOrder:
    """Tests for Order model."""

    def test_order_creation(self, sample_order):
        assert sample_order.id == "order_test_1"
        assert sample_order.side == Side.BUY
        assert sample_order.order_type == OrderType.GTC
        assert sample_order.status == OrderStatus.PENDING

    def test_remaining_size(self):
        order = Order(
            id="o1",
            market_id="m1",
            token_id="t1",
            side=Side.BUY,
            price=0.5,
            size=10.0,
            filled_size=3.0,
        )
        assert order.remaining_size == 7.0

    def test_is_complete(self):
        # Pending order is not complete
        order = Order(
            id="o1", market_id="m1", token_id="t1",
            side=Side.BUY, price=0.5, size=10.0,
            status=OrderStatus.PENDING,
        )
        assert not order.is_complete

        # Filled order is complete
        order.status = OrderStatus.FILLED
        assert order.is_complete

        # Cancelled order is complete
        order.status = OrderStatus.CANCELLED
        assert order.is_complete


class TestPosition:
    """Tests for Position model."""

    def test_position_creation(self):
        position = Position(
            market_id="m1",
            token_id="t1",
            market_question="Test?",
            outcome="Yes",
            size=10.0,
            avg_entry_price=0.45,
            cost_basis=4.50,
        )
        assert position.size == 10.0
        assert position.cost_basis == 4.50

    def test_update_mark(self):
        position = Position(
            market_id="m1",
            token_id="t1",
            size=10.0,
            avg_entry_price=0.45,
            cost_basis=4.50,
        )

        position.update_mark(0.55)

        assert position.current_price == 0.55
        assert position.market_value == 5.50
        assert abs(position.unrealized_pnl - 1.0) < 0.01
        assert abs(position.unrealized_pnl_pct - 0.222) < 0.01


class TestProbabilityEstimate:
    """Tests for ProbabilityEstimate model."""

    def test_estimate_creation(self):
        estimate = ProbabilityEstimate(
            market_id="m1",
            probability=0.65,
            confidence=0.8,
            model="claude",
            reasoning="Test reasoning",
            market_price=0.55,
            edge=0.10,
        )
        assert estimate.probability == 0.65
        assert estimate.edge == 0.10

    def test_has_positive_edge(self):
        # Positive edge
        estimate = ProbabilityEstimate(
            market_id="m1",
            probability=0.65,
            confidence=0.8,
            edge=0.10,
        )
        assert estimate.has_positive_edge

        # Negative edge (still has edge in opposite direction)
        estimate.edge = -0.10
        assert estimate.has_positive_edge

        # No edge
        estimate.edge = 0.0
        assert not estimate.has_positive_edge


class TestLLMBudget:
    """Tests for LLMBudget model."""

    def test_budget_defaults(self):
        budget = LLMBudget()
        assert budget.anthropic_budget == 4.50
        assert budget.openai_budget == 5.00
        assert budget.anthropic_spent == 0.0
        assert budget.openai_spent == 0.0

    def test_remaining_calculation(self):
        budget = LLMBudget(
            anthropic_spent=2.00,
            openai_spent=1.50,
        )
        assert budget.anthropic_remaining == 2.50
        assert budget.openai_remaining == 3.50
        assert budget.total_remaining == 6.00

    def test_exhausted_flags(self):
        budget = LLMBudget(
            anthropic_spent=4.50,
            openai_spent=5.00,
        )
        assert budget.anthropic_exhausted
        assert budget.openai_exhausted
        assert budget.all_exhausted

        budget.anthropic_spent = 4.00
        assert not budget.anthropic_exhausted
        assert not budget.all_exhausted


class TestRiskCheckResult:
    """Tests for RiskCheckResult model."""

    def test_passed_result(self):
        result = RiskCheckResult(
            passed=True,
            checks={"daily_loss": True, "exposure": True},
            reasons=[],
            original_size=3.0,
            approved_size=3.0,
        )
        assert result.passed
        assert not result.size_reduced

    def test_failed_result(self):
        result = RiskCheckResult(
            passed=False,
            checks={"daily_loss": False},
            reasons=["Daily loss limit exceeded"],
            original_size=3.0,
            approved_size=0.0,
        )
        assert not result.passed
        assert result.size_reduced


class TestDailyStats:
    """Tests for DailyStats model."""

    def test_stats_defaults(self):
        stats = DailyStats(date="2024-01-15")
        assert stats.realized_pnl == 0.0
        assert stats.trades_count == 0
        assert stats.wins == 0
        assert stats.losses == 0

    def test_stats_tracking(self):
        stats = DailyStats(
            date="2024-01-15",
            realized_pnl=5.50,
            trades_count=10,
            wins=6,
            losses=4,
            claude_calls=5,
            gpt_calls=20,
        )
        assert stats.trades_count == 10
        assert stats.claude_calls == 5
