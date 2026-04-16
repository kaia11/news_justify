from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class WechatSettings(BaseSettings):
    wechat_app_id: str = Field(default="", alias="WECHAT_APP_ID")
    wechat_app_secret: str = Field(default="", alias="WECHAT_APP_SECRET")
    wechat_token: str = Field(default="", alias="WECHAT_TOKEN")
    wechat_encoding_aes_key: str = Field(default="", alias="WECHAT_ENCODING_AES_KEY")
    wechat_author: str = Field(default="Justify Demo", alias="WECHAT_AUTHOR")
    wechat_default_digest: str = Field(
        default="这是一篇由新闻流水线自动生成的公众号演示草稿。",
        alias="WECHAT_DEFAULT_DIGEST",
    )
    wechat_auto_publish: bool = Field(default=False, alias="WECHAT_AUTO_PUBLISH")
    wechat_account_mode: str = Field(default="personal", alias="WECHAT_ACCOUNT_MODE")
    wechat_enable_mock: bool = Field(default=True, alias="WECHAT_ENABLE_MOCK")

    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parents[1] / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @property
    def normalized_account_mode(self) -> str:
        value = (self.wechat_account_mode or "personal").strip().lower()
        if value not in {"personal", "enterprise"}:
            raise ValueError("WECHAT_ACCOUNT_MODE must be either 'personal' or 'enterprise'.")
        return value



def get_settings() -> WechatSettings:
    return WechatSettings()
