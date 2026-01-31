"""
Pre-trade risk management checks.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from config import settings
from data.models import Market, RiskCheckResult, Position
from data.db import Database
from utils.logger import get_logger

logger = get_logger("polymarket.risk")


@dataclass
class RiskLimits:
    """Configurable risk limits."""
    # Position limits
    max_position_size: float = 3.0  # Max per position
    max_total_exposure: float = 8.0  # Max total exposure
    max_open_positions: int = 8

    # Loss limits
    daily_loss_limit: float = 3.0
    max_single_loss: float = 2.0

    # Edge requirements
    min_edge: float = 0.05
    min_confidence: float = 0.3

    # Liquidity requirements
    min_liquidity: float = 500.0
    max_position_vs_liquidity: float = 0.02  # Max 2% of market liquidity

    # Time requirements
    min_hours_to_resolution: int = 6


class RiskManager:
    """
    Pre-trade risk checks to prevent excessive losses.

    Checks:
    1. Daily loss limit not exceeded
    2. Total exposure limit not exceeded
    3. Single position limit not exceeded
    4. Max open positions not exceeded
    5. Minimum liquidity met
    6. Minimum edge threshold met
    7. Time to resolution check
    """

    def __init__(self, db: Database, limits: Optional[RiskLimits] = None):
        self.db = db
        self.limits = limits or RiskLimits(
            max_position_size=settings.trading.max_position_size,
            max_total_exposure=settings.trading.max_total_exposure,
            daily_loss_limit=settings.trading.daily_loss_limit,
            min_edge=settings.risk.min_edge_threshold,
            min_liquidity=settings.risk.min_liquidity,
            max_open_positions=settings.risk.max_open_positions,
            min_hours_to_resolution=settings.market_filter.min_hours_to_resolution,
        )

    def check_trade(
        self,
        market: Market,
        proposed_size: float,
        edge: float,
        confidence: float,
    ) -> RiskCheckResult:
        """
        Run all pre-trade risk checks.

        Args:
            market: Market to trade
            proposed_size: Proposed position size in dollars
            edge: Calculated edge (our prob - market price)
            confidence: Confidence in the estimate

        Returns:
            RiskCheckResult with pass/fail and reasons
        """
        checks = {}
        reasons = []
        approved_size = proposed_size

        # 1. Check daily loss limit
        daily_stats = self.db.get_today_stats()
        daily_pnl = daily_stats.realized_pnl + daily_stats.unrealized_pnl

        if daily_pnl <= -self.limits.daily_loss_limit:
            checks["daily_loss"] = False
            reasons.append(
                f"Daily loss limit reached: ${abs(daily_pnl):.2f} "
                f"(limit: ${self.limits.daily_loss_limit})"
            )
        else:
            checks["daily_loss"] = True

        # 2. Check total exposure
        current_exposure = self.db.get_total_exposure()
        new_exposure = current_exposure + proposed_size

        if new_exposure > self.limits.max_total_exposure:
            checks["total_exposure"] = False
            # Reduce size to fit
            available = self.limits.max_total_exposure - current_exposure
            if available > 0:
                approved_size = min(approved_size, available)
                reasons.append(
                    f"Size reduced to ${approved_size:.2f} due to exposure limit"
                )
            else:
                reasons.append(
                    f"Max exposure reached: ${current_exposure:.2f} "
                    f"(limit: ${self.limits.max_total_exposure})"
                )
        else:
            checks["total_exposure"] = True

        # 3. Check single position size
        if proposed_size > self.limits.max_position_size:
            checks["position_size"] = False
            approved_size = min(approved_size, self.limits.max_position_size)
            reasons.append(
                f"Size capped at ${self.limits.max_position_size} max position"
            )
        else:
            checks["position_size"] = True

        # 4. Check number of open positions
        open_positions = self.db.count_open_positions()
        if open_positions >= self.limits.max_open_positions:
            checks["position_count"] = False
            reasons.append(
                f"Max positions reached: {open_positions} "
                f"(limit: {self.limits.max_open_positions})"
            )
        else:
            checks["position_count"] = True

        # 5. Check market liquidity
        if market.liquidity < self.limits.min_liquidity:
            checks["liquidity"] = False
            reasons.append(
                f"Insufficient liquidity: ${market.liquidity:,.0f} "
                f"(min: ${self.limits.min_liquidity:,.0f})"
            )
        else:
            checks["liquidity"] = True

            # Also check position vs liquidity
            max_size_for_liquidity = market.liquidity * self.limits.max_position_vs_liquidity
            if approved_size > max_size_for_liquidity:
                approved_size = max_size_for_liquidity
                reasons.append(
                    f"Size reduced to ${approved_size:.2f} "
                    f"({self.limits.max_position_vs_liquidity:.0%} of liquidity)"
                )

        # 6. Check minimum edge
        if abs(edge) < self.limits.min_edge:
            checks["min_edge"] = False
            reasons.append(
                f"Edge too small: {abs(edge):.1%} "
                f"(min: {self.limits.min_edge:.1%})"
            )
        else:
            checks["min_edge"] = True

        # 7. Check minimum confidence
        if confidence < self.limits.min_confidence:
            checks["min_confidence"] = False
            reasons.append(
                f"Confidence too low: {confidence:.1%} "
                f"(min: {self.limits.min_confidence:.1%})"
            )
        else:
            checks["min_confidence"] = True

        # 8. Check time to resolution
        hours = market.hours_to_resolution
        if hours is not None and hours < self.limits.min_hours_to_resolution:
            checks["time_to_resolution"] = False
            reasons.append(
                f"Too close to resolution: {hours:.1f}h "
                f"(min: {self.limits.min_hours_to_resolution}h)"
            )
        else:
            checks["time_to_resolution"] = True

        # Determine overall pass/fail
        # Critical checks that must pass
        critical_checks = [
            "daily_loss",
            "position_count",
            "liquidity",
            "min_edge",
            "time_to_resolution",
        ]

        passed = all(
            checks.get(check, True) for check in critical_checks
        )

        # If we reduced size to 0, fail
        if approved_size <= 0:
            passed = False
            if "Size reduced to $0" not in str(reasons):
                reasons.append("No viable position size")

        result = RiskCheckResult(
            passed=passed,
            checks=checks,
            reasons=reasons,
            original_size=proposed_size,
            approved_size=approved_size if passed else 0,
            size_reduced=approved_size < proposed_size,
            reduction_reason="; ".join(
                r for r in reasons if "reduced" in r.lower() or "capped" in r.lower()
            ),
        )

        if not passed:
            logger.warning(f"Risk check FAILED: {'; '.join(reasons)}")
        elif result.size_reduced:
            logger.info(
                f"Risk check passed with reduced size: "
                f"${proposed_size:.2f} -> ${approved_size:.2f}"
            )

        return result

    def check_existing_position(
        self,
        market_id: str,
        token_id: str,
    ) -> Optional[Position]:
        """
        Check if we already have a position in this market.
        """
        return self.db.get_position(market_id, token_id)

    def check_correlated_positions(
        self,
        market: Market,
        open_positions: list[Position],
    ) -> list[str]:
        """
        Check for potentially correlated positions.

        Returns list of warnings about correlated positions.
        """
        warnings = []

        # Simple heuristic: check for same category or event
        for pos in open_positions:
            # Same event
            if market.event_id and market.event_id == pos.market_id:
                warnings.append(
                    f"Already have position in same event: {pos.market_question[:30]}..."
                )

        # Could add more sophisticated correlation checks here
        # (e.g., political markets, sports markets, etc.)

        return warnings

    def get_available_capital(self) -> float:
        """
        Calculate available capital for new trades.
        """
        current_exposure = self.db.get_total_exposure()
        return max(0, self.limits.max_total_exposure - current_exposure)

    def get_risk_summary(self) -> dict:
        """
        Get current risk status summary.
        """
        daily_stats = self.db.get_today_stats()
        daily_pnl = daily_stats.realized_pnl + daily_stats.unrealized_pnl

        current_exposure = self.db.get_total_exposure()
        open_positions = self.db.count_open_positions()
        available_capital = self.get_available_capital()

        return {
            "daily_pnl": daily_pnl,
            "daily_loss_remaining": self.limits.daily_loss_limit + daily_pnl,
            "daily_loss_limit": self.limits.daily_loss_limit,
            "current_exposure": current_exposure,
            "max_exposure": self.limits.max_total_exposure,
            "exposure_pct": current_exposure / self.limits.max_total_exposure,
            "open_positions": open_positions,
            "max_positions": self.limits.max_open_positions,
            "available_capital": available_capital,
            "can_trade": (
                daily_pnl > -self.limits.daily_loss_limit
                and open_positions < self.limits.max_open_positions
                and available_capital > 0
            ),
        }
