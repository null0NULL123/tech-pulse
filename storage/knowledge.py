"""Knowledge accumulation storage - stores articles, tracks trends, enables semantic search.

Uses SQLite + sqlite-vec for structured + vector queries in a single .db file.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import sqlite_vec

from models import ArticleRecord, Digest, FeedResult

from .base import BaseStorage

DB_PATH = "knowledge/pulse.db"
EMBEDDING_DIM = 384  # sentence-transformers/all-MiniLM-L6-v2


class KnowledgeStorage(BaseStorage):
    """SQLite + sqlite-vec storage backend for the knowledge base."""

    def _get_db(self) -> sqlite3.Connection:
        """Get database connection with sqlite-vec loaded."""
        Path("knowledge").mkdir(exist_ok=True)
        db = sqlite3.connect(DB_PATH)
        db.enable_load_extension(True)
        sqlite_vec.load(db)
        db.enable_load_extension(False)
        db.execute("PRAGMA journal_mode=WAL")
        return db

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

        # Create vector virtual table for semantic search
        db.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS article_vec USING vec0(
                article_id INTEGER PRIMARY KEY,
                embedding float[{EMBEDDING_DIM}]
            )
        """)
        db.commit()
        db.close()

    def _article_hash(self, title: str, link: str) -> str:
        """Generate unique hash for deduplication."""
        return hashlib.sha256(f"{title}|{link}".encode()).hexdigest()[:16]

    @staticmethod
    def _get_week_id(dt: datetime | None = None) -> str:
        """Get ISO week identifier like '2026-W22'."""
        if dt is None:
            dt = datetime.now(timezone.utc)
        iso = dt.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"

    def _get_embedding(self, text: str) -> list[float] | None:
        """Generate embedding vector for text. Uses API if available, else None."""
        try:
            from openai import OpenAI

            client = OpenAI(
                api_key=os.environ["API_KEY"],
                base_url=os.environ["API_BASE_URL"],
            )
            model = os.environ.get("EMBEDDING_MODEL", "")
            if not model:
                return None
            response = client.embeddings.create(model=model, input=text[:2000])
            return response.data[0].embedding
        except Exception:
            return None

    def save_articles(self, results: list[FeedResult]) -> int:
        """Save fetched articles to database. Returns count of new articles."""
        db = self._get_db()
        week = self._get_week_id()
        saved = 0

        for feed in results:
            if feed.error:
                continue
            for entry in feed.entries:
                h = self._article_hash(entry.title, entry.link)
                try:
                    db.execute(
                        """INSERT OR IGNORE INTO articles (hash, title, link, source, published, summary, week)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (h, entry.title, entry.link, feed.config.name,
                         entry.published or "", entry.summary, week)
                    )
                    if db.execute("SELECT changes()").fetchone()[0] > 0:
                        saved += 1

                        # Generate and store embedding
                        embed_text = f"{entry.title} {entry.summary}"
                        embedding = self._get_embedding(embed_text)
                        if embedding:
                            article_id = db.execute(
                                "SELECT id FROM articles WHERE hash = ?", (h,)
                            ).fetchone()[0]
                            db.execute(
                                "INSERT OR REPLACE INTO article_vec (article_id, embedding) VALUES (?, vec_f32(?))",
                                (article_id, json.dumps(embedding))
                            )
                except sqlite3.IntegrityError:
                    pass

        db.commit()
        db.close()
        return saved

    def save_topics(self, topics: list[str], week: str | None = None) -> None:
        """Save or increment topic counts for a given week."""
        db = self._get_db()
        week = week or self._get_week_id()
        for topic in topics:
            topic = topic.strip().lower()
            if not topic:
                continue
            db.execute(
                """INSERT INTO topics (week, topic, count) VALUES (?, ?, 1)
                   ON CONFLICT(week, topic) DO UPDATE SET count = count + 1""",
                (week, topic)
            )
        db.commit()
        db.close()

    def save_digest(self, digest: Digest) -> None:
        """Save weekly digest content."""
        db = self._get_db()
        week = digest.week or self._get_week_id()
        db.execute(
            """INSERT OR REPLACE INTO digests (week, content, article_count) VALUES (?, ?, ?)""",
            (week, digest.content, digest.article_count)
        )
        db.commit()
        db.close()

    def article_exists(self, article_hash: str) -> bool:
        """Check whether an article with the given hash already exists."""
        db = self._get_db()
        row = db.execute(
            "SELECT 1 FROM articles WHERE hash = ? LIMIT 1", (article_hash,)
        ).fetchone()
        db.close()
        return row is not None

    def get_articles(self, weeks: int = 4, source: str | None = None) -> list[ArticleRecord]:
        """Get articles from the last N weeks."""
        db = self._get_db()
        db.row_factory = sqlite3.Row
        cutoff_week = self._get_week_id(datetime.now(timezone.utc) - timedelta(weeks=weeks))

        if source:
            rows = db.execute(
                "SELECT * FROM articles WHERE week >= ? AND source = ? ORDER BY published DESC",
                (cutoff_week, source)
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM articles WHERE week >= ? ORDER BY published DESC",
                (cutoff_week,)
            ).fetchall()

        db.close()
        return [
            ArticleRecord(
                id=r["id"],
                hash=r["hash"],
                title=r["title"],
                link=r["link"],
                source=r["source"],
                published=r["published"],
                summary=r["summary"],
                tags=json.loads(r["tags"]) if r["tags"] else [],
                week=r["week"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def search_similar(self, query: str, limit: int = 5) -> list[ArticleRecord]:
        """Semantic search: find articles most similar to query text."""
        embedding = self._get_embedding(query)
        if not embedding:
            return []

        db = self._get_db()
        db.row_factory = sqlite3.Row
        rows = db.execute("""
            SELECT a.*, v.distance
            FROM article_vec v
            JOIN articles a ON a.id = v.article_id
            WHERE v.embedding MATCH vec_f32(?)
            ORDER BY v.distance ASC
            LIMIT ?
        """, (json.dumps(embedding), limit)).fetchall()

        db.close()
        return [
            ArticleRecord(
                id=r["id"],
                hash=r["hash"],
                title=r["title"],
                link=r["link"],
                source=r["source"],
                published=r["published"],
                summary=r["summary"],
                tags=json.loads(r["tags"]) if r["tags"] else [],
                week=r["week"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def get_topic_trends(self, months: int = 3) -> list[dict]:
        """Get topic frequency trends over the last N months."""
        db = self._get_db()
        cutoff = datetime.now(timezone.utc) - timedelta(days=months * 30)
        cutoff_week = self._get_week_id(cutoff)

        rows = db.execute("""
            SELECT topic, week, count
            FROM topics
            WHERE week >= ?
            ORDER BY week ASC, count DESC
        """, (cutoff_week,)).fetchall()
        db.close()

        # Organize by topic
        trends: dict[str, dict] = {}
        for topic, week, count in rows:
            if topic not in trends:
                trends[topic] = {"topic": topic, "weeks": [], "total": 0}
            trends[topic]["weeks"].append({"week": week, "count": count})
            trends[topic]["total"] += count

        # Sort by total frequency
        return sorted(trends.values(), key=lambda x: x["total"], reverse=True)

    def get_rising_topics(self, weeks: int = 4) -> list[dict]:
        """Detect topics with rising frequency in recent weeks."""
        trends = self.get_topic_trends(months=2)
        rising = []

        for t in trends:
            if len(t["weeks"]) < 2:
                continue
            recent = t["weeks"][-1]["count"]
            previous = sum(w["count"] for w in t["weeks"][:-1]) / max(len(t["weeks"]) - 1, 1)
            if recent > previous * 1.5 and recent >= 2:
                rising.append({
                    "topic": t["topic"],
                    "recent_count": recent,
                    "avg_previous": round(previous, 1),
                    "trend": "rising"
                })

        return rising

    def generate_trend_context(self) -> str:
        """Generate trend analysis text to inject into next digest prompt."""
        trends = self.get_topic_trends(months=3)
        rising = self.get_rising_topics()

        if not trends and not rising:
            return ""

        lines = ["## 历史趋势参考（供摘要参考，不输出到周报中）\n"]

        if rising:
            lines.append("### 上升趋势话题")
            for r in rising[:5]:
                lines.append(f"- {r['topic']}: 近期 {r['recent_count']} 次，此前平均 {r['avg_previous']} 次")

        if trends:
            lines.append("\n### 近 3 个月高频话题")
            for t in trends[:10]:
                weeks_str = ", ".join(f"{w['week']}({w['count']})" for w in t["weeks"][-4:])
                lines.append(f"- {t['topic']}: 总计 {t['total']} 次 | 近期: {weeks_str}")

        return "\n".join(lines)
