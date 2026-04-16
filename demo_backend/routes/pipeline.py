from pathlib import Path

from fastapi import APIRouter, Depends, Query

from demo_backend.config import Settings, get_settings
from demo_backend.services.news_service import NewsService
from demo_backend.services.pipeline_service import DemoPipelineService
from demo_backend.services.shared_model_client import SharedModelClient
from demo_backend.services.web_research_service import WebResearchService
from wechat.backend.config import get_settings as get_wechat_settings
from wechat.backend.service import WechatPublishService

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])

# Manual safety switch: keep False while debugging image generation only.
# Set back to True to re-enable the publish_wechat=true publishing path.
WECHAT_PUBLISH_SWITCH = True


@router.post("/demo-run")
async def run_demo_pipeline(
    mock: bool | None = Query(default=None, description="true uses local mock data, false pulls the latest cloud top 3 first"),
    publish_wechat: bool = Query(default=False, description="true publishes each finished item into WeChat draft or publish flow internally"),
    settings: Settings = Depends(get_settings),
):
    news_service = NewsService(settings)
    issue = await news_service.get_latest_issue(mock=mock)

    wechat_publisher = None
    effective_publish_wechat = publish_wechat and WECHAT_PUBLISH_SWITCH
    if effective_publish_wechat:
        root_dir = Path(__file__).resolve().parents[2]
        wechat_root = root_dir / "wechat"
        wechat_publisher = WechatPublishService(get_wechat_settings(), str(wechat_root))

    pipeline_service = DemoPipelineService(
        SharedModelClient(settings),
        web_research_service=WebResearchService(settings),
        wechat_publisher=wechat_publisher,
    )
    return await pipeline_service.run(issue)
