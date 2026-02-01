"""
Mock Polymarket client for testing.

This mock client simulates the Polymarket API without making
real network requests. Perfect for unit tests.
"""

from datetime import datetime, timedelta
from typing import Optional
from unittest.mock import MagicMock

from data.models import Market, Token, Order, OrderStatus, Side, OrderType


class MockPolymarketClient:
    """
    A mock Polymarket client for testing.

    This class simulates the behavior of the real PolymarketClient
    without making any network requests. Use it in tests to:
    - Avoid hitting rate limits
    - Test without API credentials
    - Control exactly what data is returned
    - Simulate error conditions

    Example usage:
        client = MockPolymarketClient()
        client.set_markets([mock_market_1, mock_market_2])

        # Now use client in your tests
        markets = client.get_all_markets()
    """

    def __init__(self):
        self._markets: list[dict] = []
        self._balance: float = 10.0
        self._positions: list[dict] = []
        self._order_counter = 0
        self._should_fail = False
        self._failure_message = ""

    def set_markets(self, markets: list[dict]):
        """Set the markets that will be returned by get_all_markets."""
        self._markets = markets

    def set_balance(self, balance: float):
        """Set the balance that will be returned."""
        self._balance = balance

    def set_should_fail(self, should_fail: bool, message: str = "Mock failure"):
        """Make the client simulate failures."""
        self._should_fail = should_fail
        self._failure_message = message

    def get_all_markets(self, active: bool = True) -> list[dict]:
        """Return mock markets."""
        if self._should_fail:
            raise Exception(self._failure_message)
        return self._markets

    def get_markets(self, **kwargs) -> list[dict]:
        """Return mock markets with pagination."""
        if self._should_fail:
            raise Exception(self._failure_message)
        limit = kwargs.get("limit", 100)
        offset = kwargs.get("offset", 0)
        return self._markets[offset:offset + limit]

    def get_market(self, condition_id: str) -> Optional[dict]:
        """Return a specific mock market."""
        for market in self._markets:
            if market.get("conditionId") == condition_id:
                return market
        return None

    def get_balance(self) -> float:
        """Return mock balance."""
        return self._balance

    def get_order_book(self, token_id: str) -> dict:
        """Return a mock order book."""
        return {
            "bids": [
                {"price": "0.45", "size": "100"},
                {"price": "0.44", "size": "200"},
                {"price": "0.43", "size": "300"},
            ],
            "asks": [
                {"price": "0.46", "size": "100"},
                {"price": "0.47", "size": "200"},
                {"price": "0.48", "size": "300"},
            ],
        }

    def get_midpoint_price(self, token_id: str) -> float:
        """Return mock midpoint price."""
        return 0.455

    def get_spread(self, token_id: str) -> dict:
        """Return mock spread info."""
        return {
            "best_bid": 0.45,
            "best_ask": 0.46,
            "spread": 0.01,
            "spread_pct": 0.022,
            "bid_depth": 600,
            "ask_depth": 600,
        }

    def place_order(
        self,
        token_id: str,
        side: Side,
        price: float,
        size: float,
        order_type: OrderType = OrderType.GTC,
    ) -> Optional[Order]:
        """Simulate placing an order."""
        if self._should_fail:
            return None

        self._order_counter += 1
        return Order(
            id=f"mock_order_{self._order_counter}",
            market_id="mock_market",
            token_id=token_id,
            side=side,
            order_type=order_type,
            price=price,
            size=size,
            status=OrderStatus.FILLED,
            filled_size=size,
        )

    def cancel_order(self, order_id: str) -> bool:
        """Simulate canceling an order."""
        return not self._should_fail

    def get_positions(self) -> list[dict]:
        """Return mock positions."""
        return self._positions

    def health_check(self) -> dict:
        """Return mock health status."""
        return {
            "gamma_api": True,
            "clob_api": True,
            "authenticated": True,
        }

    def parse_market(self, raw: dict) -> Market:
        """Parse a raw market dict into a Market object."""
        return Market(
            id=raw.get("conditionId", "mock_id"),
            question=raw.get("question", "Mock question?"),
            description=raw.get("description", ""),
            category=raw.get("category", ""),
            tokens=[
                Token(token_id="yes_token", outcome="Yes", price=0.5),
                Token(token_id="no_token", outcome="No", price=0.5),
            ],
            end_date=datetime.utcnow() + timedelta(days=14),
            active=True,
            liquidity=raw.get("liquidity", 10000),
        )


def create_mock_market(
    market_id: str = "mock_market_1",
    question: str = "Will this happen?",
    yes_price: float = 0.50,
    liquidity: float = 10000,
    days_to_resolution: int = 14,
) -> dict:
    """
    Helper function to create mock market data.

    Use this to quickly generate test markets with specific properties.
    """
    return {
        "conditionId": market_id,
        "question": question,
        "description": f"Description for {question}",
        "category": "Test",
        "outcomes": ["Yes", "No"],
        "outcomePrices": [str(yes_price), str(1 - yes_price)],
        "clobTokenIds": [f"yes_{market_id}", f"no_{market_id}"],
        "endDate": (datetime.utcnow() + timedelta(days=days_to_resolution)).isoformat(),
        "active": True,
        "liquidity": liquidity,
        "volume": liquidity * 5,
        "volume24hr": liquidity * 0.1,
    }
