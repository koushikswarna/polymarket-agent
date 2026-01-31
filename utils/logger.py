"""
Structured logging with Rich for terminal output.
"""

import logging
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

from rich.console import Console
from rich.logging import RichHandler
from rich.theme import Theme

# Custom theme for trading logs
TRADING_THEME = Theme({
    "info": "cyan",
    "warning": "yellow",
    "error": "red bold",
    "success": "green",
    "trade.buy": "green bold",
    "trade.sell": "red bold",
    "profit": "green",
    "loss": "red",
    "market": "blue",
    "price": "magenta",
})

console = Console(theme=TRADING_THEME)

# Module-level logger cache
_loggers: dict[str, logging.Logger] = {}


def setup_logger(
    name: str = "polymarket",
    level: str = "INFO",
    log_file: Optional[Path] = None,
) -> logging.Logger:
    """
    Set up a logger with Rich console handler and optional file handler.

    Args:
        name: Logger name
        level: Logging level (DEBUG, INFO, WARNING, ERROR)
        log_file: Optional path to log file

    Returns:
        Configured logger instance
    """
    if name in _loggers:
        return _loggers[name]

    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper()))

    # Clear existing handlers
    logger.handlers.clear()

    # Rich console handler
    console_handler = RichHandler(
        console=console,
        show_time=True,
        show_path=False,
        rich_tracebacks=True,
        tracebacks_show_locals=True,
        markup=True,
    )
    console_handler.setLevel(getattr(logging, level.upper()))
    console_format = logging.Formatter("%(message)s")
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)

    # File handler if specified
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)  # Log everything to file
        file_format = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)

    _loggers[name] = logger
    return logger


def get_logger(name: str = "polymarket") -> logging.Logger:
    """Get or create a logger by name."""
    if name not in _loggers:
        return setup_logger(name)
    return _loggers[name]


class TradingLogger:
    """
    Specialized logger for trading events with semantic formatting.
    """

    def __init__(self, name: str = "polymarket.trading"):
        self.logger = get_logger(name)

    def trade_placed(
        self,
        side: str,
        market: str,
        price: float,
        size: float,
        reason: str = "",
    ):
        """Log a trade placement."""
        style = "trade.buy" if side.upper() == "BUY" else "trade.sell"
        self.logger.info(
            f"[{style}]{side}[/{style}] {size:.2f} shares @ ${price:.3f} | "
            f"[market]{market[:50]}...[/market]"
            + (f" | {reason}" if reason else "")
        )

    def trade_filled(
        self,
        side: str,
        market: str,
        price: float,
        size: float,
        cost: float,
    ):
        """Log a trade fill."""
        style = "trade.buy" if side.upper() == "BUY" else "trade.sell"
        self.logger.info(
            f"[{style}]FILLED[/{style}] {side} {size:.2f} @ ${price:.3f} = ${cost:.2f}"
        )

    def position_opened(
        self,
        market: str,
        outcome: str,
        size: float,
        price: float,
    ):
        """Log new position."""
        self.logger.info(
            f"[success]POSITION OPENED[/success] {outcome} on [market]{market[:40]}[/market] | "
            f"{size:.2f} shares @ ${price:.3f}"
        )

    def position_closed(
        self,
        market: str,
        outcome: str,
        pnl: float,
        pnl_pct: float,
    ):
        """Log position closure."""
        style = "profit" if pnl >= 0 else "loss"
        sign = "+" if pnl >= 0 else ""
        self.logger.info(
            f"[{style}]POSITION CLOSED[/{style}] {outcome} on [market]{market[:40]}[/market] | "
            f"P&L: [{style}]{sign}${pnl:.2f} ({sign}{pnl_pct:.1%})[/{style}]"
        )

    def edge_detected(
        self,
        market: str,
        our_prob: float,
        market_price: float,
        edge: float,
    ):
        """Log edge detection."""
        direction = "YES" if edge > 0 else "NO"
        self.logger.info(
            f"[success]EDGE DETECTED[/success] {direction} on [market]{market[:40]}[/market] | "
            f"Our: {our_prob:.1%} vs Market: {market_price:.1%} = [price]{abs(edge):.1%} edge[/price]"
        )

    def arbitrage_detected(
        self,
        event: str,
        profit_pct: float,
        cost: float,
    ):
        """Log arbitrage opportunity."""
        self.logger.info(
            f"[success]ARBITRAGE[/success] on [market]{event[:40]}[/market] | "
            f"Profit: [profit]{profit_pct:.2%}[/profit] | Cost: ${cost:.2f}"
        )

    def risk_blocked(self, reason: str):
        """Log risk check blocking a trade."""
        self.logger.warning(f"[warning]RISK BLOCKED[/warning] {reason}")

    def budget_warning(self, provider: str, remaining: float):
        """Log LLM budget warning."""
        self.logger.warning(
            f"[warning]BUDGET LOW[/warning] {provider}: ${remaining:.2f} remaining"
        )

    def daily_summary(
        self,
        realized_pnl: float,
        unrealized_pnl: float,
        trades: int,
        wins: int,
        losses: int,
    ):
        """Log daily summary."""
        total = realized_pnl + unrealized_pnl
        style = "profit" if total >= 0 else "loss"
        sign = "+" if total >= 0 else ""
        win_rate = wins / trades * 100 if trades > 0 else 0

        self.logger.info(
            f"\n[bold]DAILY SUMMARY[/bold]\n"
            f"  Total P&L: [{style}]{sign}${total:.2f}[/{style}]\n"
            f"  Realized: ${realized_pnl:.2f} | Unrealized: ${unrealized_pnl:.2f}\n"
            f"  Trades: {trades} | Win Rate: {win_rate:.1f}% ({wins}W/{losses}L)"
        )


# Convenience function
def log_trade(
    side: str,
    market: str,
    price: float,
    size: float,
    reason: str = "",
):
    """Quick trade logging."""
    TradingLogger().trade_placed(side, market, price, size, reason)
