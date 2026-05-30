"""GitHub Pages channel - saves digest as HTML for static site hosting."""

from __future__ import annotations

import json
import os
import re
import logging
from datetime import datetime
from pathlib import Path

from channels.base import BaseChannel
from models import Digest

log = logging.getLogger("signal")

# Digests directory relative to project root
DOCS_DIR = Path(__file__).parent.parent / "docs"
DIGESTS_DIR = DOCS_DIR / "digests"


class GitHubPagesChannel(BaseChannel):
    """Saves digest as a styled HTML page and updates the index."""

    @property
    def name(self) -> str:
        return "github_pages"

    def send(self, digest: Digest) -> bool:
        """Save digest HTML and update index. Returns True on success."""
        try:
            DIGESTS_DIR.mkdir(parents=True, exist_ok=True)

            date_str = datetime.now().strftime("%Y-%m-%d")
            filename = f"{date_str}.html"
            filepath = DIGESTS_DIR / filename

            # Generate the digest HTML page
            html = self._render_digest(digest, date_str)
            filepath.write_text(html, encoding="utf-8")
            log.info(f"Saved digest page to {filepath}")

            # Update the index
            self._update_index()

            return True
        except Exception as e:
            log.error(f"GitHub Pages save failed: {e}")
            return False

    def _render_digest(self, digest: Digest, date_str: str) -> str:
        """Convert digest markdown to a full HTML page."""
        body = self._md_to_html(digest.content)
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Signal - {date_str}</title>
  <link rel="stylesheet" href="../style.css">
</head>
<body>
  <div class="container">
    <header>
      <h1>📡 Signal</h1>
      <p class="date">{date_str} | AI 自动摘要</p>
      <nav><a href="../index.html">← 返回目录</a></nav>
    </header>
    <article>
      {body}
    </article>
    <footer>
      <p>由 Signal 自动生成 | Powered by AI</p>
    </footer>
  </div>
</body>
</html>"""

    def _update_index(self) -> None:
        """Regenerate index.html from all digest files."""
        digests = sorted(DIGESTS_DIR.glob("*.html"), reverse=True)
        entries = []
        for f in digests:
            date_str = f.stem  # "2026-05-30"
            entries.append({
                "date": date_str,
                "file": f"digests/{f.name}",
            })

        index_html = self._render_index(entries)
        index_path = DOCS_DIR / "index.html"
        index_path.write_text(index_html, encoding="utf-8")
        log.info(f"Updated index with {len(entries)} digests")

    def _render_index(self, entries: list[dict]) -> str:
        """Render the index page with links to all digests."""
        items = ""
        for e in entries:
            items += f'    <li><a href="{e["file"]}">{e["date"]}</a></li>\n'

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Signal - AI 摘要周报</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <div class="container">
    <header>
      <h1>📡 Signal</h1>
      <p class="subtitle">从噪音中提取信号</p>
      <p class="description">每周自动从高质量信息源抓取内容，用 AI 生成精炼摘要。</p>
    </header>
    <main>
      <h2>历史周报</h2>
      <ul class="digest-list">
{items}      </ul>
    </main>
    <footer>
      <p>由 Signal 自动生成 | <a href="https://github.com/null0NULL123/signal">GitHub</a></p>
    </footer>
  </div>
</body>
</html>"""

    @staticmethod
    def _md_to_html(md_text: str) -> str:
        """Convert markdown to HTML for web page display."""
        lines = md_text.split("\n")
        html_lines = []
        in_list = False

        for line in lines:
            # Headers
            if line.startswith("## "):
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False
                html_lines.append(f"<h2>{line[3:]}</h2>")
                continue
            elif line.startswith("### "):
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False
                html_lines.append(f"<h3>{line[4:]}</h3>")
                continue
            elif line.startswith("# "):
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False
                html_lines.append(f"<h1>{line[2:]}</h1>")
                continue

            # Horizontal rule
            if line.strip() == "---":
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False
                html_lines.append("<hr>")
                continue

            # Inline formatting
            line = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line)
            line = re.sub(r"`([^`]+)`", r"<code>\1</code>", line)
            line = re.sub(
                r"\[([^\]]+)\]\(([^)]+)\)",
                r'<a href="\2">\1</a>',
                line,
            )

            # List items
            if line.startswith("- ") or line.startswith("* "):
                if not in_list:
                    html_lines.append("<ul>")
                    in_list = True
                html_lines.append(f"<li>{line[2:]}</li>")
            elif re.match(r"^\d+\.\s", line):
                html_lines.append(f"<p class='numbered'>{line}</p>")
            elif line.strip() == "":
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False
                html_lines.append("")
            else:
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False
                html_lines.append(f"<p>{line}</p>")

        if in_list:
            html_lines.append("</ul>")

        return "\n".join(html_lines)
