from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from demo_backend.config import Settings


@dataclass
class ModelRuntimeConfig:
    base_url: str
    api_key: str
    model_name: str
    timeout_seconds: float


STAGE_RESEARCH = "research"
STAGE_FACTCHECK = "factcheck"
STAGE_WRITER = "writer"
STAGE_IMAGE_PROMPT = "image_prompt"
STAGE_WECHAT_ARTICLE = "wechat_article"
STAGE_MODEL_FIELD_MAP = {
    STAGE_RESEARCH: "model_research_name",
    STAGE_FACTCHECK: "model_factcheck_name",
    STAGE_WRITER: "model_writer_name",
    STAGE_IMAGE_PROMPT: "model_image_prompt_name",
    STAGE_WECHAT_ARTICLE: "model_wechat_article_name",
}


class SharedModelClient:
    """Model client for real model calls.

    Conventions:
    1. Text stages still use the OpenAI-compatible chat/completions API.
    2. DashScope image models do not use /images/generations.
    3. wan2.x and qwen-image image models use the native DashScope image APIs.
    4. Local reference images are supported through reference_image_path.
    5. Even if .env uses compatible-mode/v1, image requests switch back to the DashScope root API.
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def configured(self) -> bool:
        return self.text_configured

    @property
    def text_configured(self) -> bool:
        config = self._get_text_config()
        return bool(config)

    @property
    def image_configured(self) -> bool:
        config = self._get_image_config()
        return bool(config)

    @property
    def strategy_label(self) -> str:
        if self._has_stage_model_overrides():
            return "Stage routing mode: text stages use per-stage model selection and the image stage keeps its own model config."
        if self.settings.dashscope_api_key:
            return "DashScope mode: text uses qwen-plus by default and image generation uses the DashScope image API."
        if self.settings.use_shared_model:
            return "Shared mode: text and image stages share one model service configuration."
        return "Split mode: text model and image model are configured independently."

    @property
    def strategy_details(self) -> dict[str, str]:
        details = {stage: self._resolve_stage_model_name(stage) for stage in STAGE_MODEL_FIELD_MAP}
        details["image"] = self._get_resolved_model_name(self._get_image_config())
        return details

    async def generate_text(self, system_prompt: str, user_prompt: str, temperature: float = 0.3) -> str:
        config = self._require_text_config()
        return await self._generate_text_with_config(config, system_prompt, user_prompt, temperature)

    async def generate_text_for_stage(
        self,
        stage: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
    ) -> str:
        config = self._require_text_config_for_stage(stage)
        return await self._generate_text_with_config(config, system_prompt, user_prompt, temperature)

    async def generate_json(self, system_prompt: str, user_prompt: str, temperature: float = 0.2) -> dict[str, Any]:
        config = self._require_text_config()
        return await self._generate_json_with_config(config, system_prompt, user_prompt, temperature)

    async def generate_json_for_stage(
        self,
        stage: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        config = self._require_text_config_for_stage(stage)
        return await self._generate_json_with_config(config, system_prompt, user_prompt, temperature)

    async def _generate_text_with_config(
        self,
        config: ModelRuntimeConfig,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
    ) -> str:
        payload = {
            "model": config.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
        }
        response = await self._post_json(
            config.base_url,
            "/chat/completions",
            payload,
            config.api_key,
            timeout_seconds=config.timeout_seconds,
        )
        return self._extract_text_content(response)

    async def _generate_json_with_config(
        self,
        config: ModelRuntimeConfig,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
    ) -> dict[str, Any]:
        payload = {
            "model": config.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        response = await self._post_json(
            config.base_url,
            "/chat/completions",
            payload,
            config.api_key,
            timeout_seconds=config.timeout_seconds,
        )
        text = self._extract_text_content(response)
        return self._parse_json_text(text)

    async def generate_image(
        self,
        prompt: str,
        width: int = 1024,
        height: int = 1440,
        reference_image_path: str = "",
    ) -> dict[str, Any]:
        config = self._require_image_config()

        if self._is_dashscope_image_model(config):
            try:
                response = await self._generate_dashscope_image(config, prompt, width, height, reference_image_path)
                response.setdefault("original_prompt", prompt)
                response.setdefault("safe_retry_prompt", "")
                response.setdefault("used_safe_retry", False)
                return response
            except RuntimeError as exc:
                if not self._is_dashscope_content_filter_error(exc):
                    raise

                safer_prompt = self._build_dashscope_safe_retry_prompt(prompt)
                response = await self._generate_dashscope_image(config, safer_prompt, width, height, reference_image_path)
                response["original_prompt"] = prompt
                response["safe_retry_prompt"] = safer_prompt
                response["used_safe_retry"] = True
                if not response.get("revised_prompt"):
                    response["revised_prompt"] = safer_prompt
                return response

        payload = {
            "model": config.model_name,
            "prompt": prompt,
            "size": f"{width}x{height}",
        }
        response = await self._post_json(
            config.base_url,
            "/images/generations",
            payload,
            config.api_key,
            timeout_seconds=config.timeout_seconds,
        )
        result = self._extract_image_content(response)
        result.setdefault("original_prompt", prompt)
        result.setdefault("safe_retry_prompt", "")
        result.setdefault("used_safe_retry", False)
        return result

    async def _generate_dashscope_image(
        self,
        config: ModelRuntimeConfig,
        prompt: str,
        width: int,
        height: int,
        reference_image_path: str = "",
    ) -> dict[str, Any]:
        api_root = self._dashscope_api_root(config.base_url)
        safe_width, safe_height = self._normalize_dashscope_size(width, height)
        size = f"{safe_width}*{safe_height}"
        model_name = config.model_name.strip()
        normalized_model = model_name.lower()

        if reference_image_path and self._supports_inline_reference_image(normalized_model):
            return await self._generate_dashscope_image_with_reference(
                api_root=api_root,
                api_key=config.api_key,
                model_name=model_name,
                prompt=prompt,
                size=size,
                reference_image_path=reference_image_path,
            )

        if self._uses_dashscope_multimodal_sync(model_name):
            payload = {
                "model": model_name,
                "input": {
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"text": prompt}
                            ],
                        }
                    ]
                },
                "parameters": {
                    "size": size,
                    "n": 1,
                },
            }
            response = await self._post_json(
                api_root,
                "/api/v1/services/aigc/multimodal-generation/generation",
                payload,
                config.api_key,
                timeout_seconds=config.timeout_seconds,
            )
            return self._extract_dashscope_multimodal_image_content(response)

        payload = {
            "model": model_name,
            "input": {
                "prompt": prompt,
            },
            "parameters": {
                "size": size,
                "n": 1,
            },
        }
        task = await self._post_json(
            api_root,
            "/api/v1/services/aigc/text2image/image-synthesis",
            payload,
            config.api_key,
            timeout_seconds=config.timeout_seconds,
            extra_headers={"X-DashScope-Async": "enable"},
        )
        task_id = str(task.get("output", {}).get("task_id") or "")
        if not task_id:
            raise RuntimeError(f"DashScope image API did not return task_id. Raw response: {task}")
        result = await self._poll_dashscope_task(api_root, config.api_key, task_id)
        return self._extract_dashscope_task_image_content(result)

    async def _generate_dashscope_image_with_reference(
        self,
        api_root: str,
        api_key: str,
        model_name: str,
        prompt: str,
        size: str,
        reference_image_path: str,
    ) -> dict[str, Any]:
        image_data_url = self._to_data_url(Path(reference_image_path))
        payload = {
            "model": model_name,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"image": image_data_url},
                            {"text": prompt},
                        ],
                    }
                ]
            },
            "parameters": {
                "size": size,
            },
        }
        response = await self._post_json(
            api_root,
            "/api/v1/services/aigc/multimodal-generation/generation",
            payload,
            api_key,
            timeout_seconds=self._normalize_timeout_seconds(self.settings.text_model_timeout_seconds),
        )
        return self._extract_dashscope_multimodal_image_content(response)

    async def _poll_dashscope_task(self, api_root: str, api_key: str, task_id: str) -> dict[str, Any]:
        last_payload: dict[str, Any] = {}
        async with httpx.AsyncClient(timeout=self._normalize_timeout_seconds(self.settings.text_model_timeout_seconds)) as client:
            for _ in range(180):
                response = await client.get(
                    f"{api_root.rstrip('/')}/api/v1/tasks/{task_id}",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                response.raise_for_status()
                payload = response.json()
                last_payload = payload
                task_status = str(payload.get("output", {}).get("task_status") or "")
                if task_status == "SUCCEEDED":
                    return payload
                if task_status in {"FAILED", "CANCELED", "UNKNOWN"}:
                    message = payload.get("output", {}).get("message") or payload.get("message") or "Image task failed."
                    raise RuntimeError(f"DashScope image task failed: {message}")
                await self._sleep_one_second()
        raise RuntimeError(f"DashScope image task polling timed out. Last payload: {last_payload}")

    async def _sleep_one_second(self) -> None:
        import asyncio

        await asyncio.sleep(1)

    async def _post_json(
        self,
        base_url: str,
        path: str,
        payload: dict[str, Any],
        api_key: str,
        timeout_seconds: float,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        url = f"{base_url.rstrip('/')}{path}"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if extra_headers:
            headers.update(extra_headers)
        async with httpx.AsyncClient(timeout=self._normalize_timeout_seconds(timeout_seconds)) as client:
            response = await client.post(url, json=payload, headers=headers)
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                response_body = response.text.strip()
                if response_body:
                    raise RuntimeError(
                        f"Model request failed: HTTP {response.status_code}, response: {response_body}"
                    ) from exc
                raise
            return response.json()

    def _is_dashscope_content_filter_error(self, error: RuntimeError) -> bool:
        message = str(error)
        return "DataInspectionFailed" in message or "inappropriate content" in message

    def _build_dashscope_safe_retry_prompt(self, prompt: str) -> str:
        _ = prompt
        return (
            "参考输入图片中的线条小狗形象，生成一张温和、卡通化、象征性的新闻解释插画。"
            "画面聚焦当前单张图片的核心信息，用资料卡片、便签、手机屏幕、简化图表和小道具表达。"
            "不需要出现任何任何文字"
            "政治人物肖像、警报、爆炸、崩塌、火焰、惊恐人群、灾难现场或强刺激措辞。"
            "整体保持暖色调、简洁线稿、表情生动、非写实、手机端阅读友好。"
        )

    def _extract_text_content(self, response: dict[str, Any]) -> str:
        choices = response.get("choices") if isinstance(response, dict) else None
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("Model response does not contain choices.")

        first_choice = choices[0] if isinstance(choices[0], dict) else {}
        message = first_choice.get("message") if isinstance(first_choice, dict) else {}
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                parts: list[str] = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        parts.append(str(item.get("text", "")))
                joined = "\n".join(part.strip() for part in parts if part.strip())
                if joined:
                    return joined

        text = first_choice.get("text") if isinstance(first_choice, dict) else None
        if isinstance(text, str) and text.strip():
            return text.strip()

        raise RuntimeError("Model response does not contain usable text content.")

    def _extract_image_content(self, response: dict[str, Any]) -> dict[str, Any]:
        data = response.get("data") if isinstance(response, dict) else None
        if not isinstance(data, list) or not data:
            raise RuntimeError("Image model response does not contain data.")

        first_item = data[0] if isinstance(data[0], dict) else {}
        image_url = first_item.get("url")
        b64_json = first_item.get("b64_json")
        revised_prompt = first_item.get("revised_prompt") or ""

        if isinstance(image_url, str) and image_url.strip():
            return {
                "final_image_url": image_url.strip(),
                "revised_prompt": str(revised_prompt),
            }

        if isinstance(b64_json, str) and b64_json.strip():
            return {
                "final_image_url": f"data:image/png;base64,{b64_json.strip()}",
                "revised_prompt": str(revised_prompt),
            }

        raise RuntimeError("Image model response does not contain url or b64_json.")

    def _extract_dashscope_task_image_content(self, response: dict[str, Any]) -> dict[str, Any]:
        output = response.get("output") if isinstance(response, dict) else None
        results = output.get("results") if isinstance(output, dict) else None
        if not isinstance(results, list) or not results:
            raise RuntimeError(f"DashScope image response does not contain output.results. Raw response: {response}")

        first_item = results[0] if isinstance(results[0], dict) else {}
        image_url = str(first_item.get("url") or "").strip()
        actual_prompt = str(first_item.get("actual_prompt") or first_item.get("orig_prompt") or "")
        if not image_url:
            code = first_item.get("code")
            message = first_item.get("message") or "DashScope image response does not contain an image URL."
            if code:
                raise RuntimeError(f"DashScope image API failed: code={code}, message={message}")
            raise RuntimeError(message)
        return {
            "final_image_url": image_url,
            "revised_prompt": actual_prompt,
        }

    def _extract_dashscope_multimodal_image_content(self, response: dict[str, Any]) -> dict[str, Any]:
        output = response.get("output") if isinstance(response, dict) else None
        if not isinstance(output, dict):
            raise RuntimeError(f"DashScope multimodal image response does not contain output. Raw response: {response}")

        results = output.get("results")
        if isinstance(results, list) and results:
            first_item = results[0] if isinstance(results[0], dict) else {}
            image_url = str(first_item.get("url") or "").strip()
            actual_prompt = str(first_item.get("actual_prompt") or first_item.get("orig_prompt") or "")
            if image_url:
                return {
                    "final_image_url": image_url,
                    "revised_prompt": actual_prompt,
                }

        choices = output.get("choices")
        if isinstance(choices, list) and choices:
            first_choice = choices[0] if isinstance(choices[0], dict) else {}
            message = first_choice.get("message") if isinstance(first_choice, dict) else {}
            content = message.get("content") if isinstance(message, dict) else None
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "image":
                        image_url = str(item.get("image") or "").strip()
                        if image_url:
                            return {
                                "final_image_url": image_url,
                                "revised_prompt": "",
                            }

        raise RuntimeError(f"DashScope multimodal image response does not contain a usable image URL. Raw response: {response}")

    def _parse_json_text(self, text: str) -> dict[str, Any]:
        normalized = text.strip()
        if not normalized:
            raise RuntimeError("Model returned empty JSON.")

        try:
            parsed = json.loads(normalized)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        match = re.search(r"\{.*\}", normalized, re.DOTALL)
        if not match:
            raise RuntimeError("Unable to extract a JSON object from model output.")

        parsed = json.loads(match.group(0))
        if not isinstance(parsed, dict):
            raise RuntimeError("Model output is not a JSON object.")
        return parsed

    def _require_text_config(self) -> ModelRuntimeConfig:
        config = self._get_text_config()
        if not config:
            raise RuntimeError("Text model configuration is incomplete. Please check .env.")
        return config

    def _require_text_config_for_stage(self, stage: str) -> ModelRuntimeConfig:
        config = self._get_text_config_for_stage(stage)
        if not config:
            raise RuntimeError(f"Text model configuration is incomplete for stage={stage}. Please check .env.")
        return config

    def _require_image_config(self) -> ModelRuntimeConfig:
        config = self._get_image_config()
        if not config:
            raise RuntimeError("Image model configuration is incomplete. Please check .env.")
        return config

    def _get_text_config(self) -> ModelRuntimeConfig | None:
        dashscope_config = self._build_config(
            self.settings.dashscope_base_url,
            self.settings.dashscope_api_key,
            self.settings.dashscope_text_model,
            self.settings.text_model_timeout_seconds,
        )
        if dashscope_config:
            return dashscope_config

        if self.settings.use_shared_model:
            return self._build_config(
                self.settings.shared_model_base_url,
                self.settings.shared_model_api_key,
                self.settings.shared_model_name,
                self.settings.text_model_timeout_seconds,
            )

        return self._build_config(
            self.settings.text_model_base_url,
            self.settings.text_model_api_key,
            self.settings.text_model_name,
            self.settings.text_model_timeout_seconds,
        )

    def _get_text_config_for_stage(self, stage: str) -> ModelRuntimeConfig | None:
        stage_model_name = self._get_stage_model_name(stage)
        if stage_model_name:
            transport = self._get_text_transport()
            if transport:
                base_url, api_key = transport
                return self._build_config(base_url, api_key, stage_model_name, self._get_stage_timeout_seconds(stage))
        return self._get_text_config()

    def _get_text_transport(self) -> tuple[str, str] | None:
        dashscope_base_url = str(self.settings.dashscope_base_url or "").strip()
        dashscope_api_key = str(self.settings.dashscope_api_key or "").strip()
        if dashscope_base_url and dashscope_api_key:
            return dashscope_base_url, dashscope_api_key

        if self.settings.use_shared_model:
            shared_base_url = str(self.settings.shared_model_base_url or "").strip()
            shared_api_key = str(self.settings.shared_model_api_key or "").strip()
            if shared_base_url and shared_api_key:
                return shared_base_url, shared_api_key

        text_base_url = str(self.settings.text_model_base_url or "").strip()
        text_api_key = str(self.settings.text_model_api_key or "").strip()
        if text_base_url and text_api_key:
            return text_base_url, text_api_key

        return None

    def _get_stage_model_name(self, stage: str) -> str:
        field_name = STAGE_MODEL_FIELD_MAP.get(stage, "")
        if not field_name:
            return ""
        return str(getattr(self.settings, field_name, "") or "").strip()

    def _resolve_stage_model_name(self, stage: str) -> str:
        return self._get_resolved_model_name(self._get_text_config_for_stage(stage))

    def _get_resolved_model_name(self, config: ModelRuntimeConfig | None) -> str:
        if not config:
            return ""
        return str(config.model_name or "").strip()

    def _has_stage_model_overrides(self) -> bool:
        return any(self._get_stage_model_name(stage) for stage in STAGE_MODEL_FIELD_MAP)

    def _get_image_config(self) -> ModelRuntimeConfig | None:
        dashscope_image_config = self._build_config(
            self.settings.dashscope_base_url,
            self.settings.dashscope_api_key,
            self.settings.dashscope_image_model,
            self.settings.text_model_timeout_seconds,
        )
        if dashscope_image_config:
            return dashscope_image_config

        if self.settings.use_shared_model:
            image_model_name = self.settings.shared_image_model_name or self.settings.shared_model_name
            return self._build_config(
                self.settings.shared_model_base_url,
                self.settings.shared_model_api_key,
                image_model_name,
                self.settings.text_model_timeout_seconds,
            )

        return self._build_config(
            self.settings.image_model_base_url,
            self.settings.image_model_api_key,
            self.settings.image_model_name,
            self.settings.text_model_timeout_seconds,
        )

    def _build_config(self, base_url: str, api_key: str, model_name: str, timeout_seconds: float) -> ModelRuntimeConfig | None:
        normalized_base_url = str(base_url or "").strip().rstrip("/")
        normalized_api_key = str(api_key or "").strip()
        normalized_model_name = str(model_name or "").strip()
        if not (normalized_base_url and normalized_api_key and normalized_model_name):
            return None
        return ModelRuntimeConfig(
            base_url=normalized_base_url,
            api_key=normalized_api_key,
            model_name=normalized_model_name,
            timeout_seconds=self._normalize_timeout_seconds(timeout_seconds),
        )

    def _get_stage_timeout_seconds(self, stage: str) -> float:
        timeout_map = {
            STAGE_RESEARCH: self.settings.model_research_timeout_seconds,
            STAGE_FACTCHECK: self.settings.model_factcheck_timeout_seconds,
            STAGE_WRITER: self.settings.model_writer_timeout_seconds,
            STAGE_IMAGE_PROMPT: self.settings.model_image_prompt_timeout_seconds,
            STAGE_WECHAT_ARTICLE: self.settings.model_wechat_article_timeout_seconds,
        }
        return self._normalize_timeout_seconds(timeout_map.get(stage, self.settings.text_model_timeout_seconds))

    def _normalize_timeout_seconds(self, value: float | int | None) -> float:
        try:
            normalized = float(value or 0)
        except (TypeError, ValueError):
            normalized = 0.0
        return normalized if normalized > 0 else 120.0

    def _is_dashscope_image_model(self, config: ModelRuntimeConfig) -> bool:
        if not self.settings.dashscope_api_key:
            return False
        return "dashscope.aliyuncs.com" in config.base_url

    def _dashscope_api_root(self, base_url: str) -> str:
        normalized = base_url.rstrip("/")
        marker = "/compatible-mode/v1"
        if normalized.endswith(marker):
            return normalized[: -len(marker)]
        return normalized

    def _uses_dashscope_multimodal_sync(self, model_name: str) -> bool:
        normalized = model_name.lower()
        return normalized.startswith("qwen-image") or normalized.startswith("wan2.7-image")

    def _supports_inline_reference_image(self, model_name: str) -> bool:
        normalized = model_name.lower()
        return normalized.startswith("qwen-image") or normalized.startswith("wan2.7-image")

    def _normalize_dashscope_size(self, width: int, height: int) -> tuple[int, int]:
        safe_width = min(max(int(width), 512), 1440)
        safe_height = min(max(int(height), 512), 1440)
        return safe_width, safe_height

    def _to_data_url(self, image_path: Path) -> str:
        if not image_path.exists() or not image_path.is_file():
            raise RuntimeError(f"Reference image does not exist: {image_path}")
        suffix = image_path.suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".bmp", ".webp"}:
            raise RuntimeError("Reference image format must be jpg/jpeg/png/bmp/webp.")
        mime_type = self._guess_mime_type(suffix)
        encoded = base64.b64encode(image_path.read_bytes()).decode("utf-8")
        return f"data:{mime_type};base64,{encoded}"

    def _guess_mime_type(self, suffix: str) -> str:
        if suffix in {".jpg", ".jpeg"}:
            return "image/jpeg"
        if suffix == ".png":
            return "image/png"
        if suffix == ".bmp":
            return "image/bmp"
        if suffix == ".webp":
            return "image/webp"
        return "application/octet-stream"

