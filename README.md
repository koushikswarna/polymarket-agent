# Polymarket AI Trading Agent

An autonomous trading agent for Polymarket prediction markets that uses AI (Claude + GPT-4o-mini) for probability estimation, detects arbitrage opportunities, and executes trades via the Polymarket CLOB API.

## Features

- **Two-Tier LLM Strategy**: GPT-4o-mini for fast screening (~$0.001/call), Claude for deep analysis (~$0.005/call)
- **Superforecaster Methodology**: Prompts based on Philip Tetlock's research for accurate probability estimation
- **Arbitrage Detection**: Scans NegRisk multi-outcome markets for risk-free arbitrage opportunities
- **Kelly Criterion Sizing**: Quarter-Kelly position sizing with confidence adjustment
- **Risk Management**: Daily loss limits, position limits, circuit breakers, and cooldowns
- **Real-time Dashboard**: Rich terminal UI for monitoring positions and P&L

## Configuration

### Starting Capital
- **$10 USDC** starting capital
- Max $3 per position
- Max $8 total exposure

### LLM Budget
- **$4.50** Anthropic (Claude)
- **$5.00** OpenAI (GPT-4o-mini)
- Auto-fallback to arbitrage-only when budgets exhausted

### Market Selection
- Resolution: 6 hours to 60 days
- Minimum liquidity: $500
- Skip extreme prices (< 3% or > 97%)
- Prioritize 1-14 day resolution for capital turnover

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/polymarket-agent.git
cd polymarket-agent

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment variables
cp config/.env.example config/.env
# Edit config/.env with your API keys
```

## Configuration

Create a `.env` file in the `config/` directory (or project root):

```bash
# Polymarket API Credentials
POLYMARKET_API_KEY=your_api_key
POLYMARKET_API_SECRET=your_api_secret
POLYMARKET_API_PASSPHRASE=your_passphrase
PRIVATE_KEY=your_ethereum_private_key

# LLM API Keys
ANTHROPIC_API_KEY=your_anthropic_key
OPENAI_API_KEY=your_openai_key

# Trading Configuration
DRY_RUN=true  # Set to false for live trading
```

## Usage

### Dry Run Mode (Recommended for Testing)

```bash
# Run single iteration
python main.py --single

# Run continuous loop
python main.py

# Launch dashboard only
python main.py --dashboard
```

### Live Trading (Use with Caution)

```bash
python main.py --live
```

## Project Structure

```
polymarket-agent/
├── config/
│   ├── settings.py              # Configuration management
│   └── .env.example             # Environment template
├── core/
│   ├── client.py                # Polymarket API wrapper
│   ├── market_scanner.py        # Market discovery & filtering
│   ├── order_manager.py         # Order execution & tracking
│   └── portfolio.py             # Position & P&L management
├── strategy/
│   ├── probability_engine.py    # LLM probability estimation
│   ├── news_analyzer.py         # News fetching via RSS
│   ├── edge_detector.py         # Edge calculation
│   ├── kelly.py                 # Kelly Criterion sizing
│   └── arbitrage.py             # NegRisk arbitrage detection
├── risk/
│   ├── risk_manager.py          # Pre-trade risk checks
│   └── guardrails.py            # Circuit breakers
├── data/
│   ├── db.py                    # SQLite persistence
│   └── models.py                # Pydantic data models
├── utils/
│   ├── logger.py                # Structured logging
│   └── helpers.py               # Utilities
├── main.py                      # Main trading loop
├── dashboard.py                 # Terminal dashboard
└── requirements.txt             # Dependencies
```

## How It Works

### Trading Loop

1. **Scan for Arbitrage** (risk-free first)
   - Check NegRisk markets for sum(YES) < 1.0
   - Execute with FOK orders for atomic fills

2. **AI Probability Analysis**
   - Screen markets with GPT-4o-mini
   - Deep analyze promising markets with Claude
   - Use superforecaster methodology

3. **Edge Detection**
   - Compare AI probability vs market price
   - Calculate confidence-adjusted edge

4. **Position Sizing**
   - Quarter-Kelly with confidence discount
   - Cap at risk limits

5. **Risk Checks**
   - Daily loss limit
   - Total exposure limit
   - Position count limit
   - Minimum edge threshold

6. **Execute & Monitor**
   - Place limit orders
   - Track fills
   - Mark-to-market

### LLM Strategy

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   All Markets   │───▶│  GPT-4o-mini    │───▶│    Claude       │
│   (50+ daily)   │    │  Screening      │    │  Deep Analysis  │
└─────────────────┘    │  ~$0.001/call   │    │  ~$0.005/call   │
                       │  80% of calls   │    │  20% of calls   │
                       └─────────────────┘    └─────────────────┘
```

## Risk Controls

| Control | Limit | Action |
|---------|-------|--------|
| Daily Loss | $3.00 | Stop trading |
| Total Exposure | $8.00 | Block new trades |
| Single Position | $3.00 | Cap size |
| Open Positions | 8 | Block new trades |
| Consecutive Losses | 5 | 1-hour cooldown |
| Minimum Edge | 5% | Skip trade |
| Minimum Liquidity | $500 | Skip market |

## Dashboard

The terminal dashboard shows:
- Account balance and P&L
- Open positions with live prices
- Recent trades
- Risk metrics and limits
- LLM budget remaining

```bash
python main.py --dashboard
```

## API Reference

### Polymarket APIs Used

- **Gamma API** (Public): Market data, events, prices
- **CLOB API** (Authenticated): Order book, trading, positions

### Rate Limits

- Public API: 100 requests/minute
- Trading API: 60 orders/minute

## Disclaimer

This software is for educational and research purposes only. Trading prediction markets involves significant risk of loss. Past performance does not guarantee future results. Use at your own risk.

## License

MIT License
