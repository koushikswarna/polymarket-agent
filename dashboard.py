#!/usr/bin/env python3
"""
Rich terminal dashboard for monitoring the trading agent.
"""

import time
from datetime import datetime

from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.live import Live
from rich.text import Text

from config import settings
from data.db import Database
from core.client import PolymarketClient
from core.portfolio import PortfolioManager
from strategy.probability_engine import ProbabilityEngine

console = Console()


class Dashboard:
    """
    Terminal dashboard for real-time monitoring.
    """

    def __init__(self):
        self.db = Database(settings.db_path)
        self.client = PolymarketClient()
        self.portfolio = PortfolioManager(self.client, self.db)
        self.probability_engine = ProbabilityEngine(self.db)

    def make_layout(self) -> Layout:
        """Create the dashboard layout."""
        layout = Layout()

        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="main", ratio=1),
            Layout(name="footer", size=3),
        )

        layout["main"].split_row(
            Layout(name="left", ratio=1),
            Layout(name="right", ratio=2),
        )

        layout["left"].split_column(
            Layout(name="balance", size=10),
            Layout(name="risk", ratio=1),
        )

        layout["right"].split_column(
            Layout(name="positions", ratio=2),
            Layout(name="trades", ratio=1),
        )

        return layout

    def make_header(self) -> Panel:
        """Create header panel."""
        mode = "[yellow]DRY RUN[/yellow]" if settings.trading.dry_run else "[red]LIVE[/red]"
        return Panel(
            Text.from_markup(
                f"[bold blue]Polymarket AI Trading Agent[/bold blue] | "
                f"Mode: {mode} | "
                f"Time: {datetime.now().strftime('%H:%M:%S')}"
            ),
            style="white on dark_blue",
        )

    def make_balance_panel(self) -> Panel:
        """Create balance panel."""
        summary = self.portfolio.get_balance_summary()

        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("Label", style="dim")
        table.add_column("Value", justify="right")

        table.add_row("USDC Balance", f"${summary['usdc_balance']:.2f}")
        table.add_row("Position Value", f"${summary['position_value']:.2f}")
        table.add_row("─" * 15, "─" * 10)
        table.add_row("[bold]Total Value[/bold]", f"[bold]${summary['total_value']:.2f}[/bold]")
        table.add_row("", "")

        # P&L
        unrealized = summary['unrealized_pnl']
        realized = summary['realized_pnl']
        total_pnl = unrealized + realized

        pnl_style = "green" if total_pnl >= 0 else "red"
        table.add_row("Unrealized P&L", f"[{pnl_style}]${unrealized:+.2f}[/{pnl_style}]")
        table.add_row("Realized P&L", f"[{pnl_style}]${realized:+.2f}[/{pnl_style}]")
        table.add_row("[bold]Total P&L[/bold]", f"[bold {pnl_style}]${total_pnl:+.2f}[/bold {pnl_style}]")

        return Panel(table, title="[bold]Balance[/bold]", border_style="green")

    def make_risk_panel(self) -> Panel:
        """Create risk status panel."""
        from risk.risk_manager import RiskManager
        from risk.guardrails import Guardrails

        risk_manager = RiskManager(self.db)
        guardrails = Guardrails(self.db)

        risk_summary = risk_manager.get_risk_summary()
        guard_status = guardrails.get_status()

        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("Label", style="dim")
        table.add_column("Value", justify="right")

        # Risk limits
        exposure_pct = risk_summary['exposure_pct'] * 100
        exposure_style = "green" if exposure_pct < 70 else "yellow" if exposure_pct < 90 else "red"
        table.add_row(
            "Exposure",
            f"[{exposure_style}]${risk_summary['current_exposure']:.2f} / ${risk_summary['max_exposure']:.2f}[/{exposure_style}]"
        )

        table.add_row(
            "Positions",
            f"{risk_summary['open_positions']} / {risk_summary['max_positions']}"
        )

        loss_remaining = risk_summary['daily_loss_remaining']
        loss_style = "green" if loss_remaining > 1.5 else "yellow" if loss_remaining > 0.5 else "red"
        table.add_row(
            "Daily Loss Buffer",
            f"[{loss_style}]${loss_remaining:.2f}[/{loss_style}]"
        )

        table.add_row("", "")

        # Guardrails
        if guard_status['can_trade']:
            table.add_row("Status", "[green]Active[/green]")
        else:
            table.add_row("Status", f"[red]Paused: {guard_status['reason']}[/red]")

        table.add_row(
            "Consecutive Losses",
            f"{guard_status['consecutive_losses']} / {guard_status['max_consecutive_losses']}"
        )

        # LLM Budget
        budget = self.probability_engine.get_budget_status()
        budget_style = "green" if budget['total_remaining'] > 3 else "yellow" if budget['total_remaining'] > 1 else "red"
        table.add_row(
            "LLM Budget",
            f"[{budget_style}]${budget['total_remaining']:.2f}[/{budget_style}]"
        )

        return Panel(table, title="[bold]Risk & Budget[/bold]", border_style="blue")

    def make_positions_panel(self) -> Panel:
        """Create positions table panel."""
        positions = self.portfolio.export_positions_table()

        if not positions:
            return Panel(
                "[dim]No open positions[/dim]",
                title="[bold]Open Positions[/bold]",
                border_style="cyan"
            )

        table = Table(show_header=True, header_style="bold", box=None)
        table.add_column("Market", max_width=35)
        table.add_column("Side", justify="center")
        table.add_column("Size", justify="right")
        table.add_column("Entry", justify="right")
        table.add_column("Current", justify="right")
        table.add_column("P&L", justify="right")
        table.add_column("P&L %", justify="right")

        for pos in positions[:10]:  # Limit to 10 rows
            pnl = float(pos["P&L"].replace("$", "").replace("+", ""))
            pnl_style = "green" if pnl >= 0 else "red"

            table.add_row(
                pos["Market"],
                pos["Outcome"],
                pos["Size"],
                pos["Entry"],
                pos["Current"],
                f"[{pnl_style}]{pos['P&L']}[/{pnl_style}]",
                f"[{pnl_style}]{pos['P&L %']}[/{pnl_style}]",
            )

        return Panel(table, title="[bold]Open Positions[/bold]", border_style="cyan")

    def make_trades_panel(self) -> Panel:
        """Create recent trades panel."""
        trades = self.db.get_recent_trades(limit=5)

        if not trades:
            return Panel(
                "[dim]No recent trades[/dim]",
                title="[bold]Recent Trades[/bold]",
                border_style="magenta"
            )

        table = Table(show_header=True, header_style="bold", box=None)
        table.add_column("Time", max_width=10)
        table.add_column("Side", justify="center")
        table.add_column("Price", justify="right")
        table.add_column("Size", justify="right")
        table.add_column("Cost", justify="right")

        for trade in trades:
            side_style = "green" if trade.side.value == "BUY" else "red"
            table.add_row(
                trade.executed_at.strftime("%H:%M:%S"),
                f"[{side_style}]{trade.side.value}[/{side_style}]",
                f"${trade.price:.3f}",
                f"{trade.size:.2f}",
                f"${trade.cost:.2f}",
            )

        return Panel(table, title="[bold]Recent Trades[/bold]", border_style="magenta")

    def make_footer(self) -> Panel:
        """Create footer panel."""
        daily_stats = self.db.get_today_stats()

        return Panel(
            f"Today: {daily_stats.trades_count} trades | "
            f"W/L: {daily_stats.wins}/{daily_stats.losses} | "
            f"LLM Calls: Claude={daily_stats.claude_calls} GPT={daily_stats.gpt_calls} | "
            f"Press Ctrl+C to exit",
            style="dim",
        )

    def generate(self) -> Layout:
        """Generate the complete dashboard."""
        layout = self.make_layout()

        layout["header"].update(self.make_header())
        layout["balance"].update(self.make_balance_panel())
        layout["risk"].update(self.make_risk_panel())
        layout["positions"].update(self.make_positions_panel())
        layout["trades"].update(self.make_trades_panel())
        layout["footer"].update(self.make_footer())

        return layout


def run_dashboard(refresh_rate: float = 2.0):
    """
    Run the live dashboard.

    Args:
        refresh_rate: Seconds between refreshes
    """
    dashboard = Dashboard()

    console.print("[bold blue]Starting dashboard...[/bold blue]")
    console.print("Press Ctrl+C to exit\n")

    try:
        with Live(dashboard.generate(), refresh_per_second=1/refresh_rate, screen=True) as live:
            while True:
                time.sleep(refresh_rate)
                live.update(dashboard.generate())
    except KeyboardInterrupt:
        console.print("\n[yellow]Dashboard closed[/yellow]")


if __name__ == "__main__":
    run_dashboard()
