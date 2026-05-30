from __future__ import annotations

import logging
import os
from datetime import datetime

from models import Digest

from .base import BaseChannel

log = logging.getLogger("signal")


class FileChannel(BaseChannel):
    """Save digest to a local markdown file."""

    def __init__(self, output_dir: str = "output") -> None:
        self.output_dir = output_dir

    @property
    def name(self) -> str:
        return "file"

    def send(self, digest: Digest) -> bool:
        """Save digest content to output/signal-YYYY-MM-DD.md. Returns True on success."""
        os.makedirs(self.output_dir, exist_ok=True)
        filename = f"signal-{datetime.now().strftime('%Y-%m-%d')}.md"
        filepath = os.path.join(self.output_dir, filename)

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(digest.content)
            log.info(f"Digest saved to {filepath}")
            return True
        except OSError as e:
            log.error(f"Failed to save digest to {filepath}: {e}")
            return False
