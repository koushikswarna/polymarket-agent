"""
Health checking for all system components.

The health checker monitors:
- API connectivity (Polymarket, LLM providers)
- Database health
- System resources
- Trading system state

Regular health checks help catch problems early before they
cause trading failures or financial losses.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from enum import Enum


class HealthStatus(Enum):
    """Health status levels."""
    HEALTHY = "healthy"      # Everything is working fine
    DEGRADED = "degraded"    # Some issues but still functional
    UNHEALTHY = "unhealthy"  # Critical problems, should stop trading


@dataclass
class ComponentHealth:
    """Health status of a single component."""
    name: str
    status: HealthStatus
    message: str
    last_check: datetime = field(default_factory=datetime.utcnow)
    response_time_ms: Optional[float] = None

    @property
    def is_healthy(self) -> bool:
        return self.status == HealthStatus.HEALTHY


@dataclass
class SystemHealth:
    """Overall system health status."""
    status: HealthStatus
    components: list[ComponentHealth]
    checked_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def is_healthy(self) -> bool:
        return self.status == HealthStatus.HEALTHY

    @property
    def unhealthy_components(self) -> list[str]:
        return [c.name for c in self.components if not c.is_healthy]

    def summary(self) -> str:
        """Generate a human-readable health summary."""
        lines = [
            f"System Health: {self.status.value.upper()}",
            f"Checked at: {self.checked_at.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "Components:",
        ]

        for comp in self.components:
            icon = "✓" if comp.is_healthy else "✗"
            lines.append(f"  {icon} {comp.name}: {comp.status.value} - {comp.message}")

        return "\n".join(lines)


class HealthChecker:
    """
    Monitors the health of all system components.

    Use this to:
    - Run regular health checks before trading
    - Diagnose issues when things go wrong
    - Monitor system performance

    Example usage:
        checker = HealthChecker(client, db)
        health = checker.check_all()

        if not health.is_healthy:
            print("Problems detected:", health.unhealthy_components)
            # Maybe pause trading until fixed
    """

    def __init__(self, client=None, db=None):
        """
        Initialize the health checker.

        Args:
            client: PolymarketClient instance
            db: Database instance
        """
        self.client = client
        self.db = db

    def check_all(self) -> SystemHealth:
        """
        Run all health checks and return overall status.

        Returns:
            SystemHealth with status of all components
        """
        components = []

        # Check each component
        components.append(self._check_database())
        components.append(self._check_polymarket_api())
        components.append(self._check_llm_apis())
        components.append(self._check_trading_state())

        # Determine overall status
        if any(c.status == HealthStatus.UNHEALTHY for c in components):
            overall_status = HealthStatus.UNHEALTHY
        elif any(c.status == HealthStatus.DEGRADED for c in components):
            overall_status = HealthStatus.DEGRADED
        else:
            overall_status = HealthStatus.HEALTHY

        return SystemHealth(
            status=overall_status,
            components=components,
        )

    def _check_database(self) -> ComponentHealth:
        """Check database connectivity and integrity."""
        import time

        if not self.db:
            return ComponentHealth(
                name="Database",
                status=HealthStatus.UNHEALTHY,
                message="Database not configured",
            )

        try:
            start = time.time()
            # Try a simple query
            self.db.get_today_stats()
            elapsed = (time.time() - start) * 1000

            return ComponentHealth(
                name="Database",
                status=HealthStatus.HEALTHY,
                message=f"Connected and responsive",
                response_time_ms=elapsed,
            )
        except Exception as e:
            return ComponentHealth(
                name="Database",
                status=HealthStatus.UNHEALTHY,
                message=f"Error: {str(e)}",
            )

    def _check_polymarket_api(self) -> ComponentHealth:
        """Check Polymarket API connectivity."""
        if not self.client:
            return ComponentHealth(
                name="Polymarket API",
                status=HealthStatus.DEGRADED,
                message="Client not configured",
            )

        try:
            health = self.client.health_check()

            if health.get("gamma_api") and health.get("authenticated"):
                return ComponentHealth(
                    name="Polymarket API",
                    status=HealthStatus.HEALTHY,
                    message="All APIs connected",
                )
            elif health.get("gamma_api"):
                return ComponentHealth(
                    name="Polymarket API",
                    status=HealthStatus.DEGRADED,
                    message="Public API OK, trading API issues",
                )
            else:
                return ComponentHealth(
                    name="Polymarket API",
                    status=HealthStatus.UNHEALTHY,
                    message="Cannot connect to APIs",
                )
        except Exception as e:
            return ComponentHealth(
                name="Polymarket API",
                status=HealthStatus.UNHEALTHY,
                message=f"Error: {str(e)}",
            )

    def _check_llm_apis(self) -> ComponentHealth:
        """Check LLM API availability and budget."""
        if not self.db:
            return ComponentHealth(
                name="LLM APIs",
                status=HealthStatus.DEGRADED,
                message="Cannot check budget",
            )

        try:
            budget = self.db.get_llm_budget()

            if budget.all_exhausted:
                return ComponentHealth(
                    name="LLM APIs",
                    status=HealthStatus.DEGRADED,
                    message="Budget exhausted - arbitrage only mode",
                )

            remaining = budget.total_remaining
            if remaining < 1.0:
                return ComponentHealth(
                    name="LLM APIs",
                    status=HealthStatus.DEGRADED,
                    message=f"Low budget: ${remaining:.2f} remaining",
                )

            return ComponentHealth(
                name="LLM APIs",
                status=HealthStatus.HEALTHY,
                message=f"Budget OK: ${remaining:.2f} remaining",
            )
        except Exception as e:
            return ComponentHealth(
                name="LLM APIs",
                status=HealthStatus.DEGRADED,
                message=f"Error checking: {str(e)}",
            )

    def _check_trading_state(self) -> ComponentHealth:
        """Check trading system state."""
        if not self.db:
            return ComponentHealth(
                name="Trading State",
                status=HealthStatus.DEGRADED,
                message="Cannot check state",
            )

        try:
            stats = self.db.get_today_stats()
            positions = self.db.count_open_positions()

            # Check for warning signs
            warnings = []

            if stats.consecutive_losses >= 3:
                warnings.append(f"{stats.consecutive_losses} consecutive losses")

            if stats.total_pnl < -2.0:
                warnings.append(f"Down ${abs(stats.total_pnl):.2f} today")

            if warnings:
                return ComponentHealth(
                    name="Trading State",
                    status=HealthStatus.DEGRADED,
                    message="; ".join(warnings),
                )

            return ComponentHealth(
                name="Trading State",
                status=HealthStatus.HEALTHY,
                message=f"{positions} open positions, ${stats.total_pnl:+.2f} today",
            )
        except Exception as e:
            return ComponentHealth(
                name="Trading State",
                status=HealthStatus.DEGRADED,
                message=f"Error: {str(e)}",
            )

    def quick_check(self) -> bool:
        """
        Quick health check - just returns True/False.

        Use this for fast checks in the trading loop.
        """
        health = self.check_all()
        return health.status != HealthStatus.UNHEALTHY
