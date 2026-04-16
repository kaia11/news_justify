from pathlib import Path

from fastapi import FastAPI

from demo_backend.config import ENV_FILE, PROJECT_ROOT, get_settings
from demo_backend.routes.news import router as news_router
from demo_backend.routes.pipeline import router as pipeline_router
from demo_backend.services.pipeline_service import DEBUG_OUTPUT_ROOT, GENERATED_IMAGE_ROOT, SCRIPT_DB_PATH

settings = get_settings()
app = FastAPI(title=settings.app_name)


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "app": settings.app_name,
        "project_root": str(PROJECT_ROOT),
        "env_file": str(ENV_FILE),
        "env_exists": Path(ENV_FILE).exists(),
        "mock": settings.mock,
        "news_base_url": settings.news_base_url,
        "news_board": settings.news_board,
        "use_shared_model": settings.use_shared_model,
        "data_dirs": {
            "debug_pipeline": str(DEBUG_OUTPUT_ROOT),
            "generated_images": str(GENERATED_IMAGE_ROOT),
            "pipeline_scripts_db": str(SCRIPT_DB_PATH),
        },
    }


app.include_router(news_router)
app.include_router(pipeline_router)
