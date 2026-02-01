"""
Unit tests for risk management.
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

from data.models import Market, Token, Position, DailyStats
from risk.risk_manager import RiskManager, RiskLimits


class TestRiskManager:
    """Tests for RiskManager class."""

    @pytest.fixture
    def mock_db(self):
        db = MagicMock()
        db.get_today_stats.return_value = DailyStats(
            date=datetime.now().strftime("%Y-%m-%d"),
            realized_pnl=0.0,
            unrealized_pnl=0.0,
        )
        db.get_total_exposure.return_value = 2.0
        db.count_open_positions.return_value = 2
        return db

    @pytest.fixture
    def limits(self):
        return RiskLimits(
            max_position_size=3.0,
            max_total_exposure=8.0,
            max_open_positions=8,
            daily_loss_limit=3.0,
            min_edge=0.05,
            min_confidence=0.3,
            min_liquidity=500.0,
            min_hours_to_resolution=6,
        )

    @pytest.fixture
    def risk_manager(self, mock_db, limits):
        return RiskManager(db=mock_db, limits=limits)

    @pytest.fixture
    def valid_market(self):
        return Market(
            id="m1",
            question="Test market?",
            tokens=[
                Token(token_id="yes", outcome="Yes", price=0.50),
            ],
            liquidity=5000.0,
            end_date=datetime.now().replace(hour=datetime.now().hour + 24),
        )

    def test_all_checks_pass(self, risk_manager, valid_market):
        """Test that valid trade passes all checks."""
        result = risk_manager.check_trade(
            market=valid_market,
            proposed_size=2.0,
            edge=0.10,
            confidence=0.7,
        )

        assert result.passed
        assert result.approved_size == 2.0
        assert not result.size_reduced

    def test_daily_loss_limit(self, risk_manager, valid_market, mock_db):
        """Test daily loss limit check."""
        mock_db.get_today_stats.return_value = DailyStats(
            date=datetime.now().strftime("%Y-%m-%d"),
            realized_pnl=-3.50,  # Exceeded limit
            unrealized_pnl=0.0,
        )

        result = risk_manager.check_trade(
            market=valid_market,
            proposed_size=2.0,
            edge=0.10,
            confidence=0.7,
        )

        assert not result.passed
        assert "daily_loss" in result.checks
        assert not result.checks["daily_loss"]

    def test_total_exposure_limit(self, risk_manager, valid_market, mock_db):
        """Test total exposure capping."""
        mock_db.get_total_exposure.return_value = 7.0  # Already near limit

        result = risk_manager.check_trade(
            market=valid_market,
            proposed_size=3.0,  # Would exceed 8.0 limit
            edge=0.10,
            confidence=0.7,
        )

        # Should reduce size, not reject
        assert result.passed
        assert result.size_reduced
        assert result.approved_size <= 1.0

    def test_position_count_limit(self, risk_manager, valid_market, mock_db):
        """Test max positions check."""
        mock_db.count_open_positions.return_value = 8  # At limit

        result = risk_manager.check_trade(
            market=valid_market,
            proposed_size=2.0,
            edge=0.10,
            confidence=0.7,
        )

        assert not result.passed
        assert "position_count" in result.checks
        assert not result.checks["position_count"]

    def test_min_liquidity(self, risk_manager):
        """Test minimum liquidity check."""
        low_liq_market = Market(
            id="m1",
            question="Test?",
            tokens=[Token(token_id="yes", outcome="Yes", price=0.50)],
            liquidity=100.0,  # Below 500 minimum
        )

        result = risk_manager.check_trade(
            market=low_liq_market,
            proposed_size=2.0,
            edge=0.10,
            confidence=0.7,
        )

        assert not result.passed
        assert not result.checks["liquidity"]

    def test_min_edge_threshold(self, risk_manager, valid_market):
        """Test minimum edge check."""
        result = risk_manager.check_trade(
            market=valid_market,
            proposed_size=2.0,
            edge=0.02,  # Below 5% threshold
            confidence=0.7,
        )

        assert not result.passed
        assert not result.checks["min_edge"]

    def test_min_confidence(self, risk_manager, valid_market):
        """Test minimum confidence check."""
        result = risk_manager.check_trade(
            market=valid_market,
            proposed_size=2.0,
            edge=0.10,
            confidence=0.2,  # Below 30% threshold
        )

        assert not result.passed
        assert not result.checks["min_confidence"]

    def test_time_to_resolution(self, risk_manager):
        """Test time to resolution check."""
        expiring_soon = Market(
            id="m1",
            question="Test?",
            tokens=[Token(token_id="yes", outcome="Yes", price=0.50)],
            liquidity=5000.0,
            end_date=datetime.now().replace(hour=datetime.now().hour + 2),  # 2 hours
        )

        result = risk_manager.check_trade(
            market=expiring_soon,
            proposed_size=2.0,
            edge=0.10,
            confidence=0.7,
        )

        assert not result.passed
        assert not result.checks["time_to_resolution"]

    def test_max_position_size_cap(self, risk_manager, valid_market):
        """Test single position size cap."""
        result = risk_manager.check_trade(
            market=valid_market,
            proposed_size=5.0,  # Above 3.0 limit
            edge=0.10,
            confidence=0.7,
        )

        assert result.passed
        assert result.size_reduced
        assert result.approved_size == 3.0

    def test_size_vs_liquidity_cap(self, risk_manager):
        """Test position vs liquidity cap."""
        market = Market(
            id="m1",
            question="Test?",
            tokens=[Token(token_id="yes", outcome="Yes", price=0.50)],
            liquidity=50.0,  # 2% of this = $1
            end_date=datetime.now().replace(hour=datetime.now().hour + 24),
        )

        # Need to update limits to allow low liquidity
        risk_manager.limits.min_liquidity = 10.0

        result = risk_manager.check_trade(
            market=market,
            proposed_size=3.0,  # More than 2% of liquidity
            edge=0.10,
            confidence=0.7,
        )

        if result.passed:
            assert result.approved_size <= 1.0

    def test_get_available_capital(self, risk_manager, mock_db):
        """Test available capital calculation."""
        mock_db.get_total_exposure.return_value = 5.0

        available = risk_manager.get_available_capital()

        assert available == 3.0  # 8.0 max - 5.0 current

    def test_get_risk_summary(self, risk_manager, mock_db):
        """Test risk summary generation."""
        summary = risk_manager.get_risk_summary()

        assert "daily_pnl" in summary
        assert "current_exposure" in summary
        assert "open_positions" in summary
        assert "available_capital" in summary
        assert "can_trade" in summary


class TestRiskLimits:
    """Tests for RiskLimits configuration."""

    def test_default_limits(self):
        limits = RiskLimits()

        assert limits.max_position_size == 3.0
        assert limits.daily_loss_limit == 3.0
        assert limits.min_edge == 0.05

    def test_custom_limits(self):
        limits = RiskLimits(
            max_position_size=5.0,
            daily_loss_limit=10.0,
            min_edge=0.03,
        )

        assert limits.max_position_size == 5.0
        assert limits.daily_loss_limit == 10.0
        assert limits.min_edge == 0.03
