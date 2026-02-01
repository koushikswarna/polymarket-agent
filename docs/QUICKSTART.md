# Quickstart Guide

Get the Polymarket AI Trading Agent running in 5 minutes.

## Prerequisites

- Python 3.10+
- Polymarket account with API access
- Anthropic and OpenAI API keys
- Some USDC on Polygon network

## Installation

```bash
# Clone the repository
git clone https://github.com/koushikswarna/polymarket-agent.git
cd polymarket-agent

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

## Configuration

1. Copy the example environment file:
```bash
cp config/.env.example config/.env
```

2. Edit `config/.env` with your API keys:
```bash
POLYMARKET_API_KEY=your_key
POLYMARKET_API_SECRET=your_secret
POLYMARKET_API_PASSPHRASE=your_passphrase
PRIVATE_KEY=your_ethereum_private_key

ANTHROPIC_API_KEY=your_anthropic_key
OPENAI_API_KEY=your_openai_key

DRY_RUN=true  # Start with dry run!
```

## First Run (Dry Run Mode)

Always start with dry run mode to test without risking real money:

```bash
# Run a single iteration
python main.py --single

# Run continuous loop
python main.py

# View the dashboard
python main.py --dashboard
```

## Understanding the Output

The agent will:
1. Scan Polymarket for tradeable markets
2. Check for arbitrage opportunities
3. Analyze promising markets with AI
4. Calculate edge and position sizes
5. Execute trades (simulated in dry run)

## Going Live

**WARNING: Only go live with money you can afford to lose!**

When you're confident the system works:

```bash
python main.py --live
```

## Monitoring

- Check the dashboard for real-time status
- Review `trading.log` for detailed logs
- Run `python scripts/health_check.py` for system status

## Need Help?

- Check the [full documentation](./README.md)
- Review the [API reference](./api/README.md)
- Open an issue on GitHub
