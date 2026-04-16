import re
from datetime import datetime

import httpx

from demo_backend.config import Settings
from demo_backend.mock_data import build_mock_issue
from demo_backend.models import IssueItem, IssuePayload, NewsItem

ISSUE_SUBTITLE = "这里展示的是和现有 news_brief 前端一致的云端榜单前三条新闻。"
ISSUE_FOOTER = "当前后端复用了前端的取数方式：/api/ranks/sub/weibo，然后截取前 3 条。"


class NewsService:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def get_latest_issue(self, mock: bool) -> IssuePayload:
        if mock:
            return build_mock_issue()

        news_items = await self.fetch_cloud_news()
        issue_id = datetime.now().strftime("%Y-%m-%d")
        issue_items = [self._to_issue_item(item) for item in news_items[: self.settings.news_limit]]
        return IssuePayload(
            id=issue_id,
            title=f"{issue_id} 新闻速览 / 云端前三条",
            subtitle=ISSUE_SUBTITLE,
            footer=ISSUE_FOOTER,
            source_mode="cloud",
            items=issue_items,
        )

    async def fetch_cloud_news(self) -> list[NewsItem]:
        url = f"{self.settings.news_base_url.rstrip('/')}/api/ranks/{self.settings.news_board}/weibo"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.json()

        items = payload.get("list", []) if isinstance(payload, dict) else []
        return [self._normalize_news_item(item, index) for index, item in enumerate(items)]

    def _normalize_news_item(self, item: dict, index: int) -> NewsItem:
        score = item.get("viewsNum") or item.get("total_score") or item.get("score") or "0"
        source = item.get("source") or item.get("tag") or "AI 资讯"
        summary = item.get("summary") or item.get("brief") or item.get("description") or f"来自 {source} 的热门内容"
        return NewsItem(
            id=str(item.get("newsId") or item.get("id") or f"news-{index}"),
            news_id=self._safe_int(item.get("newsId") or item.get("id")),
            title=item.get("title") or "未命名新闻",
            summary=str(summary),
            url=item.get("url") or "",
            source=str(source),
            score=str(score),
            cover_url=item.get("coverUrl") or item.get("cover_url") or "",
            raw=item,
        )

    def _to_issue_item(self, item: NewsItem) -> IssueItem:
        raw_brief = item.raw.get("brief") if isinstance(item.raw, dict) else None
        headline = raw_brief.get("headline") if isinstance(raw_brief, dict) else item.title
        lead = raw_brief.get("lead") if isinstance(raw_brief, dict) else item.summary
        paragraphs = raw_brief.get("paragraphs") if isinstance(raw_brief, dict) else None
        expanded_body = self._normalize_paragraphs(paragraphs, lead)
        return IssueItem(
            id=item.id,
            news_id=item.news_id,
            source=item.source,
            headline=str(headline),
            warning=str(lead),
            article_url=item.url,
            cover_image=item.cover_url,
            expanded_body=expanded_body,
        )

    def _normalize_paragraphs(self, paragraphs: object, fallback_text: str) -> list[str]:
        if isinstance(paragraphs, list):
            normalized = [str(paragraph).strip() for paragraph in paragraphs if str(paragraph).strip()]
            if normalized:
                return normalized

        text = str(fallback_text or "").strip()
        if not text:
            return []
        parts = [chunk.strip() for chunk in re.split(r"(?<=[.!?。！？])", text) if chunk.strip()]
        return parts or [text]

    def _safe_int(self, value: object) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None
