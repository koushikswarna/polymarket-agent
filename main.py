#!/usr/bin/env python3
"""
Polymarket AI Trading Agent - Main Entry Point

Autonomous trading loop that:
1. Scans markets for opportunities
2. Checks arbitrage opportunities first (risk-free)
3. Uses AI for probability estimation on candidates
4. Calculates edge and sizes positions with Kelly
5. Executes trades that pass risk checks
6. Manages existing positions
"""

import argparse
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from config import settings
from data.db import Database
from data.models import Side
from core.client import PolymarketClient
from core.market_scanner import MarketScanner
from core.order_manager import OrderManager
from core.portfolio import PortfolioManager
from strategy.probability_engine import ProbabilityEngine
from strategy.edge_detector import EdgeDetector
from strategy.kelly import KellyCriterion
from strategy.arbitrage import ArbitrageDetector
from risk.risk_manager import RiskManager
from risk.guardrails import Guardrails, DailyLossCircuitBreaker
from utils.logger import setup_logger, TradingLogger

console = Console()


class TradingAgent:
    """
    Main trading agent orchestrating all components.
    """

    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run
        self.running = False

        # Override settings if specified
        if dry_run:
            settings.trading.dry_run = True

        # Set up logging
        log_file = Path(settings.data_dir) / settings.logging.log_file
        self.logger = setup_logger(
            name="polymarket",
            level=settings.logging.log_level,
            log_file=log_file,
        )
        self.trade_logger = TradingLogger()

        # Initialize database
        self.db = Database(settings.db_path)

        # Initialize components
        self.client = PolymarketClient()
        self.scanner = MarketScanner(self.client)
        self.order_manager = OrderManager(self.client, self.db)
        self.portfolio = PortfolioManager(self.client, self.db)
        self.probability_engine = ProbabilityEngine(self.db)
        self.edge_detector = EdgeDetector()
        self.kelly = KellyCriterion()
        self.arbitrage = ArbitrageDetector(self.client)
        self.risk_manager = RiskManager(self.db)
        self.guardrails = Guardrails(self.db)
        self.daily_loss_breaker = DailyLossCircuitBreaker(self.db)

        # Stats
        self.loop_count = 0
        self.trades_executed = 0
        self.arbs_executed = 0

    def startup_checks(self) -> bool:
        """
        Run startup validation checks.
        """
        console.print(Panel.fit(
            "[bold blue]Polymarket AI Trading Agent[/bold blue]\n"
            f"Mode: {'[yellow]DRY RUN[/yellow]' if self.dry_run else '[red]LIVE[/red]'}\n"
            f"Starting Capital: ${settings.trading.starting_capital}\n"
            f"LLM Budget: ${settings.llm.anthropic_budget + settings.llm.openai_budget}",
            title="Startup"
        ))

        # Validate settings
        missing = settings.validate()
        if missing:
            console.print(f"[red]Missing configuration: {', '.join(missing)}[/red]")
            console.print("Please set the required environment variables or create a .env file.")
            return False

        # Health check APIs
        console.print("Checking API connectivity...")
        health = self.client.health_check()

        if not health["gamma_api"]:
            console.print("[red]Cannot connect to Gamma API[/red]")
            return False

        if not self.dry_run and not health["authenticated"]:
            console.print("[red]CLOB API authentication failed[/red]")
            return False

        console.print("[green]API connectivity OK[/green]")

        # Check budget
        budget_status = self.probability_engine.get_budget_status()
        if budget_status["all_exhausted"]:
            console.print("[yellow]Warning: LLM budget exhausted - arbitrage only mode[/yellow]")

        console.print(
            f"LLM Budget: Anthropic ${budget_status['anthropic']['remaining']:.2f} / "
            f"OpenAI ${budget_status['openai']['remaining']:.2f}"
        )

        return True

    def check_arbitrage(self) -> int:
        """
        Scan for and execute arbitrage opportunities.
        Returns number of arbs executed.
        """
        self.logger.info("Scanning for arbitrage opportunities...")

        # Get NegRisk events
        neg_risk_events = self.scanner.get_neg_risk_events()

        if not neg_risk_events:
            return 0

        # Scan for arbs
        opportunities = self.arbitrage.scan_all_events(
            neg_risk_events,
            bet_size=1.0,  # $1 per leg
        )

        executed = 0

        for opp in opportunities:
            # Check if profit is worth it
            if opp.profit < 0.01:  # < $0.01 profit
                continue

            # Check risk
            risk_summary = self.risk_manager.get_risk_summary()
            if not risk_summary["can_trade"]:
                self.logger.warning("Risk check prevents arbitrage execution")
                break

            # Check execution quality
            exec_quality = self.arbitrage.estimate_execution_quality(opp)
            if not exec_quality["can_fill"]:
                self.logger.info(f"Insufficient depth for arb on {opp.event_title}")
                continue

            self.trade_logger.arbitrage_detected(
                event=opp.event_title,
                profit_pct=opp.profit_pct,
                cost=opp.total_cost,
            )

            if not self.dry_run:
                # Execute arbitrage
                orders = self.arbitrage.prepare_arb_orders(opp)
                results = self.order_manager.place_arb_orders(orders)

                if results:
                    executed += 1
                    self.arbs_executed += 1
            else:
                self.logger.info(f"[DRY RUN] Would execute arb: {opp.profit_pct:.2%} profit")
                executed += 1

        return executed

    def analyze_and_trade(self, max_markets: int = 10) -> int:
        """
        Main AI analysis and trading logic.
        Returns number of trades executed.
        """
        # Check if we can trade
        can_trade, reason = self.guardrails.can_trade()
        if not can_trade:
            self.logger.info(f"Trading paused: {reason}")
            return 0

        # Check daily loss limit
        loss_ok, loss_reason = self.daily_loss_breaker.check()
        if not loss_ok:
            self.logger.warning(loss_reason)
            return 0

        # Check budget
        budget_status = self.probability_engine.get_budget_status()
        if budget_status["all_exhausted"]:
            self.logger.info("LLM budget exhausted - skipping AI analysis")
            return 0

        # Get tradeable markets
        markets = self.scanner.get_tradeable_markets(limit=max_markets * 2)

        if not markets:
            self.logger.info("No tradeable markets found")
            return 0

        # Filter out markets we already have positions in
        markets = [
            m for m in markets
            if not self.portfolio.has_position(m.id)
        ][:max_markets]

        self.logger.info(f"Analyzing {len(markets)} candidate markets...")

        # Batch screen with GPT
        promising = self.probability_engine.batch_screen(markets, max_screens=max_markets)

        trades_executed = 0

        for market, screening in promising:
            # Deep analysis with Claude
            estimate = self.probability_engine.deep_analyze(market, screening)

            if not estimate:
                continue

            # Calculate edge
            edge_opp = self.edge_detector.calculate_edge(market, estimate)

            if not edge_opp.tradeable:
                self.logger.debug(
                    f"No tradeable edge in '{market.question[:30]}...': "
                    f"edge={edge_opp.edge_abs:.1%}"
                )
                continue

            self.trade_logger.edge_detected(
                market=market.question,
                our_prob=estimate.probability,
                market_price=estimate.market_price,
                edge=edge_opp.edge,
            )

            # Calculate position size with Kelly
            bankroll = self.risk_manager.get_available_capital()
            kelly_result = self.kelly.size_trade(
                estimated_prob=estimate.probability,
                market_price=edge_opp.entry_price,
                bankroll=bankroll,
                confidence=estimate.confidence,
                buying_yes=(edge_opp.outcome == "Yes"),
            )

            if kelly_result.recommended_bet <= 0:
                self.logger.debug("Kelly sizing returned zero position")
                continue

            # Risk check
            risk_result = self.risk_manager.check_trade(
                market=market,
                proposed_size=kelly_result.recommended_bet,
                edge=edge_opp.edge,
                confidence=estimate.confidence,
            )

            if not risk_result.passed:
                self.trade_logger.risk_blocked("; ".join(risk_result.reasons))
                continue

            # Execute trade
            final_size = risk_result.approved_size

            self.logger.info(
                f"Placing trade: {edge_opp.outcome} on '{market.question[:40]}...' "
                f"@ ${edge_opp.entry_price:.3f} x ${final_size:.2f}"
            )

            # Calculate shares from dollar size
            shares = final_size / edge_opp.entry_price

            order = self.order_manager.place_limit_buy(
                market_id=market.id,
                token_id=edge_opp.token_id,
                price=edge_opp.entry_price,
                size=shares,
                reason=f"Edge={edge_opp.edge_abs:.1%}, Conf={estimate.confidence:.1%}",
            )

            if order:
                # Open position tracking
                self.portfolio.open_position(
                    market=market,
                    token_id=edge_opp.token_id,
                    outcome=edge_opp.outcome,
                    size=shares,
                    entry_price=edge_opp.entry_price,
                )

                self.guardrails.record_trade_attempt()
                trades_executed += 1
                self.trades_executed += 1

            # Rate limit between trades
            time.sleep(1)

        return trades_executed

    def manage_positions(self):
        """
        Manage existing positions.
        """
        # Refresh position prices
        self.portfolio.refresh_all_positions()

        # Check for resolutions
        self.portfolio.check_resolutions()

        # Update daily stats
        summary = self.portfolio.get_position_summary()
        daily_stats = self.db.get_today_stats()
        daily_stats.unrealized_pnl = summary["unrealized_pnl"]
        daily_stats.total_pnl = summary["total_pnl"]
        self.db.save_daily_stats(daily_stats)

    def run_loop(self):
        """
        Main trading loop iteration.
        """
        self.loop_count += 1
        self.logger.info(f"=== Trading Loop #{self.loop_count} ===")

        try:
            # 1. Check arbitrage first (risk-free)
            arbs = self.check_arbitrage()
            if arbs:
                self.logger.info(f"Executed {arbs} arbitrage trades")

            # 2. AI analysis and trading
            trades = self.analyze_and_trade()
            if trades:
                self.logger.info(f"Executed {trades} AI-driven trades")

            # 3. Manage existing positions
            self.manage_positions()

            # 4. Log summary
            summary = self.portfolio.get_position_summary()
            budget = self.probability_engine.get_budget_status()

            self.logger.info(
                f"Loop complete | Positions: {summary['open_positions']} | "
                f"Unrealized P&L: ${summary['unrealized_pnl']:+.2f} | "
                f"LLM Budget: ${budget['total_remaining']:.2f}"
            )

        except Exception as e:
            self.logger.error(f"Error in trading loop: {e}", exc_info=True)

    def run(self, single_loop: bool = False):
        """
        Run the trading agent.

        Args:
            single_loop: If True, run once and exit. Otherwise, run continuously.
        """
        if not self.startup_checks():
            return

        self.running = True

        # Set up signal handlers
        def signal_handler(sig, frame):
            console.print("\n[yellow]Shutting down...[/yellow]")
            self.running = False

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        console.print("[green]Starting trading loop...[/green]")

        try:
            while self.running:
                self.run_loop()

                if single_loop:
                    break

                # Sleep until next iteration
                sleep_time = settings.intervals.market_scan_interval
                self.logger.info(f"Sleeping for {sleep_time}s until next scan...")

                # Sleep in chunks to allow for interruption
                for _ in range(sleep_time):
                    if not self.running:
                        break
                    time.sleep(1)

        except KeyboardInterrupt:
            pass

        # Shutdown
        self.logger.info("Trading agent stopped")
        self.print_session_summary()

    def print_session_summary(self):
        """Print session summary on shutdown."""
        summary = self.portfolio.get_position_summary()
        budget = self.probability_engine.get_budget_status()

        console.print(Panel.fit(
            f"[bold]Session Summary[/bold]\n\n"
            f"Loops: {self.loop_count}\n"
            f"Trades Executed: {self.trades_executed}\n"
            f"Arbs Executed: {self.arbs_executed}\n\n"
            f"Open Positions: {summary['open_positions']}\n"
            f"Unrealized P&L: ${summary['unrealized_pnl']:+.2f}\n"
            f"Realized P&L: ${summary['realized_pnl']:+.2f}\n"
            f"Total P&L: ${summary['total_pnl']:+.2f}\n\n"
            f"LLM Spend: ${budget['anthropic']['spent'] + budget['openai']['spent']:.2f}\n"
            f"LLM Remaining: ${budget['total_remaining']:.2f}",
            title="Shutdown"
        ))


def main():
    parser = argparse.ArgumentParser(
        description="Polymarket AI Trading Agent"
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run in live trading mode (default: dry run)"
    )
    parser.add_argument(
        "--single",
        action="store_true",
        help="Run single loop and exit"
    )
    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="Launch dashboard instead of trading loop"
    )

    args = parser.parse_args()

    if args.dashboard:
        # Import and run dashboard
        from dashboard import run_dashboard
        run_dashboard()
    else:
        # Run trading agent
        agent = TradingAgent(dry_run=not args.live)
        agent.run(single_loop=args.single)


if __name__ == "__main__":
    main()
