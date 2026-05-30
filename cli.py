"""Command-line interface for Tech Pulse.

Usage::

    python cli.py run [--days 7] [--language zh-CN]
    python cli.py fetch [--days 7]
    python cli.py discover
"""

from __future__ import annotations

import argparse
import logging
import sys

from config import load_env, load_sources, get_summary_days, get_summary_language
from models import SourceConfig
from pipeline import Pipeline, create_source
from sources.base import BaseSource

log = logging.getLogger("tech-pulse")


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def setup_logging(verbose: bool = False) -> None:
    """Configure root logging for CLI usage.

    *verbose* switches the level from INFO to DEBUG.
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


# ---------------------------------------------------------------------------
# Sub-commands
# ---------------------------------------------------------------------------


def cmd_run(args: argparse.Namespace) -> None:
    """Run the full pipeline: fetch -> dedup -> save -> summarize -> deliver."""
    load_env()

    from channels.email import EmailChannel
    from channels.file import FileChannel
    from processors.summarizer import SummarizeProcessor
    from storage.knowledge import KnowledgeStorage

    sources = load_sources(args.feeds)
    if not sources:
        log.error(f"No sources found in {args.feeds}")
        sys.exit(1)

    days = args.days or get_summary_days()
    language = args.language or get_summary_language()

    pipeline = Pipeline(
        sources=sources,
        storage=KnowledgeStorage(),
        channels=[FileChannel(), EmailChannel()],
        summarize_processor=SummarizeProcessor(),
        days=days,
        language=language,
    )

    pipeline.run()
    log.info("Done!")


def cmd_fetch(args: argparse.Namespace) -> None:
    """Fetch and store articles only (no summarization, no delivery)."""
    load_env()

    from storage.knowledge import KnowledgeStorage

    sources = load_sources(args.feeds)
    if not sources:
        log.error(f"No sources found in {args.feeds}")
        sys.exit(1)

    days = args.days or get_summary_days()

    pipeline = Pipeline(
        sources=sources,
        storage=KnowledgeStorage(),
        days=days,
    )

    results = pipeline.fetch_only()

    total = sum(len(r.entries) for r in results if r.ok)
    errors = [r.config.name for r in results if not r.ok]
    log.info(f"Fetched {total} new articles from {len(results)} sources")
    if errors:
        log.warning(f"Failed sources: {', '.join(errors)}")


def cmd_discover(args: argparse.Namespace) -> None:
    """Discover available sub-sources from configured feeds."""
    sources = load_sources(args.feeds)
    if not sources:
        log.error(f"No sources found in {args.feeds}")
        sys.exit(1)

    for config in sources:
        try:
            src: BaseSource = create_source(config)
            discovered = src.discover()
            if discovered:
                log.info(f"{config.name}: discovered {len(discovered)} sub-sources")
                for sub in discovered:
                    log.info(f"  - {sub.name} ({sub.url})")
            else:
                log.info(f"{config.name}: no sub-sources")
        except Exception as exc:
            log.warning(f"{config.name}: discovery failed - {exc}")


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        prog="tech-pulse",
        description="Tech Pulse - RSS weekly digest with AI summary and email delivery",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        default=False,
        help="Enable debug logging",
    )
    parser.add_argument(
        "--feeds",
        default="feeds.json",
        help="Path to feeds.json (default: feeds.json)",
    )

    sub = parser.add_subparsers(dest="command", help="Available commands")

    # -- run --
    p_run = sub.add_parser("run", help="Full pipeline: fetch + summarize + deliver")
    p_run.add_argument("--days", type=int, default=None, help="Days of articles to fetch (default: from env)")
    p_run.add_argument("--language", default=None, help="Target language for digest (default: from env)")

    # -- fetch --
    p_fetch = sub.add_parser("fetch", help="Fetch and store articles only")
    p_fetch.add_argument("--days", type=int, default=None, help="Days of articles to fetch (default: from env)")

    # -- discover --
    sub.add_parser("discover", help="Discover sub-sources from configured feeds")

    return parser


def main() -> None:
    """Entry point for the CLI."""
    parser = _build_parser()
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    commands = {
        "run": cmd_run,
        "fetch": cmd_fetch,
        "discover": cmd_discover,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
