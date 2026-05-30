"""Smoke tests for Signal pipeline — no external dependencies, pure assert.

Usage:
    python tests/test_all.py          # run all tests
    python tests/test_all.py config   # run only config tests
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# Ensure project root on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

passed = 0
failed = 0
errors: list[str] = []


def run(name: str, fn) -> None:
    global passed, failed
    try:
        fn()
        print(f"  ✓ {name}")
        passed += 1
    except AssertionError as e:
        print(f"  ✗ {name}: {e}")
        failed += 1
        errors.append(f"{name}: {e}")
    except Exception as e:
        print(f"  ✗ {name}: EXCEPTION {type(e).__name__}: {e}")
        failed += 1
        errors.append(f"{name}: {type(e).__name__}: {e}")


def section(title: str) -> None:
    print(f"\n{'='*50}")
    print(f"  {title}")
    print(f"{'='*50}")


# ------------------------------------------------------------------
# config
# ------------------------------------------------------------------

def test_config_constants():
    from config import (
        DEFAULT_FEEDS_PATH, DEFAULT_DB_PATH, DEFAULT_OUTPUT_DIR,
        DEFAULT_LANGUAGE, DEFAULT_DAYS, DEFAULT_PROMPT_NAME,
        HASH_TRUNCATE_LENGTH, FETCH_MAX_WORKERS, LOCALE,
    )
    assert DEFAULT_FEEDS_PATH == "feeds.json"
    assert DEFAULT_DB_PATH == "knowledge/pulse.db"
    assert DEFAULT_OUTPUT_DIR == "output"
    assert DEFAULT_LANGUAGE == "zh-CN"
    assert DEFAULT_DAYS == 7
    assert DEFAULT_PROMPT_NAME == "tech-weekly"
    assert HASH_TRUNCATE_LENGTH == 16
    assert FETCH_MAX_WORKERS == 8
    assert "email_subject" in LOCALE
    assert "no_articles" in LOCALE


def test_config_get_env():
    from config import get_env, get_int, get_float
    os.environ["_TEST_STR"] = "hello"
    assert get_env("_TEST_STR") == "hello"
    assert get_env("_TEST_MISSING", "default") == "default"

    os.environ["_TEST_INT"] = "42"
    assert get_int("_TEST_INT", 0) == 42
    assert get_int("_TEST_MISSING", 99) == 99

    os.environ["_TEST_FLOAT"] = "3.14"
    assert get_float("_TEST_FLOAT", 0.0) == 3.14
    assert get_float("_TEST_MISSING", 1.5) == 1.5

    del os.environ["_TEST_STR"]
    del os.environ["_TEST_INT"]
    del os.environ["_TEST_FLOAT"]


def test_config_load_env():
    from config import load_env
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
        f.write("# comment\n")
        f.write("API_BASE_URL=https://test.api.com/v1\n")
        f.write("API_KEY=test-key\n")
        f.write("MODEL_NAME=test-model\n")
        f.write("SMTP_SERVER=smtp.test.com\n")
        f.write("SMTP_PORT=587\n")
        f.write("SMTP_SENDER=test@test.com\n")
        f.write("SMTP_AUTH_CODE=test-code\n")
        f.write("SMTP_RECEIVER=test@test.com\n")
        f.write("EXTRA_VAR=extra-value\n")
        tmp_path = f.name

    try:
        # Save and clear env
        saved = {}
        for k in ["API_BASE_URL", "API_KEY", "MODEL_NAME", "SMTP_SERVER",
                   "SMTP_PORT", "SMTP_SENDER", "SMTP_AUTH_CODE", "SMTP_RECEIVER", "EXTRA_VAR"]:
            saved[k] = os.environ.pop(k, None)

        load_env(tmp_path)
        assert os.environ["API_BASE_URL"] == "https://test.api.com/v1"
        assert os.environ["EXTRA_VAR"] == "extra-value"

        # Restore
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)
    finally:
        os.unlink(tmp_path)


def test_config_load_sources():
    from config import load_sources, DEFAULT_SOURCE_LANG, DEFAULT_SOURCE_TYPE
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump([
            {"name": "Test Blog", "url": "https://example.com/rss"},
            {"name": "Web Source", "url": "https://example.com", "source_type": "web", "lang": "zh"},
        ], f)
        tmp_path = f.name

    try:
        sources = load_sources(tmp_path)
        assert len(sources) == 2
        assert sources[0].name == "Test Blog"
        assert sources[0].lang == DEFAULT_SOURCE_LANG
        assert sources[0].source_type == DEFAULT_SOURCE_TYPE
        assert sources[1].source_type == "web"
        assert sources[1].lang == "zh"
    finally:
        os.unlink(tmp_path)


# ------------------------------------------------------------------
# models
# ------------------------------------------------------------------

def test_models_source_config():
    from models import SourceConfig
    sc = SourceConfig(name="test", url="http://x")
    assert sc.name == "test"
    assert sc.lang == "en"
    assert sc.source_type == "rss"
    assert sc.enabled is True
    assert sc.tags == []
    assert sc.metadata == {}


def test_models_entry():
    from models import Entry
    e = Entry(title="Hello", link="http://x")
    assert e.title == "Hello"
    assert e.summary == ""
    assert e.published is None


def test_models_feed_result():
    from models import FeedResult, SourceConfig, Entry
    cfg = SourceConfig(name="t", url="http://x")
    r = FeedResult(config=cfg)
    assert r.ok is True
    assert r.entries == []

    r2 = FeedResult(config=cfg, error="fail")
    assert r2.ok is False


def test_models_digest():
    from models import Digest
    d = Digest(content="hello", language="zh-CN")
    assert d.content == "hello"
    assert d.article_count == 0


# ------------------------------------------------------------------
# processors/dedup
# ------------------------------------------------------------------

def test_dedup_hash():
    from processors.dedup import DedupProcessor
    from config import HASH_TRUNCATE_LENGTH
    h = DedupProcessor._hash("title", "http://link")
    assert len(h) == HASH_TRUNCATE_LENGTH
    assert h == DedupProcessor._hash("title", "http://link")  # deterministic


def test_dedup_process():
    from processors.dedup import DedupProcessor
    from models import FeedResult, SourceConfig, Entry

    class MockStorage:
        def __init__(self, existing: set[str]):
            self._existing = existing
        def articles_exist(self, hashes):
            return {h for h in hashes if h in self._existing}

    cfg = SourceConfig(name="t", url="http://x")
    e1 = Entry(title="A", link="http://a")
    e2 = Entry(title="B", link="http://b")
    e3 = Entry(title="C", link="http://c")

    h1 = DedupProcessor._hash("A", "http://a")
    h2 = DedupProcessor._hash("B", "http://b")

    storage = MockStorage({h1})  # A already exists
    dedup = DedupProcessor(storage)

    results = [FeedResult(config=cfg, entries=[e1, e2, e3])]
    deduped = dedup.process(results)

    assert len(deduped) == 1
    remaining = deduped[0].entries
    assert len(remaining) == 2
    assert remaining[0].title == "B"
    assert remaining[1].title == "C"


# ------------------------------------------------------------------
# storage/knowledge
# ------------------------------------------------------------------

def test_storage_init_and_schema():
    from storage.knowledge import KnowledgeStorage

    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["DB_PATH"] = os.path.join(tmpdir, "test.db")
        try:
            ks = KnowledgeStorage()
            ks.initialize()

            db = ks._get_db()
            tables = [r[0] for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]
            assert "articles" in tables
            assert "topics" in tables
            assert "digests" in tables
            assert "article_vec" in tables

            ks.close()
        finally:
            os.environ.pop("DB_PATH", None)


def test_storage_save_and_query():
    from storage.knowledge import KnowledgeStorage
    from models import FeedResult, SourceConfig, Entry

    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["DB_PATH"] = os.path.join(tmpdir, "test.db")
        try:
            ks = KnowledgeStorage()
            ks.initialize()

            cfg = SourceConfig(name="Test", url="http://x")
            e1 = Entry(title="Article One", link="http://x/1", published=datetime.now(timezone.utc), summary="Summary one")
            e2 = Entry(title="Article Two", link="http://x/2", published=datetime.now(timezone.utc), summary="Summary two")
            result = FeedResult(config=cfg, entries=[e1, e2])

            saved = ks.save_articles([result])
            assert saved == 2

            # Duplicate should not save
            saved2 = ks.save_articles([result])
            assert saved2 == 0

            # Query
            articles = ks.get_articles(weeks=1)
            assert len(articles) == 2
            assert articles[0].title in ("Article One", "Article Two")

            ks.close()
        finally:
            os.environ.pop("DB_PATH", None)


def test_storage_batch_exist():
    from storage.knowledge import KnowledgeStorage

    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["DB_PATH"] = os.path.join(tmpdir, "test.db")
        try:
            ks = KnowledgeStorage()
            ks.initialize()

            # Empty list
            assert ks.articles_exist([]) == set()

            # Insert one article
            from models import FeedResult, SourceConfig, Entry
            cfg = SourceConfig(name="T", url="http://x")
            e = Entry(title="X", link="http://x/1", published=datetime.now(timezone.utc))
            ks.save_articles([FeedResult(config=cfg, entries=[e])])

            # Get its hash
            h = ks._hash("X", "http://x/1")
            assert h in ks.articles_exist([h])
            assert "nonexistent" not in ks.articles_exist(["nonexistent"])

            ks.close()
        finally:
            os.environ.pop("DB_PATH", None)


def test_storage_topics():
    from storage.knowledge import KnowledgeStorage

    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["DB_PATH"] = os.path.join(tmpdir, "test.db")
        try:
            ks = KnowledgeStorage()
            ks.initialize()

            ks.save_topics(["AI", "LLM", "ai"])  # "AI" and "ai" should merge
            trends = ks.get_topic_trends(months=1)
            assert len(trends) >= 1
            ai_topic = next((t for t in trends if t["topic"] == "ai"), None)
            assert ai_topic is not None
            assert ai_topic["total"] == 2  # "AI" + "ai" merged

            ks.close()
        finally:
            os.environ.pop("DB_PATH", None)


def test_storage_digest():
    from storage.knowledge import KnowledgeStorage
    from models import Digest

    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["DB_PATH"] = os.path.join(tmpdir, "test.db")
        try:
            ks = KnowledgeStorage()
            ks.initialize()

            d = Digest(content="test digest", article_count=5)
            ks.save_digest(d)

            db = ks._get_db()
            row = db.execute("SELECT content, article_count FROM digests").fetchone()
            assert row[0] == "test digest"
            assert row[1] == 5

            ks.close()
        finally:
            os.environ.pop("DB_PATH", None)


def test_storage_keyword_search():
    from storage.knowledge import KnowledgeStorage
    from models import FeedResult, SourceConfig, Entry

    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["DB_PATH"] = os.path.join(tmpdir, "test.db")
        try:
            ks = KnowledgeStorage()
            ks.initialize()

            cfg = SourceConfig(name="T", url="http://x")
            entries = [
                Entry(title="SQLite is great", link="http://x/1", published=datetime.now(timezone.utc)),
                Entry(title="PostgreSQL tips", link="http://x/2", published=datetime.now(timezone.utc)),
                Entry(title="SQLite advanced", link="http://x/3", published=datetime.now(timezone.utc)),
            ]
            ks.save_articles([FeedResult(config=cfg, entries=entries)])

            results = ks._search_by_keywords(["SQLite"])
            assert len(results) == 2
            titles = {r.title for r in results}
            assert "SQLite is great" in titles
            assert "SQLite advanced" in titles

            ks.close()
        finally:
            os.environ.pop("DB_PATH", None)


def test_storage_trend_context():
    from storage.knowledge import KnowledgeStorage

    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["DB_PATH"] = os.path.join(tmpdir, "test.db")
        try:
            ks = KnowledgeStorage()
            ks.initialize()

            # No data -> empty context
            assert ks.generate_trend_context() == ""

            # With topics
            ks.save_topics(["AI", "LLM", "Rust"])
            ctx = ks.generate_trend_context()
            assert "上升趋势话题" in ctx or "高频话题" in ctx

            ks.close()
        finally:
            os.environ.pop("DB_PATH", None)


def test_storage_related_context():
    from storage.knowledge import KnowledgeStorage
    from models import FeedResult, SourceConfig, Entry

    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["DB_PATH"] = os.path.join(tmpdir, "test.db")
        try:
            ks = KnowledgeStorage()
            ks.initialize()

            # Save some historical articles
            cfg = SourceConfig(name="T", url="http://x")
            old = [
                Entry(title="Old SQLite article", link="http://x/old1", published=datetime.now(timezone.utc)),
                Entry(title="Old Rust article", link="http://x/old2", published=datetime.now(timezone.utc)),
            ]
            ks.save_articles([FeedResult(config=cfg, entries=old)])

            # Current articles (different titles, should find related via keyword)
            current = [
                Entry(title="New SQLite feature", link="http://x/new1", published=datetime.now(timezone.utc)),
            ]
            ctx = ks.generate_related_context([FeedResult(config=cfg, entries=current)])
            # Should find "Old SQLite article" as related
            assert "SQLite" in ctx

            ks.close()
        finally:
            os.environ.pop("DB_PATH", None)


# ------------------------------------------------------------------
# sources
# ------------------------------------------------------------------

def test_rss_source_parse_date():
    from sources.rss import RSSSource
    from datetime import timezone

    class FakeEntry:
        published_parsed = (2026, 5, 30, 12, 0, 0, 0, 0, 0)

    dt = RSSSource._parse_date(FakeEntry())
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 5
    assert dt.day == 30
    assert dt.tzinfo == timezone.utc


def test_web_source_defaults():
    from sources.web import _DEFAULTS
    assert "selector" in _DEFAULTS
    assert "title_sel" in _DEFAULTS
    assert _DEFAULTS["selector"] == "article"


# ------------------------------------------------------------------
# pipeline
# ------------------------------------------------------------------

def test_create_source():
    from pipeline import create_source
    from models import SourceConfig

    rss = create_source(SourceConfig(name="t", url="http://x"))
    assert type(rss).__name__ == "RSSSource"

    web = create_source(SourceConfig(name="t", url="http://x", source_type="web"))
    assert type(web).__name__ == "WebSource"

    try:
        create_source(SourceConfig(name="t", url="http://x", source_type="unknown"))
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


def test_pipeline_init():
    from pipeline import Pipeline
    from models import SourceConfig
    from config import DEFAULT_DAYS, DEFAULT_LANGUAGE

    p = Pipeline(sources=[], storage=None)
    assert p.days == DEFAULT_DAYS
    assert p.language == DEFAULT_LANGUAGE
    assert p.channels == []

    p2 = Pipeline(sources=[], storage=None, days=3, language="en")
    assert p2.days == 3
    assert p2.language == "en"


# ------------------------------------------------------------------
# summarizer
# ------------------------------------------------------------------

def test_summarizer_prompt_loading():
    from processors.summarizer import load_prompt, _prompts_dir
    assert _prompts_dir().exists()
    prompt = load_prompt("tech-weekly")
    assert len(prompt) > 0
    assert isinstance(prompt, str)


def test_summarizer_build_prompt():
    from processors.summarizer import SummarizeProcessor
    from models import FeedResult, SourceConfig, Entry

    # We can't call __init__ without API keys, so test _build_user_prompt directly
    # by creating a minimal instance
    class FakeProcessor:
        _build_user_prompt = SummarizeProcessor._build_user_prompt

    cfg = SourceConfig(name="Blog", url="http://x")
    e1 = Entry(title="Test Article", link="http://x/1", summary="A test summary")
    e2 = Entry(title="Another", link="http://x/2", summary="")
    result = FeedResult(config=cfg, entries=[e1, e2])
    error_result = FeedResult(config=cfg, error="timeout")

    fp = FakeProcessor()
    prompt = fp._build_user_prompt([result, error_result], "zh-CN")

    assert "Test Article" in prompt
    assert "Another" in prompt
    assert "Blog" in prompt
    assert "timeout" in prompt  # error source listed
    assert "2" in prompt  # article count


def test_summarizer_empty_prompt():
    from processors.summarizer import SummarizeProcessor
    from models import FeedResult, SourceConfig

    class FakeProcessor:
        _build_user_prompt = SummarizeProcessor._build_user_prompt

    cfg = SourceConfig(name="Blog", url="http://x")
    empty_result = FeedResult(config=cfg, entries=[])

    fp = FakeProcessor()
    prompt = fp._build_user_prompt([empty_result], "zh-CN")
    assert "无新文章" in prompt


# ------------------------------------------------------------------
# channels
# ------------------------------------------------------------------

def test_file_channel():
    from channels.file import FileChannel
    from models import Digest

    with tempfile.TemporaryDirectory() as tmpdir:
        ch = FileChannel(output_dir=tmpdir)
        assert ch.name == "file"

        d = Digest(content="# Test\nHello world")
        result = ch.send(d)
        assert result is True

        files = list(Path(tmpdir).glob("*.md"))
        assert len(files) == 1
        assert "signal-" in files[0].name
        assert files[0].read_text() == "# Test\nHello world"


def test_github_pages_channel():
    from channels.github_pages import GitHubPagesChannel
    from models import Digest

    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["GITHUB_PAGES_DIR"] = tmpdir
        try:
            ch = GitHubPagesChannel()
            assert ch.name == "github_pages"

            d = Digest(content="# Hello\n\nTest content")
            result = ch.send(d)
            assert result is True

            digests_dir = Path(tmpdir) / "digests"
            assert digests_dir.exists()
            html_files = list(digests_dir.glob("*.html"))
            assert len(html_files) == 1
            assert "Hello" in html_files[0].read_text()

            index = Path(tmpdir) / "index.html"
            assert index.exists()
            assert "Signal" in index.read_text()
        finally:
            os.environ.pop("GITHUB_PAGES_DIR", None)


# ------------------------------------------------------------------
# Run all
# ------------------------------------------------------------------

ALL_TESTS = {
    "config": [
        ("constants", test_config_constants),
        ("get_env/get_int/get_float", test_config_get_env),
        ("load_env", test_config_load_env),
        ("load_sources", test_config_load_sources),
    ],
    "models": [
        ("SourceConfig", test_models_source_config),
        ("Entry", test_models_entry),
        ("FeedResult", test_models_feed_result),
        ("Digest", test_models_digest),
    ],
    "dedup": [
        ("hash", test_dedup_hash),
        ("process", test_dedup_process),
    ],
    "storage": [
        ("init and schema", test_storage_init_and_schema),
        ("save and query", test_storage_save_and_query),
        ("batch exist", test_storage_batch_exist),
        ("topics", test_storage_topics),
        ("digest", test_storage_digest),
        ("keyword search", test_storage_keyword_search),
        ("trend context", test_storage_trend_context),
        ("related context", test_storage_related_context),
    ],
    "sources": [
        ("RSS parse_date", test_rss_source_parse_date),
        ("Web defaults", test_web_source_defaults),
    ],
    "pipeline": [
        ("create_source", test_create_source),
        ("Pipeline init", test_pipeline_init),
    ],
    "summarizer": [
        ("prompt loading", test_summarizer_prompt_loading),
        ("build prompt", test_summarizer_build_prompt),
        ("empty prompt", test_summarizer_empty_prompt),
    ],
    "channels": [
        ("FileChannel", test_file_channel),
        ("GitHubPagesChannel", test_github_pages_channel),
    ],
}


def main():
    global passed, failed, errors

    filter_group = sys.argv[1] if len(sys.argv) > 1 else None

    print("Signal Test Suite")
    print("=" * 50)

    for group, tests in ALL_TESTS.items():
        if filter_group and filter_group != group:
            continue
        section(group)
        for name, fn in tests:
            run(name, fn)

    print(f"\n{'='*50}")
    print(f"  Results: {passed} passed, {failed} failed")
    print(f"{'='*50}")

    if errors:
        print("\nFailures:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print("\nAll tests passed ✓")
        sys.exit(0)


if __name__ == "__main__":
    main()
