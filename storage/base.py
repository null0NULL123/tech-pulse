from __future__ import annotations

from abc import ABC, abstractmethod

from models import ArticleRecord, Digest, FeedResult


class BaseStorage(ABC):
    """Abstract base for all storage backends."""

    @abstractmethod
    def initialize(self) -> None:
        """Initialize database schema and required tables."""

    def close(self) -> None:
        """Release resources (connection, file handles, etc.)."""

    @abstractmethod
    def save_articles(self, results: list[FeedResult]) -> int:
        """Save fetched articles to storage. Returns count of new articles."""

    @abstractmethod
    def save_digest(self, digest: Digest) -> None:
        """Save weekly digest content."""

    @abstractmethod
    def article_exists(self, article_hash: str) -> bool:
        """Check whether an article with the given hash already exists."""

    def articles_exist(self, hashes: list[str]) -> set[str]:
        """Batch check which hashes exist. Returns set of existing hashes.

        Default implementation falls back to individual article_exists() calls.
        Subclasses should override for better performance.
        """
        return {h for h in hashes if self.article_exists(h)}

    @abstractmethod
    def get_articles(self, weeks: int = 4, source: str | None = None) -> list[ArticleRecord]:
        """Get articles from the last N weeks."""

    @abstractmethod
    def search_similar(self, query: str, limit: int = 5) -> list[ArticleRecord]:
        """Semantic search: find articles most similar to query text."""

    @abstractmethod
    def generate_trend_context(self) -> str:
        """Generate trend analysis text to inject into next digest prompt."""
