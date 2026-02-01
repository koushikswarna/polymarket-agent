#!/usr/bin/env python3
"""
Run system health checks.

Usage:
    python scripts/health_check.py
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings
from data.db import Database
from core.client import PolymarketClient
from monitoring.health.checker import HealthChecker


def main():
    print("Polymarket Agent Health Check")
    print("=" * 50)

    # Initialize components
    db = Database(settings.db_path)
    client = PolymarketClient()

    # Run health check
    checker = HealthChecker(client=client, db=db)
    health = checker.check_all()

    # Print results
    print(health.summary())
    print()

    if health.is_healthy:
        print("✓ All systems healthy")
        return 0
    else:
        print("✗ Issues detected:")
        for component in health.unhealthy_components:
            print(f"  - {component}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
