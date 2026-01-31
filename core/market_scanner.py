"""
Market scanner for discovering and filtering tradeable markets.
"""

from datetime import datetime, timedelta
from typing import Optional

from config import settings
from data.models import Market
from utils.logger import get_logger
from utils.helpers import memoize_with_ttl

from .client import PolymarketClient

logger = get_logger("polymarket.scanner")


class MarketScanner:
    """
    Scans Polymarket for tradeable markets with filtering and prioritization.
    """

    def __init__(self, client: PolymarketClient):
        self.client = client
        self._market_cache: dict[str, Market] = {}

    def scan_all_markets(self, use_cache: bool = True) -> list[Market]:
        """
        Fetch all active markets from Polymarket.

        Args:
            use_cache: Whether to use cached market data

        Returns:
            List of Market objects
        """
        raw_markets = self.client.get_all_markets(active=True)
        markets = []

        for raw in raw_markets:
            try:
                market = self.client.parse_market(raw)
                markets.append(market)

                if use_cache:
                    self._market_cache[market.id] = market

            except Exception as e:
                logger.warning(f"Failed to parse market: {e}")
                continue

        logger.info(f"Scanned {len(markets)} active markets")
        return markets

    def get_market(self, market_id: str) -> Optional[Market]:
        """Get a market by ID, using cache if available."""
        if market_id in self._market_cache:
            return self._market_cache[market_id]

        raw = self.client.get_market(market_id)
        if raw:
            market = self.client.parse_market(raw)
            self._market_cache[market_id] = market
            return market
        return None

    def filter_markets(
        self,
        markets: list[Market],
        min_liquidity: Optional[float] = None,
        min_hours: Optional[int] = None,
        max_days: Optional[int] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        exclude_resolved: bool = True,
        exclude_closed: bool = True,
    ) -> list[Market]:
        """
        Filter markets based on criteria.

        Args:
            markets: List of markets to filter
            min_liquidity: Minimum liquidity required
            min_hours: Minimum hours until resolution
            max_days: Maximum days until resolution
            min_price: Minimum YES price (exclude < 3%)
            max_price: Maximum YES price (exclude > 97%)
            exclude_resolved: Skip already resolved markets
            exclude_closed: Skip closed markets

        Returns:
            Filtered list of markets
        """
        # Use settings defaults if not specified
        min_liquidity = min_liquidity or settings.market_filter.min_liquidity
        min_hours = min_hours or settings.market_filter.min_hours_to_resolution
        max_days = max_days or settings.market_filter.max_days_to_resolution
        min_price = min_price or settings.market_filter.min_price
        max_price = max_price or settings.market_filter.max_price

        filtered = []

        for market in markets:
            # Skip resolved/closed
            if exclude_resolved and market.resolved:
                continue
            if exclude_closed and market.closed:
                continue

            # Check liquidity
            if market.liquidity < min_liquidity:
                continue

            # Check time to resolution
            hours = market.hours_to_resolution
            if hours is not None:
                if hours < min_hours:
                    continue
                if hours > max_days * 24:
                    continue

            # Check price extremes
            yes_price = market.yes_price
            if yes_price is not None:
                if yes_price < min_price or yes_price > max_price:
                    continue

            filtered.append(market)

        logger.info(
            f"Filtered {len(markets)} markets down to {len(filtered)} candidates"
        )
        return filtered

    def prioritize_markets(self, markets: list[Market]) -> list[Market]:
        """
        Sort markets by priority for analysis.

        Priority factors:
        1. Time to resolution (shorter = higher priority)
        2. Volume (higher = higher priority)
        3. Liquidity (higher = higher priority)
        """
        def priority_score(market: Market) -> float:
            score = 0.0

            # Time factor: prefer markets resolving in 1-14 days
            hours = market.hours_to_resolution
            if hours:
                days = hours / 24
                if 1 <= days <= settings.market_filter.priority_days:
                    # Higher score for optimal range
                    score += 100 - (days * 5)  # Max 95 for 1 day
                elif days < 1:
                    score += 50  # Still decent for same-day
                else:
                    score += max(0, 50 - (days - 14) * 2)

            # Volume factor (log scale to prevent domination)
            if market.volume_24h > 0:
                import math
                score += min(50, math.log10(market.volume_24h + 1) * 10)

            # Liquidity factor
            if market.liquidity > 0:
                import math
                score += min(30, math.log10(market.liquidity + 1) * 5)

            # Bonus for NegRisk (arbitrage potential)
            if market.neg_risk:
                score += 20

            return score

        sorted_markets = sorted(markets, key=priority_score, reverse=True)
        return sorted_markets

    def get_tradeable_markets(self, limit: int = 50) -> list[Market]:
        """
        Main entry point: get prioritized list of tradeable markets.

        Args:
            limit: Maximum number of markets to return

        Returns:
            Prioritized list of tradeable markets
        """
        # Scan all markets
        all_markets = self.scan_all_markets()

        # Apply filters
        filtered = self.filter_markets(all_markets)

        # Prioritize
        prioritized = self.prioritize_markets(filtered)

        # Limit results
        top_markets = prioritized[:limit]

        logger.info(f"Returning top {len(top_markets)} tradeable markets")
        return top_markets

    def get_neg_risk_events(self) -> dict[str, list[Market]]:
        """
        Group NegRisk markets by event for arbitrage scanning.

        NegRisk markets are multi-outcome markets where outcomes are
        mutually exclusive (e.g., "Who will win?" with multiple candidates).

        Returns:
            Dict mapping event_id to list of markets in that event
        """
        all_markets = self.scan_all_markets()

        # Filter to NegRisk only
        neg_risk_markets = [m for m in all_markets if m.neg_risk]

        # Group by event
        events: dict[str, list[Market]] = {}
        for market in neg_risk_markets:
            event_id = market.event_id
            if event_id:
                if event_id not in events:
                    events[event_id] = []
                events[event_id].append(market)

        # Only return events with multiple markets (arbitrage potential)
        multi_outcome_events = {
            eid: markets for eid, markets in events.items()
            if len(markets) >= 2
        }

        logger.info(
            f"Found {len(multi_outcome_events)} NegRisk events with "
            f"multiple outcomes"
        )
        return multi_outcome_events

    def get_markets_by_category(self, category: str) -> list[Market]:
        """Get all markets in a specific category."""
        all_markets = self.scan_all_markets()
        return [
            m for m in all_markets
            if category.lower() in m.category.lower()
        ]

    def get_expiring_soon(self, hours: int = 24) -> list[Market]:
        """Get markets expiring within specified hours."""
        all_markets = self.scan_all_markets()
        return [
            m for m in all_markets
            if m.hours_to_resolution and 0 < m.hours_to_resolution <= hours
        ]

    def refresh_market_prices(self, markets: list[Market]) -> list[Market]:
        """
        Update market prices from order book data.

        Uses CLOB API to get real-time mid prices.
        """
        updated = []

        for market in markets:
            for token in market.tokens:
                if token.token_id:
                    price = self.client.get_midpoint_price(token.token_id)
                    if price is not None:
                        token.price = price

            market.updated_at = datetime.utcnow()
            updated.append(market)

        return updated

    def get_market_summary(self, market: Market) -> dict:
        """Get a summary of market information."""
        return {
            "id": market.id,
            "question": market.question[:100],
            "yes_price": market.yes_price,
            "no_price": market.no_price,
            "liquidity": market.liquidity,
            "volume_24h": market.volume_24h,
            "hours_to_resolution": market.hours_to_resolution,
            "days_to_resolution": market.days_to_resolution,
            "neg_risk": market.neg_risk,
            "category": market.category,
        }
