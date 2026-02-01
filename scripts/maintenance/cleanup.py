#!/usr/bin/env python3
"""
Maintenance script for database cleanup and optimization.

This script performs routine maintenance tasks:
- Cleans up old log entries
- Optimizes the SQLite database
- Archives completed trades
- Removes stale cache entries
"""

import os
import sys
import sqlite3
import argparse
from datetime import datetime, timedelta
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def cleanup_old_logs(db_path: str, days: int = 30):
    """Remove log entries older than specified days."""
    print(f"Cleaning up logs older than {days} days...")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cutoff = datetime.now() - timedelta(days=days)
    cutoff_str = cutoff.isoformat()

    # Check if logs table exists
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='logs'
    """)

    if cursor.fetchone():
        cursor.execute(
            "DELETE FROM logs WHERE timestamp < ?",
            (cutoff_str,)
        )
        deleted = cursor.rowcount
        print(f"  Deleted {deleted} old log entries")
    else:
        print("  No logs table found")

    conn.commit()
    conn.close()


def archive_completed_trades(db_path: str, archive_path: str, days: int = 90):
    """Archive trades older than specified days to separate database."""
    print(f"Archiving trades older than {days} days...")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cutoff = datetime.now() - timedelta(days=days)
    cutoff_str = cutoff.isoformat()

    # Get old trades
    cursor.execute("""
        SELECT * FROM trades WHERE timestamp < ?
    """, (cutoff_str,))

    old_trades = cursor.fetchall()

    if old_trades:
        # Create archive database
        archive_conn = sqlite3.connect(archive_path)
        archive_cursor = archive_conn.cursor()

        # Create archive table if needed
        archive_cursor.execute("""
            CREATE TABLE IF NOT EXISTS archived_trades (
                id TEXT PRIMARY KEY,
                market_id TEXT,
                token_id TEXT,
                side TEXT,
                size REAL,
                price REAL,
                status TEXT,
                timestamp TEXT,
                archived_at TEXT
            )
        """)

        # Insert into archive
        now = datetime.now().isoformat()
        for trade in old_trades:
            archive_cursor.execute("""
                INSERT OR REPLACE INTO archived_trades
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (*trade, now))

        archive_conn.commit()
        archive_conn.close()

        # Delete from main database
        cursor.execute(
            "DELETE FROM trades WHERE timestamp < ?",
            (cutoff_str,)
        )

        print(f"  Archived {len(old_trades)} trades to {archive_path}")
    else:
        print("  No trades to archive")

    conn.commit()
    conn.close()


def optimize_database(db_path: str):
    """Run SQLite optimization commands."""
    print("Optimizing database...")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Analyze tables for query optimization
    cursor.execute("ANALYZE")
    print("  Analyzed tables")

    # Rebuild indexes
    cursor.execute("REINDEX")
    print("  Rebuilt indexes")

    # Reclaim unused space
    cursor.execute("VACUUM")
    print("  Vacuumed database")

    conn.close()

    # Report file size
    size = os.path.getsize(db_path)
    print(f"  Database size: {size / 1024:.1f} KB")


def cleanup_cache(cache_dir: str, hours: int = 24):
    """Remove cache files older than specified hours."""
    print(f"Cleaning up cache files older than {hours} hours...")

    cache_path = Path(cache_dir)
    if not cache_path.exists():
        print("  Cache directory not found")
        return

    cutoff = datetime.now() - timedelta(hours=hours)
    deleted = 0

    for cache_file in cache_path.glob("*.json"):
        mtime = datetime.fromtimestamp(cache_file.stat().st_mtime)
        if mtime < cutoff:
            cache_file.unlink()
            deleted += 1

    print(f"  Deleted {deleted} cache files")


def generate_report(db_path: str):
    """Generate a maintenance report."""
    print("\n" + "=" * 50)
    print("MAINTENANCE REPORT")
    print("=" * 50)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Database stats
    print(f"\nDatabase: {db_path}")
    print(f"Size: {os.path.getsize(db_path) / 1024:.1f} KB")

    # Table counts
    tables = ["trades", "orders", "positions", "daily_stats"]
    for table in tables:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        count = cursor.fetchone()[0]
        print(f"  {table}: {count} records")

    conn.close()
    print("=" * 50)


def main():
    parser = argparse.ArgumentParser(
        description="Maintenance tasks for the Polymarket Trading Agent"
    )
    parser.add_argument(
        "--db",
        default="data/trading.db",
        help="Path to SQLite database"
    )
    parser.add_argument(
        "--archive-path",
        default="data/archive.db",
        help="Path for archived trades"
    )
    parser.add_argument(
        "--cache-dir",
        default="data/cache",
        help="Path to cache directory"
    )
    parser.add_argument(
        "--log-days",
        type=int,
        default=30,
        help="Delete logs older than this many days"
    )
    parser.add_argument(
        "--archive-days",
        type=int,
        default=90,
        help="Archive trades older than this many days"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes"
    )

    args = parser.parse_args()

    print("Polymarket Trading Agent - Maintenance")
    print("=" * 50)
    print(f"Timestamp: {datetime.now().isoformat()}")

    if args.dry_run:
        print("\n[DRY RUN - No changes will be made]\n")
        generate_report(args.db)
        return

    # Run maintenance tasks
    if os.path.exists(args.db):
        cleanup_old_logs(args.db, args.log_days)
        archive_completed_trades(args.db, args.archive_path, args.archive_days)
        optimize_database(args.db)
        cleanup_cache(args.cache_dir)
        generate_report(args.db)
    else:
        print(f"Database not found: {args.db}")
        sys.exit(1)


if __name__ == "__main__":
    main()
