"""
Unit tests for circuit breakers and guardrails.
"""

import pytest
import json
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from data.models import DailyStats
from risk.guardrails import Guardrails, DailyLossCircuitBreaker


class TestGuardrails:
    """Tests for Guardrails class."""

    @pytest.fixture
    def mock_db(self):
        db = MagicMock()
        db.get_today_stats.return_value = DailyStats(
            date=datetime.now().strftime("%Y-%m-%d"),
            realized_pnl=0.0,
            unrealized_pnl=0.0,
        )
        return db

    @pytest.fixture
    def temp_state_file(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = Path(f.name)
        yield path
        try:
            path.unlink()
        except:
            pass

    @pytest.fixture
    def guardrails(self, mock_db, temp_state_file):
        return Guardrails(db=mock_db, state_file=temp_state_file)

    def test_can_trade_initially(self, guardrails):
        """Test trading is allowed initially."""
        can_trade, reason = guardrails.can_trade()

        assert can_trade
        assert reason == "OK"

    def test_emergency_stop(self, guardrails):
        """Test emergency stop blocks trading."""
        guardrails.activate_emergency_stop("Test emergency")

        can_trade, reason = guardrails.can_trade()

        assert not can_trade
        assert "Emergency" in reason

    def test_deactivate_emergency(self, guardrails):
        """Test emergency stop can be deactivated."""
        guardrails.activate_emergency_stop("Test")
        guardrails.deactivate_emergency_stop()

        can_trade, _ = guardrails.can_trade()
        assert can_trade

    def test_consecutive_loss_tracking(self, guardrails):
        """Test consecutive loss counter."""
        # Record losses
        for _ in range(3):
            guardrails.record_trade_result(is_win=False)

        status = guardrails.get_status()
        assert status["consecutive_losses"] == 3

        # Win resets counter
        guardrails.record_trade_result(is_win=True)

        status = guardrails.get_status()
        assert status["consecutive_losses"] == 0

    def test_cooldown_triggered(self, guardrails):
        """Test cooldown after max consecutive losses."""
        # Trigger cooldown (5 losses)
        for _ in range(5):
            guardrails.record_trade_result(is_win=False)

        can_trade, reason = guardrails.can_trade()

        assert not can_trade
        assert "cooldown" in reason.lower()

    def test_cooldown_expires(self, guardrails):
        """Test cooldown expiration."""
        # Set a short cooldown
        guardrails.cooldown_hours = 0.001  # Very short

        # Trigger cooldown
        for _ in range(5):
            guardrails.record_trade_result(is_win=False)

        # Wait for expiration (or mock time)
        import time
        time.sleep(0.01)

        can_trade, _ = guardrails.can_trade()
        assert can_trade

    def test_reset_cooldown(self, guardrails):
        """Test manual cooldown reset."""
        # Trigger cooldown
        for _ in range(5):
            guardrails.record_trade_result(is_win=False)

        guardrails.reset_cooldown()

        can_trade, _ = guardrails.can_trade()
        assert can_trade

    def test_trade_rate_limiting(self, guardrails):
        """Test hourly trade rate limit."""
        # Record many trades
        for _ in range(25):
            guardrails.record_trade_attempt()

        rate_ok, reason = guardrails.check_trade_rate(max_trades_per_hour=20)

        assert not rate_ok
        assert "Max trades" in reason

    def test_state_persistence(self, mock_db, temp_state_file):
        """Test state persists across instances."""
        # First instance
        g1 = Guardrails(db=mock_db, state_file=temp_state_file)
        g1.record_trade_result(is_win=False)
        g1.record_trade_result(is_win=False)

        # Second instance should load state
        g2 = Guardrails(db=mock_db, state_file=temp_state_file)
        status = g2.get_status()

        assert status["consecutive_losses"] == 2

    def test_get_status(self, guardrails):
        """Test status report generation."""
        status = guardrails.get_status()

        assert "can_trade" in status
        assert "consecutive_losses" in status
        assert "emergency_stop" in status
        assert "trades_this_hour" in status

    def test_check_all(self, guardrails):
        """Test all guardrails checked together."""
        all_passed, failures = guardrails.check_all()

        assert all_passed
        assert len(failures) == 0


class TestDailyLossCircuitBreaker:
    """Tests for DailyLossCircuitBreaker class."""

    @pytest.fixture
    def mock_db(self):
        db = MagicMock()
        db.get_today_stats.return_value = DailyStats(
            date=datetime.now().strftime("%Y-%m-%d"),
            realized_pnl=0.0,
            unrealized_pnl=0.0,
        )
        return db

    @pytest.fixture
    def breaker(self, mock_db):
        return DailyLossCircuitBreaker(db=mock_db, daily_limit=3.0)

    def test_allows_trading_initially(self, breaker):
        """Test trading allowed when no losses."""
        can_trade, reason = breaker.check()

        assert can_trade
        assert "$3.00 remaining" in reason

    def test_triggers_at_limit(self, breaker, mock_db):
        """Test breaker triggers at limit."""
        mock_db.get_today_stats.return_value = DailyStats(
            date=datetime.now().strftime("%Y-%m-%d"),
            realized_pnl=-3.50,
            unrealized_pnl=0.0,
        )

        can_trade, reason = breaker.check()

        assert not can_trade
        assert "limit reached" in reason.lower()

    def test_stays_triggered(self, breaker, mock_db):
        """Test breaker stays triggered once hit."""
        mock_db.get_today_stats.return_value = DailyStats(
            date=datetime.now().strftime("%Y-%m-%d"),
            realized_pnl=-3.50,
            unrealized_pnl=0.0,
        )

        breaker.check()

        # Even if losses recover, stays triggered
        mock_db.get_today_stats.return_value = DailyStats(
            date=datetime.now().strftime("%Y-%m-%d"),
            realized_pnl=-1.00,
            unrealized_pnl=0.0,
        )

        can_trade, _ = breaker.check()
        assert not can_trade

    def test_reset(self, breaker, mock_db):
        """Test breaker can be reset."""
        mock_db.get_today_stats.return_value = DailyStats(
            date=datetime.now().strftime("%Y-%m-%d"),
            realized_pnl=-3.50,
            unrealized_pnl=0.0,
        )

        breaker.check()
        breaker.reset()

        mock_db.get_today_stats.return_value = DailyStats(
            date=datetime.now().strftime("%Y-%m-%d"),
            realized_pnl=0.0,
            unrealized_pnl=0.0,
        )

        can_trade, _ = breaker.check()
        assert can_trade

    def test_get_remaining(self, breaker, mock_db):
        """Test remaining calculation."""
        mock_db.get_today_stats.return_value = DailyStats(
            date=datetime.now().strftime("%Y-%m-%d"),
            realized_pnl=-1.50,
            unrealized_pnl=0.0,
        )

        remaining = breaker.get_remaining()

        assert remaining == 1.50
