"""Knowledge accumulation storage - stores articles, tracks trends, enables semantic search.

Uses SQLite + sqlite-vec for structured + vector queries in a single .db file.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import sqlite_vec

from config import (
    CONTEXT_SUMMARY_TRUNCATE_LENGTH,
    CONTEXT_TITLE_TRUNCATE_LENGTH,
    DEFAULT_DB_PATH,
    DEFAULT_EMBEDDING_DIM,
    EMBEDDING_MAX_INPUT_LENGTH,
    HASH_TRUNCATE_LENGTH,
    LOCALE,
    MAX_KEYWORD_SEARCH,
    MAX_RISING_TOPICS,
    MAX_SEMANTIC_QUERIES,
    MAX_TREND_TOPICS,
    MIN_KEYWORD_LENGTH,
    RISING_TOPIC_MIN_COUNT,
    RISING_TOPIC_MULTIPLIER,
    get_env,
    get_int,
)
from models import ArticleRecord, Digest, Entry, FeedResult

from .base import BaseStorage


class KnowledgeStorage(BaseStorage):
    """SQLite + sqlite-vec storage backend for the knowledge base."""

    def __init__(self) -> None:
        self._conn: sqlite3.Connection | None = None

    def _get_db(self) -> sqlite3.Connection:
        """Get database connection with sqlite-vec loaded. Reuses connection within a run."""
        if self._conn is not None:
            return self._conn
        db_path = get_env("DB_PATH", DEFAULT_DB_PATH)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(db_path)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=NORMAL")
        db.execute("PRAGMA cache_size=-8000")
        db.execute("PRAGMA temp_store=MEMORY")
        db.enable_load_extension(True)
        sqlite_vec.load(db)
        db.enable_load_extension(False)
        self._conn = db
        return db

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def initialize(self) -> None:
        """Initialize database schema and vector table."""
        db = self._get_db()
        db.executescript("""
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hash TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                link TEXT NOT NULL,
                source TEXT NOT NULL,
                published TEXT,
                summary TEXT,
                tags TEXT DEFAULT '[]',
                week TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS topics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                week TEXT NOT NULL,
                topic TEXT NOT NULL,
                count INTEGER DEFAULT 1,
                UNIQUE(week, topic)
            );
            CREATE TABLE IF NOT EXISTS digests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                week TEXT UNIQUE NOT NULL,
                content TEXT NOT NULL,
                article_count INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_articles_week ON articles(week);
            CREATE INDEX IF NOT EXISTS idx_articles_source ON articles(source);
            CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published);
            CREATE INDEX IF NOT EXISTS idx_topics_week ON topics(week);
        """)
        dim = get_int("EMBEDDING_DIM", DEFAULT_EMBEDDING_DIM)
        db.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS article_vec USING vec0(
                article_id INTEGER PRIMARY KEY,
                embedding float[{dim}]
            )
        """)
        db.commit()

    # ------------------------------------------------------------------
    # Hash & time helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _hash(title: str, link: str) -> str:
        return hashlib.sha256(f"{title}|{link}".encode()).hexdigest()[:HASH_TRUNCATE_LENGTH]

    @staticmethod
    def _week_id(dt: datetime | None = None) -> str:
        if dt is None:
            dt = datetime.now(timezone.utc)
        iso = dt.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"

    @staticmethod
    def _row_to_article(r: sqlite3.Row) -> ArticleRecord:
        return ArticleRecord(
            id=r["id"], hash=r["hash"], title=r["title"], link=r["link"],
            source=r["source"], published=r["published"], summary=r["summary"],
            tags=json.loads(r["tags"]) if r["tags"] else [],
            week=r["week"], created_at=r["created_at"],
        )

    # ------------------------------------------------------------------
    # Embedding
    # ------------------------------------------------------------------

    def _get_embedding(self, text: str) -> list[float] | None:
        try:
            from openai import OpenAI

            api_key = os.environ.get("EMBEDDING_API_KEY", "")
            base_url = os.environ.get("EMBEDDING_API_BASE_URL", "")
            model = os.environ.get("EMBEDDING_MODEL", "")
            if not (api_key and base_url and model):
                return None
            client = OpenAI(api_key=api_key, base_url=base_url)
            response = client.embeddings.create(model=model, input=text[:EMBEDDING_MAX_INPUT_LENGTH])
            return response.data[0].embedding
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Batch existence check
    # ------------------------------------------------------------------

    def articles_exist(self, hashes: list[str]) -> set[str]:
        """Check which hashes already exist. Single query with batched IN-clause."""
        if not hashes:
            return set()
        db = self._get_db()
        existing: set[str] = set()
        for i in range(0, len(hashes), 500):
            batch = hashes[i:i + 500]
            ph = ",".join("?" for _ in batch)
            rows = db.execute(f"SELECT hash FROM articles WHERE hash IN ({ph})", batch).fetchall()
            existing.update(r[0] for r in rows)
        return existing

    def article_exists(self, article_hash: str) -> bool:
        db = self._get_db()
        return db.execute("SELECT 1 FROM articles WHERE hash = ? LIMIT 1", (article_hash,)).fetchone() is not None

    # ------------------------------------------------------------------
    # Save operations
    # ------------------------------------------------------------------

    def save_articles(self, results: list[FeedResult]) -> int:
        """Save fetched articles. Returns count of new articles."""
        db = self._get_db()
        week = self._week_id()

        # Collect entries with hashes
        entries: list[tuple[str, str, Entry]] = []  # (hash, source_name, entry)
        for feed in results:
            if feed.error:
                continue
            for entry in feed.entries:
                entries.append((self._hash(entry.title, entry.link), feed.config.name, entry))

        if not entries:
            return 0

        # Pre-check existing (1 query instead of N)
        existing = self.articles_exist([h for h, _, _ in entries])

        # Insert new articles, collect IDs for embeddings
        article_ids: list[tuple[int, Entry]] = []
        for h, source_name, entry in entries:
            if h in existing:
                continue
            try:
                cur = db.execute(
                    "INSERT OR IGNORE INTO articles (hash, title, link, source, published, summary, week) VALUES (?,?,?,?,?,?,?)",
                    (h, entry.title, entry.link, source_name, entry.published or "", entry.summary, week),
                )
                if cur.rowcount > 0:
                    article_ids.append((cur.lastrowid, entry))
            except sqlite3.IntegrityError:
                pass

        # Batch insert embeddings
        embed_rows = [
            (aid, json.dumps(emb))
            for aid, entry in article_ids
            if (emb := self._get_embedding(f"{entry.title} {entry.summary}"))
        ]
        if embed_rows:
            db.executemany(
                "INSERT OR REPLACE INTO article_vec (article_id, embedding) VALUES (?, vec_f32(?))",
                embed_rows,
            )

        db.commit()
        return len(article_ids)

    def save_topics(self, topics: list[str], week: str | None = None) -> None:
        db = self._get_db()
        week = week or self._week_id()
        clean = [(week, t.strip().lower()) for t in topics if t.strip()]
        if not clean:
            return
        db.executemany(
            "INSERT INTO topics (week, topic, count) VALUES (?, ?, 1) ON CONFLICT(week, topic) DO UPDATE SET count = count + 1",
            clean,
        )
        db.commit()

    def save_digest(self, digest: Digest) -> None:
        db = self._get_db()
        week = digest.week or self._week_id()
        db.execute(
            "INSERT OR REPLACE INTO digests (week, content, article_count) VALUES (?, ?, ?)",
            (week, digest.content, digest.article_count),
        )
        db.commit()

    # ------------------------------------------------------------------
    # Query operations
    # ------------------------------------------------------------------

    def get_articles(self, weeks: int = 4, source: str | None = None) -> list[ArticleRecord]:
        db = self._get_db()
        db.row_factory = sqlite3.Row
        cutoff = self._week_id(datetime.now(timezone.utc) - timedelta(weeks=weeks))
        if source:
            rows = db.execute("SELECT * FROM articles WHERE week >= ? AND source = ? ORDER BY published DESC", (cutoff, source)).fetchall()
        else:
            rows = db.execute("SELECT * FROM articles WHERE week >= ? ORDER BY published DESC", (cutoff,)).fetchall()
        db.row_factory = None
        return [self._row_to_article(r) for r in rows]

    def search_similar(self, query: str, limit: int = 5) -> list[ArticleRecord]:
        embedding = self._get_embedding(query)
        if not embedding:
            return []
        db = self._get_db()
        db.row_factory = sqlite3.Row
        rows = db.execute("""
            SELECT a.*, v.distance FROM article_vec v
            JOIN articles a ON a.id = v.article_id
            WHERE v.embedding MATCH vec_f32(?) AND k = ?
            ORDER BY v.distance ASC
        """, (json.dumps(embedding), limit)).fetchall()
        db.row_factory = None
        return [self._row_to_article(r) for r in rows]

    def search_similar_batch(self, queries: list[str], limit_per_query: int = 3) -> list[ArticleRecord]:
        """Batch semantic search. Returns deduplicated results across all queries."""
        if not queries:
            return []
        db = self._get_db()
        db.row_factory = sqlite3.Row
        seen: set[int] = set()
        results: list[ArticleRecord] = []
        for query in queries:
            embedding = self._get_embedding(query)
            if not embedding:
                continue
            rows = db.execute("""
                SELECT a.*, v.distance FROM article_vec v
                JOIN articles a ON a.id = v.article_id
                WHERE v.embedding MATCH vec_f32(?) AND k = ?
                ORDER BY v.distance ASC
            """, (json.dumps(embedding), limit_per_query)).fetchall()
            for r in rows:
                if r["id"] not in seen:
                    seen.add(r["id"])
                    results.append(self._row_to_article(r))
        db.row_factory = None
        return results

    # ------------------------------------------------------------------
    # Trend analysis
    # ------------------------------------------------------------------

    def get_topic_trends(self, months: int = 3) -> list[dict]:
        db = self._get_db()
        cutoff = self._week_id(datetime.now(timezone.utc) - timedelta(days=months * 30))
        rows = db.execute("SELECT topic, week, count FROM topics WHERE week >= ? ORDER BY week ASC, count DESC", (cutoff,)).fetchall()

        trends: dict[str, dict] = {}
        for topic, week, count in rows:
            if topic not in trends:
                trends[topic] = {"topic": topic, "weeks": [], "total": 0}
            trends[topic]["weeks"].append({"week": week, "count": count})
            trends[topic]["total"] += count
        return sorted(trends.values(), key=lambda x: x["total"], reverse=True)

    def get_rising_topics(self) -> list[dict]:
        trends = self.get_topic_trends(months=2)
        rising = []
        for t in trends:
            if len(t["weeks"]) < 2:
                continue
            recent = t["weeks"][-1]["count"]
            previous = sum(w["count"] for w in t["weeks"][:-1]) / max(len(t["weeks"]) - 1, 1)
            if recent > previous * RISING_TOPIC_MULTIPLIER and recent >= RISING_TOPIC_MIN_COUNT:
                rising.append({"topic": t["topic"], "recent_count": recent, "avg_previous": round(previous, 1), "trend": "rising"})
        return rising

    def generate_trend_context(self) -> str:
        trends = self.get_topic_trends(months=3)
        rising = self.get_rising_topics()
        if not trends and not rising:
            return ""

        lines = [f"## {LOCALE['trend_header']}\n"]
        if rising:
            lines.append(f"### {LOCALE['trend_rising']}")
            for r in rising[:MAX_RISING_TOPICS]:
                lines.append(f"- {r['topic']}: 近期 {r['recent_count']} 次，此前平均 {r['avg_previous']} 次")
        if trends:
            lines.append(f"\n### {LOCALE['trend_frequent']}")
            for t in trends[:MAX_TREND_TOPICS]:
                weeks_str = ", ".join(f"{w['week']}({w['count']})" for w in t["weeks"][-4:])
                lines.append(f"- {t['topic']}: 总计 {t['total']} 次 | 近期: {weeks_str}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Related context (semantic + keyword fallback)
    # ------------------------------------------------------------------

    def _search_by_keywords(self, keywords: list[str], limit: int = 5) -> list[ArticleRecord]:
        db = self._get_db()
        db.row_factory = sqlite3.Row
        conditions, params = [], []
        for kw in keywords[:MAX_KEYWORD_SEARCH]:
            conditions.append("(title LIKE ? OR summary LIKE ?)")
            params.extend([f"%{kw}%", f"%{kw}%"])
        if not conditions:
            return []
        rows = db.execute(
            f"SELECT * FROM articles WHERE {' OR '.join(conditions)} ORDER BY published DESC LIMIT ?",
            params + [limit],
        ).fetchall()
        db.row_factory = None
        return [self._row_to_article(r) for r in rows]

    def generate_related_context(self, current_articles: list[FeedResult], limit: int = 8) -> str:
        current_titles: set[str] = set()
        queries: list[str] = []
        keywords: set[str] = set()

        for feed in current_articles:
            for entry in feed.entries:
                current_titles.add(entry.title)
                text = entry.title
                if entry.summary:
                    text += " " + re.sub(r"<[^>]+>", "", entry.summary)[:CONTEXT_TITLE_TRUNCATE_LENGTH]
                queries.append(text)
                for word in entry.title.split():
                    if len(word) > MIN_KEYWORD_LENGTH:
                        keywords.add(word.lower())

        if not queries:
            return ""

        # Phase 1: Batch semantic search
        related: list[ArticleRecord] = []
        if os.environ.get("EMBEDDING_API_KEY"):
            for r in self.search_similar_batch(queries[:MAX_SEMANTIC_QUERIES], limit_per_query=3):
                if r.title not in current_titles:
                    related.append(r)
                    if len(related) >= limit:
                        break

        # Phase 2: Keyword fallback
        if not related and keywords:
            for r in self._search_by_keywords(list(keywords), limit=limit):
                if r.title not in current_titles:
                    related.append(r)

        if not related:
            return ""

        lines = [f"## {LOCALE['related_header']}", f"{LOCALE['related_intro']}\n"]
        for r in related[:limit]:
            line = f"- **{r.title}**（{r.source}，{r.week}）"
            if r.summary:
                line += f"\n  {re.sub(r'<[^>]+>', '', r.summary)[:CONTEXT_SUMMARY_TRUNCATE_LENGTH]}"
            lines.append(line)
        return "\n".join(lines)
