"""
Sample market data for testing.

These fixtures provide realistic market data that can be used
across multiple tests for consistency.
"""

from datetime import datetime, timedelta

# Sample markets covering different scenarios
SAMPLE_MARKETS = [
    {
        "conditionId": "btc_100k",
        "question": "Will Bitcoin reach $100,000 by end of 2024?",
        "description": "Resolves YES if BTC/USD reaches $100,000 on any major exchange.",
        "category": "Crypto",
        "outcomes": ["Yes", "No"],
        "outcomePrices": ["0.35", "0.65"],
        "clobTokenIds": ["btc_yes", "btc_no"],
        "endDate": (datetime.utcnow() + timedelta(days=30)).isoformat(),
        "active": True,
        "liquidity": 50000,
        "volume": 250000,
        "volume24hr": 15000,
        "negRisk": False,
    },
    {
        "conditionId": "fed_rates",
        "question": "Will the Fed raise interest rates in Q1 2024?",
        "description": "Resolves YES if the Federal Reserve raises the target rate.",
        "category": "Economics",
        "outcomes": ["Yes", "No"],
        "outcomePrices": ["0.25", "0.75"],
        "clobTokenIds": ["fed_yes", "fed_no"],
        "endDate": (datetime.utcnow() + timedelta(days=60)).isoformat(),
        "active": True,
        "liquidity": 30000,
        "volume": 150000,
        "volume24hr": 8000,
        "negRisk": False,
    },
    {
        "conditionId": "spacex_starship",
        "question": "Will SpaceX successfully land Starship by March 2024?",
        "description": "Resolves YES if Starship completes a successful landing.",
        "category": "Science",
        "outcomes": ["Yes", "No"],
        "outcomePrices": ["0.72", "0.28"],
        "clobTokenIds": ["spacex_yes", "spacex_no"],
        "endDate": (datetime.utcnow() + timedelta(days=14)).isoformat(),
        "active": True,
        "liquidity": 25000,
        "volume": 120000,
        "volume24hr": 5000,
        "negRisk": False,
    },
    {
        "conditionId": "low_liquidity",
        "question": "Will this low liquidity market work?",
        "description": "A market with very low liquidity for testing filters.",
        "category": "Test",
        "outcomes": ["Yes", "No"],
        "outcomePrices": ["0.50", "0.50"],
        "clobTokenIds": ["low_yes", "low_no"],
        "endDate": (datetime.utcnow() + timedelta(days=7)).isoformat(),
        "active": True,
        "liquidity": 100,  # Very low - should be filtered out
        "volume": 500,
        "volume24hr": 50,
        "negRisk": False,
    },
    {
        "conditionId": "expiring_soon",
        "question": "This market expires in 2 hours",
        "description": "A market that's about to expire for testing time filters.",
        "category": "Test",
        "outcomes": ["Yes", "No"],
        "outcomePrices": ["0.80", "0.20"],
        "clobTokenIds": ["exp_yes", "exp_no"],
        "endDate": (datetime.utcnow() + timedelta(hours=2)).isoformat(),
        "active": True,
        "liquidity": 10000,
        "volume": 50000,
        "volume24hr": 2000,
        "negRisk": False,
    },
]

# Sample NegRisk event (multi-outcome) for arbitrage testing
SAMPLE_NEG_RISK_EVENT = {
    "event_id": "election_2024",
    "event_title": "Who will win the 2024 Presidential Election?",
    "markets": [
        {
            "conditionId": "candidate_biden",
            "question": "Will Biden win the 2024 election?",
            "outcomePrices": ["0.28", "0.72"],
            "clobTokenIds": ["biden_yes", "biden_no"],
            "negRisk": True,
            "eventSlug": "election_2024",
        },
        {
            "conditionId": "candidate_trump",
            "question": "Will Trump win the 2024 election?",
            "outcomePrices": ["0.42", "0.58"],
            "clobTokenIds": ["trump_yes", "trump_no"],
            "negRisk": True,
            "eventSlug": "election_2024",
        },
        {
            "conditionId": "candidate_other",
            "question": "Will someone else win the 2024 election?",
            "outcomePrices": ["0.15", "0.85"],
            "clobTokenIds": ["other_yes", "other_no"],
            "negRisk": True,
            "eventSlug": "election_2024",
        },
    ],
    # Total YES prices: 0.28 + 0.42 + 0.15 = 0.85 < 1.0
    # This creates an arbitrage opportunity!
}

# Sample arbitrage-free NegRisk event
SAMPLE_NEG_RISK_NO_ARB = {
    "event_id": "sports_winner",
    "event_title": "Who will win the championship?",
    "markets": [
        {
            "conditionId": "team_a",
            "question": "Will Team A win?",
            "outcomePrices": ["0.45", "0.55"],
            "negRisk": True,
            "eventSlug": "sports_winner",
        },
        {
            "conditionId": "team_b",
            "question": "Will Team B win?",
            "outcomePrices": ["0.40", "0.60"],
            "negRisk": True,
            "eventSlug": "sports_winner",
        },
        {
            "conditionId": "team_c",
            "question": "Will Team C win?",
            "outcomePrices": ["0.20", "0.80"],
            "negRisk": True,
            "eventSlug": "sports_winner",
        },
    ],
    # Total YES prices: 0.45 + 0.40 + 0.20 = 1.05 > 1.0
    # No arbitrage opportunity
}
