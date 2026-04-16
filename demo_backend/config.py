from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    app_name: str = "news-pipeline-demo"
    app_host: str = "0.0.0.0"
    app_port: int = 8080
    mock: bool = True

    news_base_url: str = "http://8.135.4.46:8000"
    news_board: str = "sub"
    news_limit: int = 3

    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    dashscope_text_model: str = "qwen-plus"
    dashscope_image_model: str = ""

    use_shared_model: bool = True
    shared_model_base_url: str = ""
    shared_model_api_key: str = ""
    shared_model_name: str = ""
    shared_image_model_name: str = ""

    text_model_base_url: str = ""
    text_model_api_key: str = ""
    text_model_name: str = ""
    image_model_base_url: str = ""
    image_model_api_key: str = ""
    image_model_name: str = ""

    bocha_api_key: str = ""
    factcheck_enable_web_search: bool = True
    factcheck_search_provider: str = "bocha"
    factcheck_max_queries_per_claim: int = 5
    factcheck_max_results_per_query: int = 5
    factcheck_search_lang_mode: str = "auto"
    factcheck_news_only: bool = True

    douyin_open_base_url: str = "https://open.douyin.com"
    douyin_client_key: str = ""
    douyin_client_secret: str = ""
    douyin_redirect_uri: str = ""

    model_config = SettingsConfigDict(env_file=str(ENV_FILE), env_file_encoding="utf-8", extra="ignore")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
