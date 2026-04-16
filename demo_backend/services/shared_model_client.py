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


class SharedModelClient:
    """真实模型调用客户端。

    改动后约定：
    1. 文本阶段继续走 OpenAI compatible chat/completions
    2. DashScope 图片模型不再走 /images/generations
    3. wan2.x / qwen-image 等图片模型统一走百炼官方图片接口
    4. 支持传入本地参考图 reference_image_path
    5. 即使 .env 里的 base_url 是 compatible-mode/v1，图片阶段也会自动切回百炼根路径
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
        if self.settings.dashscope_api_key:
            return "DashScope 模式：文本阶段默认使用 qwen-plus，图片阶段自动适配百炼图片接口"
        if self.settings.use_shared_model:
            return "演示版：文本阶段和图片阶段共用同一组模型配置"
        return "扩展版：文本模型和图片模型分开配置"

    async def generate_text(self, system_prompt: str, user_prompt: str, temperature: float = 0.3) -> str:
        config = self._require_text_config()
        payload = {
            "model": config.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
        }
        response = await self._post_json(config.base_url, "/chat/completions", payload, config.api_key)
        return self._extract_text_content(response)

    async def generate_json(self, system_prompt: str, user_prompt: str, temperature: float = 0.2) -> dict[str, Any]:
        config = self._require_text_config()
        payload = {
            "model": config.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        response = await self._post_json(config.base_url, "/chat/completions", payload, config.api_key)
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
                return await self._generate_dashscope_image(config, prompt, width, height, reference_image_path)
            except RuntimeError as exc:
                if not self._is_dashscope_content_filter_error(exc):
                    raise

                safer_prompt = self._build_dashscope_safe_retry_prompt(prompt)
                response = await self._generate_dashscope_image(config, safer_prompt, width, height, reference_image_path)
                if not response.get("revised_prompt"):
                    response["revised_prompt"] = safer_prompt
                return response

        payload = {
            "model": config.model_name,
            "prompt": prompt,
            "size": f"{width}x{height}",
        }
        response = await self._post_json(config.base_url, "/images/generations", payload, config.api_key)
        return self._extract_image_content(response)

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
            extra_headers={"X-DashScope-Async": "enable"},
        )
        task_id = str(task.get("output", {}).get("task_id") or "")
        if not task_id:
            raise RuntimeError(f"百炼图片接口没有返回 task_id。原始返回：{task}")
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
        )
        return self._extract_dashscope_multimodal_image_content(response)

    async def _poll_dashscope_task(self, api_root: str, api_key: str, task_id: str) -> dict[str, Any]:
        last_payload: dict[str, Any] = {}
        async with httpx.AsyncClient(timeout=120.0) as client:
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
                    message = payload.get("output", {}).get("message") or payload.get("message") or "图片任务失败。"
                    raise RuntimeError(f"百炼图片任务失败：{message}")
                await self._sleep_one_second()
        raise RuntimeError(f"百炼图片任务轮询超时，最后状态：{last_payload}")

    async def _sleep_one_second(self) -> None:
        import asyncio

        await asyncio.sleep(1)

    async def _post_json(
        self,
        base_url: str,
        path: str,
        payload: dict[str, Any],
        api_key: str,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        url = f"{base_url.rstrip('/')}{path}"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if extra_headers:
            headers.update(extra_headers)
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                response_body = response.text.strip()
                if response_body:
                    raise RuntimeError(
                        f"模型接口请求失败：HTTP {response.status_code}，响应内容：{response_body}"
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
            "只保留非常少量、简短、中性的中文提示，不出现夸张大字标题，不出现具体人名、机构名、巨额损失数字、"
            "政治人物肖像、警报、爆炸、崩塌、火焰、惊恐人群、灾难现场或强刺激措辞。"
            "整体保持暖色调、简洁线稿、表情生动、非写实、手机端阅读友好。"
        )

    def _extract_text_content(self, response: dict[str, Any]) -> str:
        choices = response.get("choices") if isinstance(response, dict) else None
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("模型返回里没有 choices 字段。")

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

        raise RuntimeError("模型返回里没有可用的文本内容。")

    def _extract_image_content(self, response: dict[str, Any]) -> dict[str, Any]:
        data = response.get("data") if isinstance(response, dict) else None
        if not isinstance(data, list) or not data:
            raise RuntimeError("图片模型返回里没有 data 字段。")

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

        raise RuntimeError("图片模型返回里没有 url 或 b64_json。")

    def _extract_dashscope_task_image_content(self, response: dict[str, Any]) -> dict[str, Any]:
        output = response.get("output") if isinstance(response, dict) else None
        results = output.get("results") if isinstance(output, dict) else None
        if not isinstance(results, list) or not results:
            raise RuntimeError(f"百炼图片接口返回里没有 output.results。原始返回：{response}")

        first_item = results[0] if isinstance(results[0], dict) else {}
        image_url = str(first_item.get("url") or "").strip()
        actual_prompt = str(first_item.get("actual_prompt") or first_item.get("orig_prompt") or "")
        if not image_url:
            code = first_item.get("code")
            message = first_item.get("message") or "百炼图片接口没有返回图片 URL。"
            if code:
                raise RuntimeError(f"百炼图片接口失败：code={code}, message={message}")
            raise RuntimeError(message)
        return {
            "final_image_url": image_url,
            "revised_prompt": actual_prompt,
        }

    def _extract_dashscope_multimodal_image_content(self, response: dict[str, Any]) -> dict[str, Any]:
        output = response.get("output") if isinstance(response, dict) else None
        if not isinstance(output, dict):
            raise RuntimeError(f"百炼多模态图片接口返回里没有 output。原始返回：{response}")

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

        raise RuntimeError(f"百炼多模态图片接口返回里没有可用图片地址。原始返回：{response}")

    def _parse_json_text(self, text: str) -> dict[str, Any]:
        normalized = text.strip()
        if not normalized:
            raise RuntimeError("模型返回了空 JSON。")

        try:
            parsed = json.loads(normalized)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        match = re.search(r"\{.*\}", normalized, re.DOTALL)
        if not match:
            raise RuntimeError("无法从模型输出中提取 JSON 对象。")

        parsed = json.loads(match.group(0))
        if not isinstance(parsed, dict):
            raise RuntimeError("模型输出不是 JSON 对象。")
        return parsed

    def _require_text_config(self) -> ModelRuntimeConfig:
        config = self._get_text_config()
        if not config:
            raise RuntimeError("文本模型配置不完整，请检查 .env。")
        return config

    def _require_image_config(self) -> ModelRuntimeConfig:
        config = self._get_image_config()
        if not config:
            raise RuntimeError("图片模型配置不完整，请检查 .env。")
        return config

    def _get_text_config(self) -> ModelRuntimeConfig | None:
        dashscope_config = self._build_config(
            self.settings.dashscope_base_url,
            self.settings.dashscope_api_key,
            self.settings.dashscope_text_model,
        )
        if dashscope_config:
            return dashscope_config

        if self.settings.use_shared_model:
            return self._build_config(
                self.settings.shared_model_base_url,
                self.settings.shared_model_api_key,
                self.settings.shared_model_name,
            )

        return self._build_config(
            self.settings.text_model_base_url,
            self.settings.text_model_api_key,
            self.settings.text_model_name,
        )

    def _get_image_config(self) -> ModelRuntimeConfig | None:
        dashscope_image_config = self._build_config(
            self.settings.dashscope_base_url,
            self.settings.dashscope_api_key,
            self.settings.dashscope_image_model,
        )
        if dashscope_image_config:
            return dashscope_image_config

        if self.settings.use_shared_model:
            image_model_name = self.settings.shared_image_model_name or self.settings.shared_model_name
            return self._build_config(
                self.settings.shared_model_base_url,
                self.settings.shared_model_api_key,
                image_model_name,
            )

        return self._build_config(
            self.settings.image_model_base_url,
            self.settings.image_model_api_key,
            self.settings.image_model_name,
        )

    def _build_config(self, base_url: str, api_key: str, model_name: str) -> ModelRuntimeConfig | None:
        normalized_base_url = str(base_url or "").strip().rstrip("/")
        normalized_api_key = str(api_key or "").strip()
        normalized_model_name = str(model_name or "").strip()
        if not (normalized_base_url and normalized_api_key and normalized_model_name):
            return None
        return ModelRuntimeConfig(
            base_url=normalized_base_url,
            api_key=normalized_api_key,
            model_name=normalized_model_name,
        )

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
        return normalized.startswith("qwen-image-2") or normalized.startswith("wan2.7-image")

    def _supports_inline_reference_image(self, model_name: str) -> bool:
        normalized = model_name.lower()
        return normalized.startswith("qwen-image-2") or normalized.startswith("wan2.7-image")

    def _normalize_dashscope_size(self, width: int, height: int) -> tuple[int, int]:
        safe_width = min(max(int(width), 512), 1440)
        safe_height = min(max(int(height), 512), 1440)
        return safe_width, safe_height

    def _to_data_url(self, image_path: Path) -> str:
        if not image_path.exists() or not image_path.is_file():
            raise RuntimeError(f"参考图不存在：{image_path}")
        suffix = image_path.suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".bmp", ".webp"}:
            raise RuntimeError("参考图格式只支持 jpg/jpeg/png/bmp/webp。")
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






