"""
Report generation for trading performance.
"""

from datetime import datetime
from typing import Optional
from pathlib import Path
import json

from data.db import Database
from analytics.performance.metrics import PerformanceMetrics
from analytics.performance.tracker import PerformanceTracker


class ReportGenerator:
    """
    Generates comprehensive trading reports.
    """

    def __init__(self, db: Database, output_dir: Optional[Path] = None):
        self.db = db
        self.output_dir = output_dir or Path("reports")
        self.output_dir.mkdir(exist_ok=True)

    def generate_daily_report(self) -> str:
        """Generate daily trading report."""
        stats = self.db.get_today_stats()
        positions = self.db.get_open_positions()
        trades = self.db.get_recent_trades(limit=20)
        budget = self.db.get_llm_budget()

        report = []
        report.append("=" * 60)
        report.append(f"DAILY TRADING REPORT - {datetime.now().strftime('%Y-%m-%d')}")
        report.append("=" * 60)
        report.append("")

        # P&L Summary
        report.append("P&L SUMMARY")
        report.append("-" * 40)
        report.append(f"Realized P&L:   ${stats.realized_pnl:+.2f}")
        report.append(f"Unrealized P&L: ${stats.unrealized_pnl:+.2f}")
        report.append(f"Total P&L:      ${stats.total_pnl:+.2f}")
        report.append("")

        # Trading Activity
        report.append("TRADING ACTIVITY")
        report.append("-" * 40)
        report.append(f"Trades Today: {stats.trades_count}")
        report.append(f"Wins/Losses:  {stats.wins}W / {stats.losses}L")
        win_rate = stats.wins / stats.trades_count * 100 if stats.trades_count > 0 else 0
        report.append(f"Win Rate:     {win_rate:.1f}%")
        report.append("")

        # Open Positions
        report.append("OPEN POSITIONS")
        report.append("-" * 40)
        if positions:
            for pos in positions:
                report.append(
                    f"  {pos.outcome}: {pos.market_question[:40]}..."
                )
                report.append(
                    f"    Size: {pos.size:.2f} @ ${pos.avg_entry_price:.3f} | "
                    f"P&L: ${pos.unrealized_pnl:+.2f}"
                )
        else:
            report.append("  No open positions")
        report.append("")

        # LLM Usage
        report.append("LLM USAGE")
        report.append("-" * 40)
        report.append(f"Claude Calls: {stats.claude_calls} (${stats.claude_cost:.3f})")
        report.append(f"GPT Calls:    {stats.gpt_calls} (${stats.gpt_cost:.3f})")
        report.append(f"Budget Remaining: ${budget.total_remaining:.2f}")
        report.append("")

        # Recent Trades
        report.append("RECENT TRADES")
        report.append("-" * 40)
        for trade in trades[:5]:
            report.append(
                f"  {trade.executed_at.strftime('%H:%M')} | "
                f"{trade.side.value} | ${trade.price:.3f} x {trade.size:.2f}"
            )
        report.append("")

        report.append("=" * 60)

        return "\n".join(report)

    def generate_weekly_report(self) -> str:
        """Generate weekly summary report."""
        # Would aggregate daily stats
        return "Weekly report - coming soon"

    def generate_html_report(self) -> str:
        """Generate HTML formatted report."""
        stats = self.db.get_today_stats()
        positions = self.db.get_open_positions()

        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Trading Report - {datetime.now().strftime('%Y-%m-%d')}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        h1 {{ color: #2c3e50; }}
        .metric {{ display: inline-block; margin: 10px; padding: 15px;
                   background: #f8f9fa; border-radius: 5px; }}
        .positive {{ color: #27ae60; }}
        .negative {{ color: #e74c3c; }}
        table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #3498db; color: white; }}
    </style>
</head>
<body>
    <h1>Polymarket Trading Report</h1>
    <p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>

    <h2>Today's Performance</h2>
    <div class="metric">
        <strong>Total P&L</strong><br>
        <span class="{'positive' if stats.total_pnl >= 0 else 'negative'}">
            ${stats.total_pnl:+.2f}
        </span>
    </div>
    <div class="metric">
        <strong>Trades</strong><br>
        {stats.trades_count}
    </div>
    <div class="metric">
        <strong>Win Rate</strong><br>
        {stats.wins / stats.trades_count * 100 if stats.trades_count > 0 else 0:.1f}%
    </div>

    <h2>Open Positions</h2>
    <table>
        <tr>
            <th>Market</th>
            <th>Side</th>
            <th>Size</th>
            <th>Entry</th>
            <th>Current</th>
            <th>P&L</th>
        </tr>
"""

        for pos in positions:
            pnl_class = "positive" if pos.unrealized_pnl >= 0 else "negative"
            html += f"""
        <tr>
            <td>{pos.market_question[:50]}...</td>
            <td>{pos.outcome}</td>
            <td>{pos.size:.2f}</td>
            <td>${pos.avg_entry_price:.3f}</td>
            <td>${pos.current_price:.3f}</td>
            <td class="{pnl_class}">${pos.unrealized_pnl:+.2f}</td>
        </tr>
"""

        html += """
    </table>
</body>
</html>
"""
        return html

    def save_report(self, report: str, filename: str):
        """Save report to file."""
        filepath = self.output_dir / filename
        with open(filepath, "w") as f:
            f.write(report)
        return filepath

    def export_trades_csv(self) -> Path:
        """Export all trades to CSV."""
        import csv

        trades = self.db.get_recent_trades(limit=10000)
        filepath = self.output_dir / f"trades_{datetime.now().strftime('%Y%m%d')}.csv"

        with open(filepath, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "ID", "Timestamp", "Market", "Side", "Price", "Size", "Cost", "Reason"
            ])
            for trade in trades:
                writer.writerow([
                    trade.id,
                    trade.executed_at.isoformat(),
                    trade.market_id,
                    trade.side.value,
                    trade.price,
                    trade.size,
                    trade.cost,
                    trade.reason,
                ])

        return filepath

    def export_metrics_json(self, metrics: PerformanceMetrics) -> Path:
        """Export metrics to JSON."""
        filepath = self.output_dir / f"metrics_{datetime.now().strftime('%Y%m%d')}.json"

        with open(filepath, "w") as f:
            json.dump(metrics.to_dict(), f, indent=2)

        return filepath
