"""
Sample trade and position data for testing.
"""

from datetime import datetime, timedelta
from data.models import Side

# Sample trades for testing
SAMPLE_TRADES = [
    {
        "id": "trade_001",
        "order_id": "order_001",
        "market_id": "btc_100k",
        "token_id": "btc_yes",
        "side": "BUY",
        "price": 0.35,
        "size": 10.0,
        "cost": 3.50,
        "fees": 0.0,
        "reason": "Edge=15%, Confidence=75%",
        "executed_at": datetime.utcnow() - timedelta(hours=2),
        "pnl": 0.50,  # Still open, unrealized
    },
    {
        "id": "trade_002",
        "order_id": "order_002",
        "market_id": "fed_rates",
        "token_id": "fed_no",
        "side": "BUY",
        "price": 0.75,
        "size": 5.0,
        "cost": 3.75,
        "fees": 0.0,
        "reason": "Edge=10%, Confidence=70%",
        "executed_at": datetime.utcnow() - timedelta(hours=5),
        "pnl": -0.25,
    },
    {
        "id": "trade_003",
        "order_id": "order_003",
        "market_id": "spacex_starship",
        "token_id": "spacex_yes",
        "side": "BUY",
        "price": 0.65,
        "size": 4.0,
        "cost": 2.60,
        "fees": 0.0,
        "reason": "Edge=12%, Confidence=80%",
        "executed_at": datetime.utcnow() - timedelta(days=1),
        "pnl": 0.80,  # Resolved as winner
        "resolved": True,
        "won": True,
    },
]

# Sample positions
SAMPLE_POSITIONS = [
    {
        "market_id": "btc_100k",
        "token_id": "btc_yes",
        "market_question": "Will Bitcoin reach $100,000 by end of 2024?",
        "outcome": "Yes",
        "size": 10.0,
        "avg_entry_price": 0.35,
        "cost_basis": 3.50,
        "current_price": 0.40,
        "market_value": 4.00,
        "unrealized_pnl": 0.50,
        "unrealized_pnl_pct": 0.143,
        "resolved": False,
    },
    {
        "market_id": "fed_rates",
        "token_id": "fed_no",
        "market_question": "Will the Fed raise interest rates in Q1 2024?",
        "outcome": "No",
        "size": 5.0,
        "avg_entry_price": 0.75,
        "cost_basis": 3.75,
        "current_price": 0.70,
        "market_value": 3.50,
        "unrealized_pnl": -0.25,
        "unrealized_pnl_pct": -0.067,
        "resolved": False,
    },
]

# Performance stats for backtesting
SAMPLE_DAILY_RETURNS = [
    0.02,   # +2% day
    -0.01,  # -1% day
    0.03,   # +3% day
    0.01,   # +1% day
    -0.02,  # -2% day
    0.04,   # +4% day
    0.00,   # flat day
    0.02,   # +2% day
    -0.03,  # -3% day
    0.05,   # +5% day
]

# Historical price data for backtesting
SAMPLE_PRICE_HISTORY = [
    {"timestamp": datetime.utcnow() - timedelta(days=10), "price": 0.40, "volume": 5000},
    {"timestamp": datetime.utcnow() - timedelta(days=9), "price": 0.42, "volume": 6000},
    {"timestamp": datetime.utcnow() - timedelta(days=8), "price": 0.41, "volume": 4500},
    {"timestamp": datetime.utcnow() - timedelta(days=7), "price": 0.45, "volume": 8000},
    {"timestamp": datetime.utcnow() - timedelta(days=6), "price": 0.48, "volume": 10000},
    {"timestamp": datetime.utcnow() - timedelta(days=5), "price": 0.46, "volume": 7000},
    {"timestamp": datetime.utcnow() - timedelta(days=4), "price": 0.50, "volume": 12000},
    {"timestamp": datetime.utcnow() - timedelta(days=3), "price": 0.52, "volume": 15000},
    {"timestamp": datetime.utcnow() - timedelta(days=2), "price": 0.55, "volume": 18000},
    {"timestamp": datetime.utcnow() - timedelta(days=1), "price": 0.53, "volume": 14000},
    {"timestamp": datetime.utcnow(), "price": 0.58, "volume": 20000},
]
