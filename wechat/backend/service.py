from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4
from urllib.parse import urlparse

import httpx

from wechat.backend.config import WechatSettings


class WechatPublishService:
    def __init__(self, settings: WechatSettings, root_dir: str):
        self.settings = settings
        self.root_dir = Path(root_dir)
        self.project_root = self.root_dir.parent
        self.content_store_dir = self.project_root / "content_store"
        self.mock_dir = self.content_store_dir / "mock" / "wechat"
        self.issues_dir = self.content_store_dir / "issues"
        self.cover_path = self.mock_dir / "cover.jpg"
        self.body_dir = self.mock_dir / "body"

    def get_publish_info(self) -> dict:
        account_mode = self.settings.normalized_account_mode
        return {
            "platform": "wechat_official_account",
            "account_mode": account_mode,
            "root_dir": str(self.root_dir),
            "content_store_dir": str(self.content_store_dir),
            "mock_asset_dir": str(self.mock_dir),
            "issues_dir": str(self.issues_dir),
            "cover_image_path": str(self.cover_path),
            "cover_exists": self.cover_path.exists(),
            "body_image_dir": str(self.body_dir),
            "env_configured": {
                "app_id": bool(self.settings.wechat_app_id),
                "app_secret": bool(self.settings.wechat_app_secret),
                "token": bool(self.settings.wechat_token),
                "encoding_aes_key": bool(self.settings.wechat_encoding_aes_key),
            },
            "mode_behavior": self._describe_mode_behavior(account_mode),
            "official_steps": [
                "get access_token",
                "prepare shared assets under content_store/issues/<issue>/<item>/assets",
                "upload cover image for thumb_media_id",
                "upload body images for wechat urls",
                "create draft",
                "submit publish when supported",
                "query publish status when supported",
            ],
        }

    def build_mock_draft_task(self) -> dict:
        account_mode = self.settings.normalized_account_mode
        task_id = f"wechat_draft_{uuid4().hex[:10]}"
        result = {
            "task_id": task_id,
            "platform": "wechat_official_account",
            "account_mode": account_mode,
            "title": self._mock_title(),
            "author": self.settings.wechat_author,
            "digest": self.settings.wechat_default_digest,
            "content_html": self.build_mock_html([]),
            "cover_image_path": str(self.cover_path),
            "cover_exists": self.cover_path.exists(),
            "body_images": self._list_body_images(),
            "shared_mock_dir": str(self.mock_dir),
        }
        if account_mode == "enterprise":
            result["status"] = "ready_for_auto_publish"
            result["next_backend_calls"] = [
                "get_access_token()",
                "prepare shared assets",
                "upload_thumb(cover.jpg)",
                "upload_body_image(...)",
                "create_draft(...)",
                "submit_publish(...) optional",
            ]
        else:
            result["status"] = "ready_for_draft_only"
            result["manual_steps"] = self._personal_manual_steps()
            result["next_backend_calls"] = [
                "get_access_token()",
                "prepare shared assets",
                "upload_thumb(cover.jpg)",
                "upload_body_image(...)",
                "create_draft(...)",
            ]
        return result

    def get_api_placeholders(self) -> dict:
        return {
            "where_to_get": {
                "console": "https://mp.weixin.qq.com/",
                "app_id_and_secret": "登录公众号后台 -> 设置与开发 -> 开发接口管理/开发设置",
                "ip_whitelist": "同一个公众号后台里配置开发者 IP 白名单",
            },
            "shared_storage_layout": {
                "mock_assets": "content_store/mock/wechat/",
                "shared_issue_assets": "content_store/issues/<issue_id>/<item_id>/assets/",
                "wechat_publish_workspace": "content_store/issues/<issue_id>/<item_id>/platforms/wechat/",
            },
            "env_fields": [
                "WECHAT_APP_ID",
                "WECHAT_APP_SECRET",
                "WECHAT_TOKEN",
                "WECHAT_ENCODING_AES_KEY",
                "WECHAT_ACCOUNT_MODE",
            ],
            "account_mode_examples": {
                "personal": "个人号半自动模式，自动上传素材并创建草稿，人工去后台点击发布",
                "enterprise": "企业或可发布账号，自动上传素材、创建草稿并可继续自动发布",
            },
            "official_api_flow": [
                "GET /cgi-bin/token",
                "POST /cgi-bin/material/add_material?type=thumb",
                "POST /cgi-bin/media/uploadimg",
                "POST /cgi-bin/draft/add",
                "POST /cgi-bin/freepublish/submit",
                "POST /cgi-bin/freepublish/get",
            ],
        }

    async def create_mock_draft_with_wechat(self, submit_publish: bool = False) -> dict:
        self._ensure_cover_exists()
        workspace_dir = self._ensure_platform_workspace_dir("mock_issue", "mock_item")
        shared_asset_dir = self._ensure_shared_asset_dir("mock_issue", "mock_item")
        local_cover_path = shared_asset_dir / "cover" / self.cover_path.name
        local_cover_path.parent.mkdir(parents=True, exist_ok=True)
        local_cover_path.write_bytes(self.cover_path.read_bytes())

        body_paths: list[Path] = []
        for image_path in self._list_body_image_paths():
            target = shared_asset_dir / "body" / image_path.name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(image_path.read_bytes())
            body_paths.append(target)

        self._write_json(
            shared_asset_dir / "article.json",
            {
                "title": self._mock_title(),
                "digest": self.settings.wechat_default_digest,
                "author": self.settings.wechat_author,
                "source_url": "https://example.com/mock/xinzhiyuan-ai-marketing",
                "mode": self.settings.normalized_account_mode,
            },
        )

        return await self._publish_article(
            workspace_dir=workspace_dir,
            shared_asset_dir=shared_asset_dir,
            title=self._mock_title(),
            author=self.settings.wechat_author,
            digest=self.settings.wechat_default_digest,
            source_url="https://example.com/mock/xinzhiyuan-ai-marketing",
            cover_path=local_cover_path,
            body_paths=body_paths,
            html_builder=self.build_mock_html,
            submit_publish=submit_publish,
        )

    async def publish_pipeline_article(
        self,
        issue_id: str,
        item_id: str,
        title: str,
        digest: str,
        source_name: str,
        source_url: str,
        social_caption: str,
        wechat_article: dict[str, Any],
        context_notes: list[str],
        risk_notes: list[str],
        cover_image_candidates: list[str],
        body_image_candidates: list[str],
        submit_publish: bool = False,
    ) -> dict:
        workspace_dir = self._ensure_platform_workspace_dir(issue_id, item_id)
        shared_asset_dir = self._ensure_shared_asset_dir(issue_id, item_id)

        cover_path = await self._materialize_first_available_asset(
            cover_image_candidates,
            shared_asset_dir / "cover" / "cover",
        )
        if not cover_path:
            if self.cover_path.exists():
                cover_path = shared_asset_dir / "cover" / self.cover_path.name
                cover_path.parent.mkdir(parents=True, exist_ok=True)
                cover_path.write_bytes(self.cover_path.read_bytes())
            else:
                raise RuntimeError("没有可用的公众号封面图，也没有默认 cover.jpg。")

        body_paths = await self._materialize_asset_list(
            body_image_candidates,
            shared_asset_dir / "body",
        )
        if not body_paths:
            copied_cover = shared_asset_dir / "body" / cover_path.name
            copied_cover.parent.mkdir(parents=True, exist_ok=True)
            copied_cover.write_bytes(cover_path.read_bytes())
            body_paths = [copied_cover]

        preview_html = self.build_pipeline_html(
            title=title,
            source_name=source_name,
            social_caption=social_caption,
            wechat_article=wechat_article,
            context_notes=context_notes,
            risk_notes=risk_notes,
            body_image_urls=[],
        )
        (workspace_dir / "preview.html").write_text(preview_html, encoding="utf-8")
        self._write_json(
            shared_asset_dir / "article.json",
            {
                "issue_id": issue_id,
                "item_id": item_id,
                "title": title,
                "digest": digest,
                "source_name": source_name,
                "source_url": source_url,
                "social_caption": social_caption,
                "wechat_article": wechat_article,
                "context_notes": context_notes,
                "risk_notes": risk_notes,
                "cover_path": str(cover_path),
                "body_paths": [str(path) for path in body_paths],
                "mode": self.settings.normalized_account_mode,
            },
        )

        return await self._publish_article(
            workspace_dir=workspace_dir,
            shared_asset_dir=shared_asset_dir,
            title=title,
            author=self.settings.wechat_author,
            digest=(digest or social_caption or title)[:120],
            source_url=source_url or "",
            cover_path=cover_path,
            body_paths=body_paths,
            html_builder=lambda body_urls: self.build_pipeline_html(
                title=title,
                source_name=source_name,
                social_caption=social_caption,
                wechat_article=wechat_article,
                context_notes=context_notes,
                risk_notes=risk_notes,
                body_image_urls=body_urls,
            ),
            submit_publish=submit_publish,
        )

    async def query_publish_status(self, publish_id: str, article_id: str = "") -> dict:
        if self.settings.normalized_account_mode == "personal":
            return {
                "status": "not_supported_in_personal_mode",
                "account_mode": "personal",
                "message": "personal 模式只创建草稿，不产生 publish_id，因此没有发布状态可查。",
            }
        self._ensure_required_config()
        access_token = await self.get_access_token()
        return await self.get_publish_status(access_token, publish_id, article_id)

    async def get_access_token(self) -> str:
        url = "https://api.weixin.qq.com/cgi-bin/token"
        params = {
            "grant_type": "client_credential",
            "appid": self.settings.wechat_app_id,
            "secret": self.settings.wechat_app_secret,
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        self._raise_on_wechat_error(payload, "获取 access_token 失败")
        token = payload.get("access_token")
        if not token:
            raise RuntimeError("微信没有返回 access_token。")
        return str(token)

    async def upload_thumb(self, access_token: str, image_path: Path) -> str:
        url = f"https://api.weixin.qq.com/cgi-bin/material/add_material?access_token={access_token}&type=thumb"
        mime_type = self._guess_image_content_type(image_path)
        with image_path.open("rb") as image_file:
            files = {"media": (image_path.name, image_file, mime_type)}
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(url, files=files)
                response.raise_for_status()
                payload = response.json()
        self._raise_on_wechat_error(payload, "上传封面图失败")
        media_id = payload.get("media_id")
        if not media_id:
            raise RuntimeError("微信没有返回 thumb media_id。")
        return str(media_id)

    async def upload_body_image(self, access_token: str, image_path: Path) -> str:
        url = f"https://api.weixin.qq.com/cgi-bin/media/uploadimg?access_token={access_token}"
        mime_type = self._guess_image_content_type(image_path)
        with image_path.open("rb") as image_file:
            files = {"media": (image_path.name, image_file, mime_type)}
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(url, files=files)
                response.raise_for_status()
                payload = response.json()
        self._raise_on_wechat_error(payload, "上传正文图片失败")
        image_url = payload.get("url")
        if not image_url:
            raise RuntimeError("微信没有返回正文图片 URL。")
        return str(image_url)

    async def create_draft(
        self,
        access_token: str,
        title: str,
        author: str,
        digest: str,
        content_html: str,
        thumb_media_id: str,
        content_source_url: str,
    ) -> dict[str, Any]:
        url = f"https://api.weixin.qq.com/cgi-bin/draft/add?access_token={access_token}"
        payload = {
            "articles": [
                {
                    "title": title,
                    "author": author,
                    "digest": digest,
                    "content": content_html,
                    "thumb_media_id": thumb_media_id,
                    "content_source_url": content_source_url,
                    "need_open_comment": 0,
                    "only_fans_can_comment": 0,
                }
            ]
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            result = response.json()
        self._raise_on_wechat_error(result, "创建草稿失败")
        return result

    async def submit_publish(self, access_token: str, media_id: str) -> dict[str, Any]:
        url = f"https://api.weixin.qq.com/cgi-bin/freepublish/submit?access_token={access_token}"
        payload = {"media_id": media_id}
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            result = response.json()
        self._raise_on_wechat_error(result, "提交发布失败")
        return result

    async def get_publish_status(self, access_token: str, publish_id: str, article_id: str = "") -> dict[str, Any]:
        url = f"https://api.weixin.qq.com/cgi-bin/freepublish/get?access_token={access_token}"
        payload: dict[str, Any] = {"publish_id": publish_id}
        if article_id:
            payload["article_id"] = article_id
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            result = response.json()
        self._raise_on_wechat_error(result, "查询发布状态失败")
        return result

    def build_mock_html(self, body_image_urls: list[str]) -> str:
        sections = [
            "<h1>国产AI营销工具来了！工作流被Agent重构，营销物料一键即出</h1>",
            "<p>这是一篇用于微信公众号发布流程演示的 mock 图文，内容结构完整，可直接用于测试。</p>",
            "<p><strong>导语：</strong>AI 正在把营销工作从零散的工具协作，推进到统一的 Agent 工作流。</p>",
            "<h2>一、行业现象</h2>",
            "<p>越来越多营销平台开始把洞察、选号、脚本生成和投放复盘连接成一条链路，试图缩短内容生产周期。</p>",
            "<h2>二、产品价值</h2>",
            "<p>对演示项目来说，这类新闻非常适合被改写为事实核查、漫画生成和自动分发的标准测试样本。</p>",
        ]
        for image_url in body_image_urls:
            sections.append(f'<p><img src="{image_url}" /></p>')
        sections.extend(
            [
                "<h2>三、演示说明</h2>",
                "<p>企业模式下，后端会把图片上传到微信，再创建草稿并可继续提交发布。个人模式下，后端也会自动创建草稿，但最后一步发布由你在公众号后台手动完成。</p>",
                "<p>以上内容仅用于接口链路和排版流程演示。</p>",
            ]
        )
        return "".join(sections)

    def build_pipeline_html(
        self,
        title: str,
        source_name: str,
        social_caption: str,
        wechat_article: dict[str, Any],
        context_notes: list[str],
        risk_notes: list[str],
        body_image_urls: list[str],
    ) -> str:
        lead = self._escape_html(self._strip_markdown_emphasis(str(wechat_article.get("lead") or social_caption)))
        ending = self._escape_html(self._strip_markdown_emphasis(str(wechat_article.get("ending") or "")))

        wrapper_style = "max-width:760px;margin:0 auto;background:#F3F3F3;padding:24px 20px;color:#3D3F43;font-size:16px;line-height:1.95;font-family:'PingFang SC','Hiragino Sans GB','Microsoft YaHei','Helvetica Neue',Arial,sans-serif;"
        paragraph_style = "margin:0 0 28px;"
        paragraph_last_style = "margin:0 0 56px;"
        chapter_no_style = "margin:0 0 28px;font-family:Georgia,'Times New Roman',serif;font-size:46px;line-height:1;color:#3D3F43;"
        title_bar_style = "display:inline-block;margin:0 0 28px;background:#35383E;color:#FFFFFF;font-size:20px;line-height:1.45;padding:5px 9px;"
        highlight_style = "border-bottom:2px dashed #7FE0B0;"
        image_style = "display:block;width:100%;height:auto;border-radius:8px;"

        sections = [f"<div style=\"{wrapper_style}\">", f"<p style=\"{paragraph_style}\">{lead}</p>"]

        for idx, image_url in enumerate(body_image_urls):
            p_style = paragraph_last_style if idx == len(body_image_urls) - 1 else paragraph_style
            sections.append(f'<p style="{p_style}"><img style="{image_style}" src="{image_url}" /></p>')

        article_sections = wechat_article.get("sections")
        if isinstance(article_sections, list):
            for index, section in enumerate(article_sections, start=1):
                if not isinstance(section, dict):
                    continue

                chapter_no = f"{index:02d}"
                heading = self._escape_html(self._strip_markdown_emphasis(str(section.get("heading") or f"观点 {index}")))
                sections.append(f"<p style=\"{chapter_no_style}\">{chapter_no}</p>")
                sections.append(f"<p style=\"{title_bar_style}\">{heading}</p>")

                summary = self._strip_markdown_emphasis(str(section.get("summary") or "").strip())
                key_point = self._strip_markdown_emphasis(str(section.get("key_point") or "").strip())
                explain = self._strip_markdown_emphasis(str(section.get("explain") or "").strip())
                transition = self._strip_markdown_emphasis(str(section.get("transition") or "").strip())
                legacy_content = self._strip_markdown_emphasis(str(section.get("content") or "").strip())
                sentence_endings = ("。", "！", "？", "；", ";")

                content_rows: list[tuple[str, bool]] = []
                if summary:
                    content_rows.append((summary, True))

                body_parts: list[str] = []
                if key_point:
                    body_parts.append(key_point)
                if explain:
                    for line in self._split_section_lines(explain):
                        normalized_line = self._strip_markdown_emphasis(line.strip())
                        if not normalized_line:
                            continue
                        term_hint = self._split_term_hint_line(normalized_line)
                        if term_hint:
                            term, explain_text = term_hint
                            body_parts.append(f"{term}：{explain_text}")
                        else:
                            body_parts.append(normalized_line)
                transition_line = ""
                if transition:
                    transition_line = re.sub(
                        r"^(下一步看|接下来(?:我们)?看|再看|然后看|继续看|下一个问题|下一段)\s*[：:，,\s]*",
                        "",
                        transition.strip(),
                    ).strip()

                if body_parts:
                    merged_body = ""
                    for part in body_parts:
                        text_part = part.strip()
                        if not text_part:
                            continue
                        if merged_body and not merged_body.endswith(sentence_endings):
                            merged_body += "。"
                        merged_body += text_part
                    if merged_body and not merged_body.endswith(sentence_endings):
                        merged_body += "。"
                    if merged_body:
                        content_rows.append((merged_body, False))
                if transition_line:
                    if not transition_line.endswith(sentence_endings):
                        transition_line += "。"
                    content_rows.append((transition_line, False))

                if not content_rows and legacy_content:
                    for line in self._split_section_lines(legacy_content):
                        normalized_line = self._strip_markdown_emphasis(line.strip())
                        if not normalized_line:
                            continue
                        is_highlight = "【重点】" in normalized_line
                        text_line = normalized_line.replace("【重点】", "").strip() if is_highlight else normalized_line
                        if self._is_transition_line(text_line):
                            text_line = re.sub(
                                r"^(下一步看|接下来(?:我们)?看|再看|然后看|继续看|下一个问题|下一段)\s*[：:，,\s]*",
                                "",
                                text_line,
                            ).strip()
                            if not text_line:
                                continue
                        term_hint = self._split_term_hint_line(text_line)
                        if term_hint:
                            term, explain_text = term_hint
                            text_line = f"{term}：{explain_text}"
                        content_rows.append((text_line, is_highlight))

                for row_index, (text, use_highlight) in enumerate(content_rows):
                    margin_style = paragraph_last_style if row_index == len(content_rows) - 1 else paragraph_style
                    escaped_text = self._escape_html(text)
                    if use_highlight:
                        sections.append(f"<p style=\"{margin_style}\"><span style=\"{highlight_style}\">{escaped_text}</span></p>")
                    else:
                        sections.append(f"<p style=\"{margin_style}\">{escaped_text}</p>")

        if ending:
            sections.append(f"<p style=\"{title_bar_style}\">结语</p>")
            sections.append(f"<p style=\"margin:0;\"><span style=\"{highlight_style}\">{ending}</span></p>")
        sections.append("</div>")
        return "".join(sections)

    def _split_section_lines(self, content: str) -> list[str]:
        text = str(content or "").strip()
        if not text:
            return []
        by_newline = [piece.strip() for piece in re.split(r"\n+", text) if piece.strip()]
        if len(by_newline) > 1:
            return by_newline
        return [piece.strip() for piece in re.split(r"(?<=[。！？!?；;])\s*", text) if piece.strip()]

    def _is_transition_line(self, line: str) -> bool:
        normalized = line.strip()
        transition_prefixes = ("下一步看", "接下来", "再看", "然后看", "继续看", "下一个问题", "下一段")
        return any(normalized.startswith(prefix) for prefix in transition_prefixes)

    def _split_term_hint_line(self, line: str) -> tuple[str, str] | None:
        normalized = line.strip()
        if "【重点】" in normalized:
            return None
        if "=" not in normalized:
            return None
        if normalized.count("=") != 1:
            return None
        term, explanation = [value.strip() for value in normalized.split("=", 1)]
        if not (term and explanation):
            return None
        if len(term) > 20 or len(explanation) > 60:
            return None
        return term, explanation

    def _strip_markdown_emphasis(self, text: str) -> str:
        normalized = str(text or "")
        normalized = re.sub(r"\*\*(.*?)\*\*", r"\1", normalized)
        normalized = re.sub(r"__(.*?)__", r"\1", normalized)
        return normalized.strip()

    async def _publish_article(
        self,
        workspace_dir: Path,
        shared_asset_dir: Path,
        title: str,
        author: str,
        digest: str,
        source_url: str,
        cover_path: Path,
        body_paths: list[Path],
        html_builder: Callable[[list[str]], str],
        submit_publish: bool,
    ) -> dict:
        self._ensure_required_config()
        self._ensure_file_exists(cover_path, "封面图")

        access_token = await self.get_access_token()
        thumb_media_id = await self.upload_thumb(access_token, cover_path)

        uploaded_body_images = []
        body_image_urls = []
        for image_path in body_paths:
            image_url = await self.upload_body_image(access_token, image_path)
            uploaded_body_images.append(
                {
                    "file_name": image_path.name,
                    "absolute_path": str(image_path),
                    "wechat_url": image_url,
                }
            )
            body_image_urls.append(image_url)

        content_html = html_builder(body_image_urls)
        (workspace_dir / "final.html").write_text(content_html, encoding="utf-8")

        draft_result = await self.create_draft(
            access_token=access_token,
            title=title,
            author=author,
            digest=digest,
            content_html=content_html,
            thumb_media_id=thumb_media_id,
            content_source_url=source_url,
        )

        response = {
            "status": "draft_created",
            "account_mode": self.settings.normalized_account_mode,
            "publish_mode": "manual_after_draft" if self.settings.normalized_account_mode == "personal" else "draft_only",
            "thumb_media_id": thumb_media_id,
            "uploaded_body_images": uploaded_body_images,
            "draft_result": draft_result,
            "content_html": content_html,
            "cover_image_path": str(cover_path),
            "shared_asset_dir": str(shared_asset_dir),
            "workspace_dir": str(workspace_dir),
        }

        if self.settings.normalized_account_mode == "personal":
            response["manual_steps"] = self._personal_manual_steps()
            response["note"] = "personal 模式下，后端已经自动把内容导入草稿箱。接下来请登录公众号后台，在草稿箱里手动点击发布。"
            self._write_json(workspace_dir / "publish_result.json", response)
            return response

        if submit_publish:
            publish_result = await self.submit_publish(access_token, draft_result["media_id"])
            response["publish_result"] = publish_result
            response["status"] = "publish_submitted"
            response["publish_mode"] = "auto_publish"

        self._write_json(workspace_dir / "publish_result.json", response)
        return response

    async def _materialize_first_available_asset(self, candidates: list[str], target_stem: Path) -> Path | None:
        for index, candidate in enumerate(candidates):
            if not candidate:
                continue
            suffix_hint = f"_{index + 1}" if index else ""
            path = await self._materialize_asset(candidate, target_stem.with_name(target_stem.name + suffix_hint))
            if path:
                return path
        return None

    async def _materialize_asset_list(self, candidates: list[str], target_dir: Path) -> list[Path]:
        saved: list[Path] = []
        for index, candidate in enumerate(candidates, start=1):
            if not candidate:
                continue
            materialized = await self._materialize_asset(candidate, target_dir / f"image_{index}")
            if materialized:
                saved.append(materialized)
        return saved

    async def _materialize_asset(self, candidate: str, target_stem: Path) -> Path | None:
        normalized = str(candidate or "").strip()
        if not normalized:
            return None

        if normalized.startswith("data:image/"):
            return self._write_data_url_image(normalized, target_stem)

        local_path = Path(normalized)
        if local_path.exists() and local_path.is_file():
            target_path = target_stem.with_suffix(local_path.suffix or ".png")
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(local_path.read_bytes())
            return target_path

        if normalized.startswith("http://") or normalized.startswith("https://"):
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.get(normalized)
                response.raise_for_status()
                content_type = response.headers.get("Content-Type", "")
                suffix = self._guess_suffix_from_url_or_type(normalized, content_type)
                target_path = target_stem.with_suffix(suffix)
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(response.content)
                return target_path

        return None

    def _write_data_url_image(self, data_url: str, target_stem: Path) -> Path:
        match = re.match(r"^data:image/(?P<fmt>[a-zA-Z0-9.+-]+);base64,(?P<data>.+)$", data_url)
        if not match:
            raise RuntimeError("不支持的 data URL 图片格式。")
        image_format = match.group("fmt").lower()
        base64_data = match.group("data")
        image_bytes = base64.b64decode(base64_data)
        suffix = ".png" if image_format == "png" else f".{image_format}"
        target_path = target_stem.with_suffix(suffix)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(image_bytes)
        return target_path

    def _guess_suffix_from_url_or_type(self, url: str, content_type: str) -> str:
        parsed = urlparse(url)
        suffix = Path(parsed.path).suffix.lower()
        if suffix in {".jpg", ".jpeg", ".png", ".webp"}:
            return suffix
        normalized_type = str(content_type or "").lower()
        if "jpeg" in normalized_type or "jpg" in normalized_type:
            return ".jpg"
        if "png" in normalized_type:
            return ".png"
        if "webp" in normalized_type:
            return ".webp"
        return ".png"

    def _mock_title(self) -> str:
        return "国产AI营销工具来了！工作流被Agent重构，营销物料一键即出"

    def _describe_mode_behavior(self, account_mode: str) -> dict:
        if account_mode == "enterprise":
            return {
                "summary": "企业模式：自动上传素材、创建草稿，可选自动发布，可查询发布状态。",
                "direct_publish_supported": True,
                "draft_creation_supported": True,
            }
        return {
            "summary": "个人模式：自动上传素材并创建草稿，最后一步去公众号后台手动点击发布。",
            "direct_publish_supported": False,
            "draft_creation_supported": True,
        }

    def _personal_manual_steps(self) -> list[str]:
        return [
            "打开公众号后台并进入草稿箱。",
            "找到刚刚由接口创建的图文草稿。",
            "检查封面、正文图片和排版是否正常。",
            "手动点击发布。",
        ]

    def _list_body_images(self) -> list[dict[str, Any]]:
        return [
            {
                "file_name": image_path.name,
                "absolute_path": str(image_path),
                "exists": image_path.exists(),
            }
            for image_path in self._list_body_image_paths()
        ]

    def _list_body_image_paths(self) -> list[Path]:
        if not self.body_dir.exists():
            return []
        return sorted(
            [
                path
                for path in self.body_dir.iterdir()
                if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
            ]
        )

    def _guess_image_content_type(self, image_path: Path) -> str:
        suffix = image_path.suffix.lower()
        if suffix in {".jpg", ".jpeg"}:
            return "image/jpeg"
        if suffix == ".png":
            return "image/png"
        if suffix == ".webp":
            return "image/webp"
        return "application/octet-stream"

    def _ensure_required_config(self) -> None:
        if not self.settings.wechat_app_id or not self.settings.wechat_app_secret:
            raise RuntimeError("微信公众号 AppID / AppSecret 未配置。")

    def _ensure_cover_exists(self) -> None:
        if not self.cover_path.exists():
            raise RuntimeError(f"封面图不存在：{self.cover_path}")

    def _ensure_file_exists(self, path: Path, label: str) -> None:
        if not path.exists():
            raise RuntimeError(f"{label}不存在：{path}")

    def _ensure_shared_asset_dir(self, issue_id: str, item_id: str) -> Path:
        safe_issue = self._safe_name(issue_id)
        safe_item = self._safe_name(item_id)
        asset_dir = self.issues_dir / safe_issue / safe_item / "assets"
        asset_dir.mkdir(parents=True, exist_ok=True)
        return asset_dir

    def _ensure_platform_workspace_dir(self, issue_id: str, item_id: str) -> Path:
        safe_issue = self._safe_name(issue_id)
        safe_item = self._safe_name(item_id)
        workspace_dir = self.issues_dir / safe_issue / safe_item / "platforms" / "wechat"
        workspace_dir.mkdir(parents=True, exist_ok=True)
        return workspace_dir

    def _safe_name(self, value: str) -> str:
        normalized = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(value or "workspace").strip())
        return normalized[:80] or "workspace"

    def _escape_html(self, text: str) -> str:
        return (
            str(text or "")
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _raise_on_wechat_error(self, payload: dict[str, Any], default_message: str) -> None:
        errcode = payload.get("errcode")
        if errcode not in (None, 0):
            errmsg = payload.get("errmsg") or default_message
            raise RuntimeError(f"{default_message}：errcode={errcode}, errmsg={errmsg}")

