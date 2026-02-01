# Trading Strategies Guide

This guide explains the trading strategies available in the agent.

## 1. Edge-Based Strategy (Primary)

The main strategy uses AI to find mispricings.

### How It Works

1. **Screen markets** with GPT-4o-mini (fast, cheap)
2. **Deep analyze** promising ones with Claude (accurate)
3. **Calculate edge**: Our probability - Market price
4. **Size position** using Kelly Criterion
5. **Execute** if risk checks pass

### When to Use

- Default strategy for most markets
- Works best with 5-60 day resolution
- Requires LLM budget

## 2. Arbitrage Strategy

Risk-free profits from NegRisk multi-outcome markets.

### How It Works

In NegRisk events (like "Who will win?"), if the sum of all
YES prices is less than $1.00, you can:

1. Buy YES on ALL outcomes
2. One MUST win, paying $1.00
3. Profit = $1.00 - sum(prices)

### Example

```
Candidate A: 30% ($0.30)
Candidate B: 40% ($0.40)
Candidate C: 20% ($0.20)
Total: $0.90

Buy all three = $0.90
Guaranteed return = $1.00
Profit = $0.10 (11.1%)
```

### When to Use

- Always check first (risk-free!)
- No LLM budget required
- Rare but valuable

## 3. Momentum Strategy

Follow strong price trends.

### How It Works

1. Detect markets with consistent price movement
2. Calculate momentum strength
3. Enter in direction of trend
4. Exit when momentum fades

### When to Use

- During news events
- High volume markets
- Short-term trades

## 4. Mean Reversion Strategy

Bet against overreactions.

### How It Works

1. Detect price spikes (sudden moves)
2. Calculate deviation from historical mean
3. Bet on price returning to normal
4. Take profit at mean

### When to Use

- After news-driven spikes
- Low volume overreactions
- **Caution**: Verify it's not real information!

## 5. Sentiment Strategy

Trade on news sentiment.

### How It Works

1. Fetch recent news for a market
2. Analyze sentiment (positive/negative)
3. Compare sentiment to current price
4. Trade the gap

### When to Use

- News-driven markets
- When news sentiment differs from price
- Supplement to edge strategy

## Strategy Combinations

The agent combines strategies:

```
1. Check arbitrage (free money first!)
2. Run edge strategy on candidates
3. Use momentum/sentiment as confirmation
4. Apply risk checks to all trades
```

## Custom Strategies

You can add custom strategies:

```python
# strategy/custom.py

class MyStrategy:
    def analyze(self, market) -> Optional[Signal]:
        # Your logic here
        return signal
```

Then integrate in `main.py`.
