"""LLM summarizer processor - generates a Chinese tech digest from fetched entries."""

from __future__ import annotations

import os
import re

from openai import OpenAI

from models import Digest, FeedResult

from .base import BaseProcessor

SYSTEM_PROMPT = """你是一位资深技术编辑，专注于将英文技术博客文章转化为高质量的中文技术周报。

## 输出要求
1. 按信息源分组，每组用 ## 标题标注来源
2. 每篇文章用 **加粗标题** + 2-3 句正文概括
3. 保留关键术语的英文原文（如 API、Kubernetes、LLM 等）
4. 突出"为什么这个重要"——技术意义或行业影响
5. 每篇附上原文链接，格式为 [原文链接](URL)
6. 不要用翻译腔，用自然流畅的中文表达
7. 如果不同源的文章有关联，在末尾用"### 本周看点"段落指出

## 输出格式（严格遵守）
- 标题: # 一级标题, ## 二级标题, ### 三级标题
- 加粗: **文字**
- 链接: [原文链接](https://...)  —— 必须用标准 markdown 链接格式
- 列表: 1. 或 -
- 每篇文章之间用空行分隔
- 不要输出任何 HTML 标签
"""


class SummarizeProcessor(BaseProcessor):
    """Calls an LLM API to generate a Chinese tech digest."""

    def __init__(
        self,
        api_key: str | None = None,
        api_base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        self._api_key = api_key or os.environ["API_KEY"]
        self._api_base_url = api_base_url or os.environ["API_BASE_URL"]
        self._model = model or os.environ.get("MODEL_NAME", "deepseek-chat")

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
                {"role": "system", "content": SYSTEM_PROMPT},
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
