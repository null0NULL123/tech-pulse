from __future__ import annotations

import time
from datetime import datetime, timezone

import feedparser

from models import Entry, FeedResult, SourceConfig
from sources.base import BaseSource


class RSSSource(BaseSource):
    """Standard RSS/Atom feed source backed by feedparser."""

    def fetch(self, since: datetime, **kwargs) -> FeedResult:
        """Parse the feed URL, filter entries newer than *since*."""
        start = time.monotonic()
        try:
            parsed = feedparser.parse(self.config.url)
            if parsed.bozo and not parsed.entries:
                return FeedResult(
                    config=self.config,
                    entries=[],
                    error=str(parsed.bozo_exception),
                    fetch_duration=time.monotonic() - start,
                )

            entries: list[Entry] = []
            for raw in parsed.entries:
                pub_date = self._parse_date(raw)
                if pub_date and pub_date < since:
                    continue
                entries.append(
                    Entry(
                        title=raw.get("title", "").strip(),
                        link=raw.get("link", ""),
                        published=pub_date,
                        summary=raw.get("summary", "")[:500],
                        source_name=self.config.name,
                        source_type=self.config.source_type,
                        tags=list(self.config.tags),
                    )
                )
            return FeedResult(
                config=self.config,
                entries=entries,
                fetch_duration=time.monotonic() - start,
            )
        except Exception as exc:
            return FeedResult(
                config=self.config,
                entries=[],
                error=str(exc),
                fetch_duration=time.monotonic() - start,
            )

    def discover(self) -> list[SourceConfig]:
        """Return sub-sources discovered from this feed.

        Placeholder for future OPML parsing support.
        """
        return []

    @staticmethod
    def _parse_date(entry) -> datetime | None:
        """Extract published date from a feedparser entry."""
        for field in ("published_parsed", "updated_parsed"):
            parsed = getattr(entry, field, None)
            if parsed:
                try:
                    return datetime(*parsed[:6], tzinfo=timezone.utc)
                except (TypeError, ValueError):
                    continue
        return None
