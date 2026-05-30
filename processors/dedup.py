"""Deduplication processor - filters out articles already seen in storage."""

from __future__ import annotations

import hashlib

from models import Entry, FeedResult

from .base import BaseProcessor


class DedupProcessor(BaseProcessor):
    """Removes entries whose hash already exists in the knowledge storage."""

    def __init__(self, storage) -> None:
        """Initialize with a reference to KnowledgeStorage.

        The storage object must expose a ``article_exists(hash: str) -> bool`` method.
        """
        self._storage = storage

    def process(self, results: list[FeedResult], **kwargs) -> list[FeedResult]:
        """Filter out entries that have already been stored."""
        deduped: list[FeedResult] = []

        for result in results:
            if not result.ok or not result.entries:
                deduped.append(result)
                continue

            new_entries: list[Entry] = []
            for entry in result.entries:
                h = self._hash(entry.title, entry.link)
                if not self._storage.article_exists(h):
                    new_entries.append(entry)

            deduped.append(FeedResult(
                config=result.config,
                entries=new_entries,
                error=result.error,
                fetch_duration=result.fetch_duration,
            ))

        return deduped

    @staticmethod
    def _hash(title: str, link: str) -> str:
        """SHA256 of ``title|link``, truncated to 16 hex characters."""
        return hashlib.sha256(f"{title}|{link}".encode()).hexdigest()[:16]
