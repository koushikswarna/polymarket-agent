"""
Alert system for trading events and issues.

The alerter notifies you when important things happen:
- Large P&L changes (wins or losses)
- System errors or health issues
- Risk limits being approached
- Arbitrage opportunities detected

Currently supports console logging. Can be extended to support
email, Slack, Discord, or other notification channels.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Callable

from utils.logger import get_logger

logger = get_logger("polymarket.alerts")


class AlertLevel(Enum):
    """Severity levels for alerts."""
    INFO = "info"          # Nice to know
    WARNING = "warning"    # Might need attention
    CRITICAL = "critical"  # Needs immediate attention


@dataclass
class Alert:
    """A single alert."""
    level: AlertLevel
    title: str
    message: str
    timestamp: datetime = None
    data: dict = None  # Additional context

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()
        if self.data is None:
            self.data = {}


class Alerter:
    """
    Sends alerts for important trading events.

    The alerter helps you stay informed about what's happening
    with your trading bot without having to watch it constantly.

    Example usage:
        alerter = Alerter()

        # Set up a handler (e.g., for Slack)
        alerter.add_handler(my_slack_handler)

        # Send alerts
        alerter.info("Trade executed", "Bought YES on Bitcoin $100k")
        alerter.warning("Budget low", "LLM budget under $1")
        alerter.critical("Trading halted", "Daily loss limit reached")
    """

    def __init__(self):
        """Initialize the alerter."""
        self.handlers: list[Callable[[Alert], None]] = []
        self.alert_history: list[Alert] = []
        self.max_history = 1000

        # Add default console handler
        self.add_handler(self._console_handler)

    def add_handler(self, handler: Callable[[Alert], None]):
        """
        Add an alert handler.

        Handlers are functions that receive Alert objects and
        do something with them (log, send to Slack, etc.)
        """
        self.handlers.append(handler)

    def _console_handler(self, alert: Alert):
        """Default handler that logs to console."""
        if alert.level == AlertLevel.CRITICAL:
            logger.error(f"🚨 {alert.title}: {alert.message}")
        elif alert.level == AlertLevel.WARNING:
            logger.warning(f"⚠️ {alert.title}: {alert.message}")
        else:
            logger.info(f"ℹ️ {alert.title}: {alert.message}")

    def _send(self, alert: Alert):
        """Send alert to all handlers."""
        # Add to history
        self.alert_history.append(alert)
        if len(self.alert_history) > self.max_history:
            self.alert_history = self.alert_history[-self.max_history:]

        # Send to all handlers
        for handler in self.handlers:
            try:
                handler(alert)
            except Exception as e:
                logger.error(f"Alert handler failed: {e}")

    def info(self, title: str, message: str, **data):
        """Send an info-level alert."""
        self._send(Alert(
            level=AlertLevel.INFO,
            title=title,
            message=message,
            data=data,
        ))

    def warning(self, title: str, message: str, **data):
        """Send a warning-level alert."""
        self._send(Alert(
            level=AlertLevel.WARNING,
            title=title,
            message=message,
            data=data,
        ))

    def critical(self, title: str, message: str, **data):
        """Send a critical-level alert."""
        self._send(Alert(
            level=AlertLevel.CRITICAL,
            title=title,
            message=message,
            data=data,
        ))

    # ========== Convenience methods for common alerts ==========

    def trade_executed(self, side: str, market: str, size: float, price: float):
        """Alert when a trade is executed."""
        self.info(
            "Trade Executed",
            f"{side} ${size:.2f} on '{market[:40]}...' @ {price:.1%}",
            side=side,
            market=market,
            size=size,
            price=price,
        )

    def position_closed(self, market: str, pnl: float, pnl_pct: float):
        """Alert when a position is closed."""
        level = AlertLevel.INFO if pnl >= 0 else AlertLevel.WARNING
        self._send(Alert(
            level=level,
            title="Position Closed",
            message=f"'{market[:40]}...' P&L: ${pnl:+.2f} ({pnl_pct:+.1%})",
            data={"market": market, "pnl": pnl, "pnl_pct": pnl_pct},
        ))

    def arbitrage_found(self, event: str, profit_pct: float):
        """Alert when arbitrage is detected."""
        self.info(
            "Arbitrage Detected",
            f"'{event[:40]}...' - {profit_pct:.2%} profit potential",
            event=event,
            profit_pct=profit_pct,
        )

    def risk_warning(self, reason: str, current: float, limit: float):
        """Alert when approaching risk limits."""
        self.warning(
            "Risk Warning",
            f"{reason}: {current:.2f} / {limit:.2f}",
            reason=reason,
            current=current,
            limit=limit,
        )

    def daily_limit_reached(self, loss: float, limit: float):
        """Alert when daily loss limit is reached."""
        self.critical(
            "Daily Loss Limit Reached",
            f"Lost ${abs(loss):.2f} (limit: ${limit:.2f}) - Trading halted",
            loss=loss,
            limit=limit,
        )

    def budget_low(self, provider: str, remaining: float):
        """Alert when LLM budget is running low."""
        self.warning(
            "LLM Budget Low",
            f"{provider}: ${remaining:.2f} remaining",
            provider=provider,
            remaining=remaining,
        )

    def system_error(self, component: str, error: str):
        """Alert on system errors."""
        self.critical(
            "System Error",
            f"{component}: {error}",
            component=component,
            error=error,
        )

    def get_recent_alerts(self, count: int = 10) -> list[Alert]:
        """Get the most recent alerts."""
        return self.alert_history[-count:]


# Convenience: Global alerter instance
_default_alerter: Optional[Alerter] = None


def get_alerter() -> Alerter:
    """Get the global alerter instance."""
    global _default_alerter
    if _default_alerter is None:
        _default_alerter = Alerter()
    return _default_alerter
