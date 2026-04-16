from pathlib import Path

from fastapi import FastAPI, HTTPException, Query

from wechat.backend.config import get_settings
from wechat.backend.service import WechatPublishService

settings = get_settings()
app = FastAPI(title="wechat-publish-demo")


def get_service() -> WechatPublishService:
    root_dir = Path(__file__).resolve().parents[1]
    return WechatPublishService(settings, str(root_dir))


def ensure_mock_enabled() -> None:
    if not settings.wechat_enable_mock:
        raise HTTPException(status_code=403, detail="WeChat mock publishing is disabled by WECHAT_ENABLE_MOCK=false.")


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "wechat_publish_demo",
        "app_id_configured": bool(settings.wechat_app_id),
        "app_secret_configured": bool(settings.wechat_app_secret),
        "mock_enabled": settings.wechat_enable_mock,
    }


@app.get("/api/wechat/publish/info")
def get_publish_info() -> dict:
    info = get_service().get_publish_info()
    info["mock_enabled"] = settings.wechat_enable_mock
    return info


@app.get("/api/wechat/publish/api-placeholders")
def get_api_placeholders() -> dict:
    return get_service().get_api_placeholders()


@app.post("/api/wechat/publish/mock-preview")
def create_mock_preview() -> dict:
    ensure_mock_enabled()
    return get_service().build_mock_draft_task()


@app.post("/api/wechat/publish/mock-draft")
async def create_mock_draft() -> dict:
    ensure_mock_enabled()
    return await get_service().create_mock_draft_with_wechat(submit_publish=False)


@app.post("/api/wechat/publish/mock-direct")
async def create_mock_direct_publish() -> dict:
    ensure_mock_enabled()
    return await get_service().create_mock_draft_with_wechat(submit_publish=True)


@app.get("/api/wechat/publish/status")
async def get_publish_status(
    publish_id: str = Query(..., description="wechat publish_id"),
    article_id: str = Query("", description="optional article id"),
) -> dict:
    return await get_service().query_publish_status(publish_id=publish_id, article_id=article_id)
