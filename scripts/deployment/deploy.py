#!/usr/bin/env python3
"""
Deployment script for the Polymarket Trading Agent.

This script handles deployment to various environments with proper
configuration and health checks.
"""

import os
import sys
import subprocess
import argparse
from pathlib import Path


def check_environment():
    """Verify all required environment variables are set."""
    required_vars = [
        "POLYMARKET_PRIVATE_KEY",
        "POLYMARKET_API_KEY",
        "POLYMARKET_API_SECRET",
        "POLYMARKET_PASSPHRASE",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
    ]

    missing = []
    for var in required_vars:
        if not os.getenv(var):
            missing.append(var)

    if missing:
        print("Missing required environment variables:")
        for var in missing:
            print(f"  - {var}")
        return False

    print("All required environment variables are set.")
    return True


def check_dependencies():
    """Verify all Python dependencies are installed."""
    try:
        import anthropic
        import openai
        import rich
        import pydantic
        print("All core dependencies are installed.")
        return True
    except ImportError as e:
        print(f"Missing dependency: {e}")
        print("Run: pip install -r requirements.txt")
        return False


def run_tests():
    """Run the test suite before deployment."""
    print("Running test suite...")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        print("Tests failed! Aborting deployment.")
        print(result.stdout)
        print(result.stderr)
        return False

    print("All tests passed.")
    return True


def deploy_local():
    """Deploy for local development/testing."""
    print("Deploying locally...")

    # Check environment
    if not check_environment():
        return False

    # Check dependencies
    if not check_dependencies():
        return False

    print("\nLocal deployment ready!")
    print("Start the agent with: python main.py")
    print("For dry-run mode: python main.py --dry-run")
    return True


def deploy_docker():
    """Build and run Docker container."""
    print("Building Docker image...")

    dockerfile_content = '''FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create non-root user for security
RUN useradd -m -r agent && chown -R agent:agent /app
USER agent

CMD ["python", "main.py"]
'''

    # Write Dockerfile if it doesn't exist
    dockerfile_path = Path("Dockerfile")
    if not dockerfile_path.exists():
        dockerfile_path.write_text(dockerfile_content)
        print("Created Dockerfile")

    # Build image
    result = subprocess.run(
        ["docker", "build", "-t", "polymarket-agent", "."],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        print(f"Docker build failed: {result.stderr}")
        return False

    print("Docker image built successfully!")
    print("\nRun with:")
    print("  docker run --env-file .env polymarket-agent")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Deploy the Polymarket Trading Agent"
    )
    parser.add_argument(
        "target",
        choices=["local", "docker", "check"],
        help="Deployment target"
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip running tests before deployment"
    )

    args = parser.parse_args()

    print("=" * 50)
    print("Polymarket Trading Agent Deployment")
    print("=" * 50)

    # Run tests unless skipped
    if not args.skip_tests and args.target != "check":
        if not run_tests():
            sys.exit(1)

    # Deploy to target
    if args.target == "check":
        success = check_environment() and check_dependencies()
    elif args.target == "local":
        success = deploy_local()
    elif args.target == "docker":
        success = deploy_docker()
    else:
        print(f"Unknown target: {args.target}")
        success = False

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
