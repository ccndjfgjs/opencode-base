import argparse
import sys
from pathlib import Path

from pool_refresh import (
    DEFAULT_SOURCES,
    DEFAULT_TEST_URL,
    refresh_pool,
)


DEFAULT_OUTPUT = Path(__file__).with_name("public_socks5.local.txt")


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh public SOCKS5 proxy pool")
    parser.add_argument("--source", action="append", dest="sources")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--test-url", default=DEFAULT_TEST_URL)
    parser.add_argument("--timeout", type=float, default=4.0)
    parser.add_argument("--fetch-timeout", type=float, default=20.0)
    parser.add_argument("--workers", type=int, default=40)
    parser.add_argument("--limit", type=int, default=30)
    args = parser.parse_args()

    sources = tuple(args.sources) if args.sources else DEFAULT_SOURCES
    report = refresh_pool(
        output=args.output,
        sources=sources,
        test_url=args.test_url,
        timeout=args.timeout,
        fetch_timeout=args.fetch_timeout,
        workers=args.workers,
        limit=args.limit,
    )
    for error in report["errors"]:
        print(f"source failed: {error}")
    print(f"candidates: {report['candidates']}")
    print(f"alive: {report['alive']}")
    if not report["ok"]:
        print(report["message"])
        return 1
    print(f"written: {args.output}")
    if report.get("backup"):
        print(f"backup: {report['backup']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
