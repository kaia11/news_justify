from fastapi import APIRouter, Depends, Query

from demo_backend.config import Settings, get_settings
from demo_backend.services.news_service import NewsService

router = APIRouter(prefix="/api/news", tags=["news"])


@router.get("/issue")
async def get_latest_issue(
    mock: bool | None = Query(default=None, description="true uses local mock data, false pulls from /api/ranks/sub/weibo"),
    settings: Settings = Depends(get_settings),
):
    service = NewsService(settings)
    return await service.get_latest_issue(mock=mock)
