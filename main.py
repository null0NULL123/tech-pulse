#!/usr/bin/env python3
"""Tech Pulse - Weekly tech blog digest with AI summarization.

Backward-compatible entry point. Delegates to the new layered CLI.

Usage:
    python main.py              # same as: python cli.py run
    python main.py run          # full pipeline
    python main.py fetch        # fetch and store only
    python main.py discover     # discover new sources
"""

from cli import main

if __name__ == "__main__":
    main()
