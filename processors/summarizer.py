"""LLM summarizer processor - generates a Chinese tech digest from fetched entries."""

from __future__ import annotations

import os
import re
from pathlib import Path

from openai import OpenAI

from models import Digest, FeedResult

from .base import BaseProcessor

# Prompts directory (relative to project root)
PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def load_prompt(name: str = "tech-weekly") -> str:
    """Load a prompt from the prompts directory.

    Args:
        name: Prompt filename without extension (e.g., "tech-weekly", "finance-weekly")

    Returns:
        The prompt text.

    Raises:
        FileNotFoundError: If the prompt file does not exist.
    """
    filepath = PROMPTS_DIR / f"{name}.md"
    if not filepath.exists():
        raise FileNotFoundError(
            f"Prompt file not found: {filepath}. "
            f"Available prompts: {[f.stem for f in PROMPTS_DIR.glob('*.md')]}"
        )
    return filepath.read_text(encoding="utf-8").strip()


class SummarizeProcessor(BaseProcessor):
    """Calls an LLM API to generate a Chinese tech digest."""

    def __init__(
        self,
        api_key: str | None = None,
        api_base_url: str | None = None,
        model: str | None = None,
        prompt: str | None = None,
        prompt_name: str | None = None,
    ) -> None:
        self._api_key = api_key or os.environ["API_KEY"]
        self._api_base_url = api_base_url or os.environ["API_BASE_URL"]
        self._model = model or os.environ.get("MODEL_NAME", "deepseek-chat")

        # Prompt loading priority: explicit prompt > prompt_name > env > "tech-weekly"
        if prompt:
            self._system_prompt = prompt
        else:
            name = prompt_name or os.environ.get("PROMPT_NAME", "tech-weekly")
            self._system_prompt = load_prompt(name)

    def process(
        self,
        results: list[FeedResult],
        language: str = "zh-CN",
        trend_context: str = "",
        **kwargs,
    ) -> Digest:
        """Generate a digest from feed results via LLM."""
        user_prompt = self._build_user_prompt(results, language)

        if "本周所有订阅源均无新文章" in user_prompt:
            return Digest(content="本周所有订阅源均无新文章发布。\n", language=language)

        if trend_context:
            user_prompt = trend_context + "\n\n" + user_prompt

        client = OpenAI(api_key=self._api_key, base_url=self._api_base_url)
        response = client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": self._system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=4096,
        )

        content = response.choices[0].message.content
        total = sum(
            len(r.entries) for r in results if r.ok
        )

        return Digest(
            content=content,
            article_count=total,
            language=language,
        )

    def _build_user_prompt(self, results: list[FeedResult], language: str) -> str:
        """Build the user prompt from fetched feed results."""
        parts: list[str] = []
        total = 0

        for result in results:
            if result.error:
                parts.append(f"### {result.config.name}（拉取失败: {result.error}）")
                continue
            if not result.entries:
                parts.append(f"### {result.config.name}（本周无新文章）")
                continue

            parts.append(f"### {result.config.name}（{len(result.entries)} 篇）")
            for entry in result.entries:
                parts.append(f"- **{entry.title}**")
                if entry.summary:
                    clean = re.sub(r"<[^>]+>", "", entry.summary)[:300]
                    parts.append(f"  摘要: {clean}")
                parts.append(f"  链接: {entry.link}")
                total += 1

        if total == 0:
            return "本周所有订阅源均无新文章发布。"

        header = f"以下是本周（最近 7 天）从 {len(results)} 个技术博客收集到的 {total} 篇新文章。\n"
        header += f"请生成一份中文技术周报。目标语言: {language}\n\n"
        return header + "\n".join(parts)
