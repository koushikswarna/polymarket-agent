# API Reference

This document describes the internal APIs and modules of the Polymarket Trading Agent.

## Core Modules

### `core.client.PolymarketClient`

Main interface to Polymarket APIs.

```python
from core.client import PolymarketClient

client = PolymarketClient()

# Fetch markets
markets = client.get_all_markets()

# Get order book
book = client.get_order_book(token_id)

# Place order
order = client.place_order(token_id, side, price, size)
```

### `strategy.probability_engine.ProbabilityEngine`

AI-powered probability estimation.

```python
from strategy.probability_engine import ProbabilityEngine

engine = ProbabilityEngine(db)

# Analyze a market
estimate = engine.analyze_market(market)
print(f"Probability: {estimate.probability}")
print(f"Edge: {estimate.edge}")
```

### `strategy.kelly.KellyCriterion`

Position sizing using Kelly Criterion.

```python
from strategy.kelly import KellyCriterion

kelly = KellyCriterion(kelly_fraction=0.25)

result = kelly.size_trade(
    estimated_prob=0.65,
    market_price=0.50,
    bankroll=10.0,
    confidence=0.8
)
print(f"Recommended bet: ${result.recommended_bet}")
```

### `risk.risk_manager.RiskManager`

Pre-trade risk checks.

```python
from risk.risk_manager import RiskManager

rm = RiskManager(db)

result = rm.check_trade(market, size, edge, confidence)
if result.passed:
    # Safe to trade
    pass
```

## Data Models

See `data/models.py` for all Pydantic models:

- `Market` - Prediction market
- `Token` - Tradeable outcome token
- `Order` - Order on the CLOB
- `Trade` - Executed trade
- `Position` - Open position
- `ProbabilityEstimate` - AI estimate

## Configuration

All settings in `config/settings.py`:

```python
from config import settings

# Trading settings
settings.trading.dry_run  # True/False
settings.trading.max_position_size  # $3.00

# Risk settings
settings.risk.min_edge_threshold  # 5%
settings.risk.daily_loss_limit  # $3.00
```
