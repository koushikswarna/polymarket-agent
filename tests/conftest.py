"""
Pytest configuration and shared fixtures.
"""

import os
import sys
import pytest
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.models import Market, Token, Order, Position, Trade, Side, OrderType, OrderStatus
from data.db import Database


# ============== Database Fixtures ==============

@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    db = Database(db_path)
    yield db

    # Cleanup
    try:
        os.unlink(db_path)
    except:
        pass


@pytest.fixture
def populated_db(temp_db):
    """Database with sample data."""
    # Add sample positions
    position = Position(
        market_id="test_market_1",
        token_id="token_yes_1",
        market_question="Will Bitcoin reach $100k by end of 2024?",
        outcome="Yes",
        size=10.0,
        avg_entry_price=0.45,
        cost_basis=4.50,
        current_price=0.55,
        market_value=5.50,
        unrealized_pnl=1.00,
        unrealized_pnl_pct=0.222,
    )
    temp_db.save_position(position)

    # Add sample trade
    trade = Trade(
        id="trade_1",
        order_id="order_1",
        market_id="test_market_1",
        token_id="token_yes_1",
        side=Side.BUY,
        price=0.45,
        size=10.0,
        cost=4.50,
        fees=0.0,
        reason="Test trade",
    )
    temp_db.save_trade(trade)

    return temp_db


# ============== Market Fixtures ==============

@pytest.fixture
def sample_market():
    """Create a sample market for testing."""
    return Market(
        id="condition_123",
        question="Will the Fed raise interest rates in March 2024?",
        description="This market resolves YES if the Federal Reserve raises rates.",
        category="Economics",
        tokens=[
            Token(token_id="token_yes_123", outcome="Yes", price=0.65),
            Token(token_id="token_no_123", outcome="No", price=0.35),
        ],
        end_date=datetime.utcnow() + timedelta(days=14),
        active=True,
        liquidity=5000.0,
        volume=25000.0,
        volume_24h=1500.0,
        neg_risk=False,
    )


@pytest.fixture
def sample_markets():
    """Create multiple sample markets."""
    markets = []

    questions = [
        ("Will Bitcoin reach $100k?", "Crypto", 0.35, 10000),
        ("Will SpaceX launch Starship?", "Science", 0.72, 8000),
        ("Will the Lakers win the championship?", "Sports", 0.15, 15000),
        ("Will GPT-5 be released in 2024?", "Tech", 0.45, 12000),
        ("Will inflation drop below 3%?", "Economics", 0.55, 6000),
    ]

    for i, (question, category, price, liquidity) in enumerate(questions):
        market = Market(
            id=f"market_{i}",
            question=question,
            category=category,
            tokens=[
                Token(token_id=f"yes_{i}", outcome="Yes", price=price),
                Token(token_id=f"no_{i}", outcome="No", price=1-price),
            ],
            end_date=datetime.utcnow() + timedelta(days=7 + i*3),
            active=True,
            liquidity=liquidity,
            volume=liquidity * 5,
            volume_24h=liquidity * 0.3,
        )
        markets.append(market)

    return markets


@pytest.fixture
def neg_risk_markets():
    """Create NegRisk multi-outcome markets for arbitrage testing."""
    event_id = "election_2024"
    candidates = [
        ("Biden", 0.25),
        ("Trump", 0.45),
        ("DeSantis", 0.15),
        ("Haley", 0.10),
    ]

    markets = []
    for i, (name, price) in enumerate(candidates):
        market = Market(
            id=f"candidate_{i}",
            question=f"Will {name} win the 2024 election?",
            category="Politics",
            tokens=[
                Token(token_id=f"yes_cand_{i}", outcome="Yes", price=price),
                Token(token_id=f"no_cand_{i}", outcome="No", price=1-price),
            ],
            end_date=datetime.utcnow() + timedelta(days=300),
            active=True,
            liquidity=50000,
            neg_risk=True,
            event_id=event_id,
            event_title="2024 Presidential Election Winner",
        )
        markets.append(market)

    return markets


# ============== Order Fixtures ==============

@pytest.fixture
def sample_order():
    """Create a sample order."""
    return Order(
        id="order_test_1",
        market_id="market_1",
        token_id="yes_1",
        side=Side.BUY,
        order_type=OrderType.GTC,
        price=0.45,
        size=10.0,
        status=OrderStatus.PENDING,
        reason="Test order",
    )


# ============== Mock Client Fixtures ==============

@pytest.fixture
def mock_polymarket_client():
    """Mock Polymarket client for testing."""
    client = MagicMock()

    # Mock Gamma API responses
    client.get_markets.return_value = []
    client.get_events.return_value = []
    client.get_market.return_value = None

    # Mock CLOB API responses
    client.get_order_book.return_value = {
        "bids": [{"price": "0.44", "size": "100"}],
        "asks": [{"price": "0.46", "size": "100"}],
    }
    client.get_midpoint_price.return_value = 0.45
    client.get_spread.return_value = {
        "best_bid": 0.44,
        "best_ask": 0.46,
        "spread": 0.02,
        "spread_pct": 0.043,
        "bid_depth": 500,
        "ask_depth": 500,
    }
    client.get_balance.return_value = 10.0
    client.place_order.return_value = Order(
        id="mock_order_1",
        market_id="",
        token_id="",
        side=Side.BUY,
        price=0.45,
        size=10.0,
        status=OrderStatus.FILLED,
        filled_size=10.0,
    )

    return client


@pytest.fixture
def mock_llm_responses():
    """Mock LLM API responses."""
    return {
        "screening": {
            "probability": 0.65,
            "confidence": 0.7,
            "reasoning": "Based on historical patterns and current trends.",
            "worth_deeper_analysis": True,
        },
        "deep_analysis": {
            "probability": 0.68,
            "confidence": 0.75,
            "base_rate": 0.50,
            "base_rate_reasoning": "Historical average for similar events.",
            "upside_factors": ["Strong momentum", "Positive news"],
            "downside_factors": ["Market uncertainty", "Time pressure"],
            "contrarian_view": "Markets could overcorrect.",
            "reasoning": "Comprehensive analysis suggests higher probability.",
            "trade_recommendation": "BUY_YES",
            "edge_assessment": "MEDIUM",
        },
    }


# ============== Settings Fixtures ==============

@pytest.fixture
def test_settings():
    """Override settings for testing."""
    with patch.dict(os.environ, {
        "DRY_RUN": "true",
        "STARTING_CAPITAL": "10.0",
        "MAX_POSITION_SIZE": "3.0",
        "ANTHROPIC_API_KEY": "test_key",
        "OPENAI_API_KEY": "test_key",
    }):
        yield


# ============== Helper Functions ==============

def create_mock_order_book(best_bid: float, best_ask: float, depth: int = 5):
    """Create a mock order book."""
    bids = [
        {"price": str(best_bid - i * 0.01), "size": str(100 + i * 10)}
        for i in range(depth)
    ]
    asks = [
        {"price": str(best_ask + i * 0.01), "size": str(100 + i * 10)}
        for i in range(depth)
    ]
    return {"bids": bids, "asks": asks}


def assert_order_valid(order: Order):
    """Assert that an order has valid fields."""
    assert order.id is not None
    assert 0 <= order.price <= 1
    assert order.size > 0
    assert order.side in [Side.BUY, Side.SELL]
    assert order.order_type in [OrderType.GTC, OrderType.FOK, OrderType.IOC]
