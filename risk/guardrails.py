"""
Circuit breakers and safety guardrails.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from config import settings
from data.db import Database
from utils.logger import get_logger

logger = get_logger("polymarket.guardrails")


class Guardrails:
    """
    Circuit breakers and safety mechanisms.

    - Consecutive loss tracking and cooldowns
    - Emergency stop functionality
    - Trading hours restrictions (optional)
    - Rate limiting on trades
    """

    def __init__(
        self,
        db: Database,
        state_file: Optional[Path] = None,
    ):
        self.db = db
        self.state_file = state_file or (
            Path(settings.data_dir) / "guardrails_state.json"
        )

        # Configuration
        self.max_consecutive_losses = settings.risk.consecutive_loss_cooldown
        self.cooldown_hours = settings.risk.cooldown_hours

        # Load state
        self._state = self._load_state()

    def _load_state(self) -> dict:
        """Load guardrails state from file."""
        default_state = {
            "consecutive_losses": 0,
            "cooldown_until": None,
            "emergency_stop": False,
            "last_trade_time": None,
            "trades_this_hour": 0,
            "hour_start": None,
        }

        if self.state_file.exists():
            try:
                with open(self.state_file) as f:
                    state = json.load(f)
                    # Parse datetime strings
                    for key in ["cooldown_until", "last_trade_time", "hour_start"]:
                        if state.get(key):
                            state[key] = datetime.fromisoformat(state[key])
                    return state
            except Exception as e:
                logger.warning(f"Failed to load guardrails state: {e}")

        return default_state

    def _save_state(self):
        """Save guardrails state to file."""
        state_to_save = self._state.copy()

        # Convert datetimes to strings
        for key in ["cooldown_until", "last_trade_time", "hour_start"]:
            if state_to_save.get(key):
                state_to_save[key] = state_to_save[key].isoformat()

        try:
            with open(self.state_file, "w") as f:
                json.dump(state_to_save, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save guardrails state: {e}")

    def can_trade(self) -> tuple[bool, str]:
        """
        Check if trading is allowed.

        Returns:
            (can_trade, reason) tuple
        """
        # Check emergency stop
        if self._state["emergency_stop"]:
            return False, "Emergency stop is active"

        # Check cooldown
        if self._state["cooldown_until"]:
            if datetime.utcnow() < self._state["cooldown_until"]:
                remaining = self._state["cooldown_until"] - datetime.utcnow()
                return False, f"In cooldown for {remaining.seconds // 60} more minutes"
            else:
                # Cooldown expired
                self._state["cooldown_until"] = None
                self._state["consecutive_losses"] = 0
                self._save_state()

        return True, "OK"

    def record_trade_result(self, is_win: bool):
        """
        Record the result of a trade for consecutive loss tracking.

        Args:
            is_win: True if the trade was profitable
        """
        if is_win:
            self._state["consecutive_losses"] = 0
        else:
            self._state["consecutive_losses"] += 1

            # Check if we need to trigger cooldown
            if self._state["consecutive_losses"] >= self.max_consecutive_losses:
                self._trigger_cooldown()

        self._state["last_trade_time"] = datetime.utcnow()
        self._save_state()

    def _trigger_cooldown(self):
        """Trigger a cooldown period."""
        cooldown_end = datetime.utcnow() + timedelta(hours=self.cooldown_hours)
        self._state["cooldown_until"] = cooldown_end

        logger.warning(
            f"COOLDOWN TRIGGERED: {self._state['consecutive_losses']} consecutive losses. "
            f"Trading paused until {cooldown_end.strftime('%H:%M:%S UTC')}"
        )

    def activate_emergency_stop(self, reason: str = ""):
        """
        Activate emergency stop - halts all trading.

        Must be manually deactivated.
        """
        self._state["emergency_stop"] = True
        self._save_state()

        logger.error(f"EMERGENCY STOP ACTIVATED: {reason}")

    def deactivate_emergency_stop(self):
        """Deactivate emergency stop."""
        self._state["emergency_stop"] = False
        self._save_state()

        logger.info("Emergency stop deactivated")

    def reset_cooldown(self):
        """Manually reset cooldown (use with caution)."""
        self._state["cooldown_until"] = None
        self._state["consecutive_losses"] = 0
        self._save_state()

        logger.info("Cooldown reset manually")

    def check_trade_rate(self, max_trades_per_hour: int = 20) -> tuple[bool, str]:
        """
        Check if we're within hourly trade rate limits.

        Prevents runaway trading loops.
        """
        now = datetime.utcnow()

        # Reset counter if we're in a new hour
        if (
            not self._state["hour_start"]
            or now - self._state["hour_start"] > timedelta(hours=1)
        ):
            self._state["hour_start"] = now
            self._state["trades_this_hour"] = 0

        if self._state["trades_this_hour"] >= max_trades_per_hour:
            return False, f"Max trades per hour reached ({max_trades_per_hour})"

        return True, "OK"

    def record_trade_attempt(self):
        """Record a trade attempt for rate limiting."""
        now = datetime.utcnow()

        if (
            not self._state["hour_start"]
            or now - self._state["hour_start"] > timedelta(hours=1)
        ):
            self._state["hour_start"] = now
            self._state["trades_this_hour"] = 0

        self._state["trades_this_hour"] += 1
        self._save_state()

    def get_status(self) -> dict:
        """Get current guardrails status."""
        can_trade, reason = self.can_trade()

        cooldown_remaining = None
        if self._state["cooldown_until"]:
            remaining = self._state["cooldown_until"] - datetime.utcnow()
            if remaining.total_seconds() > 0:
                cooldown_remaining = remaining.total_seconds() / 60  # minutes

        return {
            "can_trade": can_trade,
            "reason": reason,
            "consecutive_losses": self._state["consecutive_losses"],
            "max_consecutive_losses": self.max_consecutive_losses,
            "cooldown_active": self._state["cooldown_until"] is not None,
            "cooldown_remaining_minutes": cooldown_remaining,
            "emergency_stop": self._state["emergency_stop"],
            "trades_this_hour": self._state["trades_this_hour"],
            "last_trade": (
                self._state["last_trade_time"].isoformat()
                if self._state["last_trade_time"]
                else None
            ),
        }

    def check_all(self) -> tuple[bool, list[str]]:
        """
        Run all guardrail checks.

        Returns:
            (all_passed, list of failed check reasons)
        """
        failures = []

        # Check main trading status
        can_trade, reason = self.can_trade()
        if not can_trade:
            failures.append(reason)

        # Check trade rate
        rate_ok, rate_reason = self.check_trade_rate()
        if not rate_ok:
            failures.append(rate_reason)

        return len(failures) == 0, failures


class DailyLossCircuitBreaker:
    """
    Specialized circuit breaker for daily loss limits.

    Automatically stops trading when daily loss limit is reached.
    """

    def __init__(self, db: Database, daily_limit: float = None):
        self.db = db
        self.daily_limit = daily_limit or settings.trading.daily_loss_limit
        self._triggered = False
        self._trigger_time = None

    def check(self) -> tuple[bool, str]:
        """
        Check if daily loss limit has been reached.

        Returns:
            (can_trade, reason)
        """
        if self._triggered:
            return False, "Daily loss limit was reached"

        daily_stats = self.db.get_today_stats()
        daily_pnl = daily_stats.realized_pnl + daily_stats.unrealized_pnl

        if daily_pnl <= -self.daily_limit:
            self._triggered = True
            self._trigger_time = datetime.utcnow()

            logger.error(
                f"DAILY LOSS LIMIT REACHED: ${abs(daily_pnl):.2f} "
                f"(limit: ${self.daily_limit})"
            )
            return False, f"Daily loss limit reached: ${abs(daily_pnl):.2f}"

        remaining = self.daily_limit + daily_pnl
        if remaining < self.daily_limit * 0.2:
            logger.warning(f"Daily loss limit warning: ${remaining:.2f} remaining")

        return True, f"${remaining:.2f} remaining before daily limit"

    def reset(self):
        """Reset for new day (called automatically at midnight)."""
        self._triggered = False
        self._trigger_time = None

    def get_remaining(self) -> float:
        """Get remaining loss allowance for today."""
        daily_stats = self.db.get_today_stats()
        daily_pnl = daily_stats.realized_pnl + daily_stats.unrealized_pnl
        return max(0, self.daily_limit + daily_pnl)
