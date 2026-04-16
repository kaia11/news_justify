from __future__ import annotations

import base64
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from demo_backend.models import (
    Claim,
    ClaimEvidenceBundle,
    ClaimVerdict,
    DemoPipelineItemResult,
    DemoPipelineResponse,
    EpisodeImage,
    EvidenceItem,
    FactCheckResult,
    ImageResult,
    IssueItem,
    IssuePayload,
    ResearchResult,
    WebResearchResult,
    WechatArticleResult,
    WechatPublishResult,
    WriterResult,
)
from demo_backend.services.shared_model_client import SharedModelClient
from demo_backend.services.web_research_service import WebResearchService
from wechat.backend.service import WechatPublishService

REFERENCE_IMAGE_PATH = Path(__file__).resolve().parents[2] / "assets" / "reference_images" / "model_input_example.jpg"
SCRIPT_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "pipeline_scripts.db"
GENERATED_IMAGE_ROOT = Path(__file__).resolve().parents[1] / "data" / "generated_images"
DEBUG_OUTPUT_ROOT = Path(__file__).resolve().parents[1] / "data" / "debug_pipeline"


class DemoPipelineService:
    COMIC_STYLE_ANCHOR = (
        "可爱卡通线条小狗主角，暖色调，简洁线稿，"
        "新闻讲解风格，手机端阅读友好，表情生动，非写实，无复杂背景，"
        "角色形象尽量参考输入图片中的线条小狗"
    )

    def __init__(
        self,
        shared_model_client: SharedModelClient,
        web_research_service: WebResearchService | None = None,
        wechat_publisher: WechatPublishService | None = None,
    ):
        self.shared_model_client = shared_model_client
        self.web_research_service = web_research_service
        self.wechat_publisher = wechat_publisher
    async def run(self, issue: IssuePayload) -> DemoPipelineResponse:
        results = []
        run_stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        for item in issue.items:
            results.append(await self._build_item_result(issue, item, run_stamp))
        return DemoPipelineResponse(
            source_mode=issue.source_mode,
            issue=issue,
            model_strategy=self.shared_model_client.strategy_label,
            model_configured=self.shared_model_client.configured,
            results=results,
        )

    async def _build_item_result(self, issue: IssuePayload, item: IssueItem, run_stamp: str) -> DemoPipelineItemResult:
        storage_item_id = self._build_storage_item_id(run_stamp, item)
        debug_artifacts: dict[str, str] = {}
        debug_artifacts["issue_item"] = self._write_debug_json(storage_item_id, "00_issue_item.json", item.model_dump())

        research = await self._build_research(item)
        debug_artifacts["research"] = self._write_debug_json(storage_item_id, "01_research.json", research.model_dump())

        web_research = await self._build_web_research(item, research)
        debug_artifacts["web_research"] = self._write_debug_json(storage_item_id, "02_web_research.json", web_research.model_dump())

        fact_check = await self._build_fact_check(item, research, web_research)
        debug_artifacts["fact_check"] = self._write_debug_json(storage_item_id, "03_fact_check.json", fact_check.model_dump())

        writer_brief = self._build_writer_brief(research, web_research, fact_check)
        debug_artifacts["writer_brief"] = self._write_debug_json(storage_item_id, "03b_writer_brief.json", writer_brief)

        writer = await self._build_writer(item, research, web_research, fact_check, writer_brief, storage_item_id)
        debug_artifacts["writer"] = self._write_debug_json(storage_item_id, "04_writer.json", writer.model_dump())

        image = await self._build_image(item, writer, storage_item_id)
        debug_artifacts["image"] = self._write_debug_json(storage_item_id, "05_image.json", image.model_dump())

        wechat_article = await self._build_wechat_article(item, fact_check, writer)
        debug_artifacts["wechat_article"] = self._write_debug_json(storage_item_id, "06_wechat_article.json", wechat_article.model_dump())

        wechat_publish = await self._build_wechat_publish(issue, item, storage_item_id, writer, fact_check, image, wechat_article)
        if wechat_publish:
            debug_artifacts["wechat_publish"] = self._write_debug_json(storage_item_id, "07_wechat_publish.json", wechat_publish.model_dump())
        return DemoPipelineItemResult(
            issue_item=item,
            research=research,
            web_research=web_research,
            fact_check=fact_check,
            writer=writer,
            image=image,
            wechat_article=wechat_article,
            wechat_publish=wechat_publish,
            debug_artifacts=debug_artifacts,
        )
    async def _build_research(self, item: IssueItem) -> ResearchResult:
        system_prompt = (
            "你是新闻研究助手。你的任务不是复述爆料，而是把一条可能半真半假的新闻拆成最值得核查的核心命题。"
            "你要同时识别两类内容：一是新闻声称发生了什么，二是这条新闻本身有哪些可疑结构，例如匿名爆料、绝对化表述、旧闻拼接、把研究讨论夸大成现实事故。"
            "每条 claim 只能表达一个事实点，但不要把同一类近义说法机械拆成很多重复命题。"
            "你必须只返回 JSON 对象，不要输出 markdown。"
        )
        user_prompt = f"""
请根据下面的新闻内容，输出一个 JSON 对象，字段必须严格如下：
{{
  "claims": [
    {{
      "claim_id": "字符串",
      "text": "字符串",
      "claim_type": "event|announcement|number|time|scope|impact|other",
      "subject": "字符串",
      "predicate": "字符串",
      "object": "字符串",
      "time_scope": "字符串",
      "priority": 1
    }}
  ],
  "reference_sources": [
    {{
      "evidence_id": "字符串",
      "claim_id": "字符串",
      "title": "字符串",
      "url": "字符串",
      "publisher": "字符串",
      "type": "primary|secondary|low_confidence",
      "note": "字符串"
    }}
  ]
}}

严格要求：
1. claims 只保留 4 到 6 条最核心、最值得核查的命题，避免把同一个爆料拆成一串近义重复句。
2. 除了“爆料声称发生了什么”，还要优先挑出真正决定新闻可信度的命题，例如：是否有公开证据、是否有内部人员真实表态、是否真的发生停机、是否把研究讨论说成现实事故。
3. 每条命题只能表达一个事实点，不要把多个事实揉在一句里。
4. claim_type 含义：
   - event：是否发生了某件事
   - announcement：谁说了什么、谁发出了什么说法
   - number：具体数值
   - time：具体时间
   - scope：对象范围
   - impact：直接影响
   - other：其他关键事实点
5. subject / predicate / object 要尽量短，便于后续核查。
6. priority 使用 1 到 5，1 表示最值得优先核查。
7. reference_sources 不要伪造权威证据；如果当前只有新闻原文或热传内容，也可以如实填写 low_confidence，并在 note 里写清“缺少公开日志、官方确认、原始截图、可复现证据”等缺口。
8. reference_sources 的 note 要尽量指出“后续真正应该查什么”，而不是简单重复“未发现”。
9. 不要输出结论，不要输出多余字段。

新闻标题：{item.headline}
新闻来源：{item.source}
原文链接：{item.article_url}
正文：{self._join_article_body(item)}
""".strip()

        payload = await self.shared_model_client.generate_json(system_prompt, user_prompt)
        claims = [Claim(**claim) for claim in payload.get("claims", [])]
        sources = [EvidenceItem(**source) for source in payload.get("reference_sources", [])]
        if not claims:
            raise RuntimeError("Research 阶段返回为空，模型没有生成 claims。")
        return ResearchResult(status="generated", claims=claims, reference_sources=sources)

    async def _build_web_research(self, item: IssueItem, research: ResearchResult) -> WebResearchResult:
        if not self.web_research_service:
            return WebResearchResult(status="pending_config", provider="bocha", notes=["未注入联网检索服务，已跳过。"])
        return await self.web_research_service.run(item, research)

    async def _build_fact_check(self, item: IssueItem, research: ResearchResult, web_research: WebResearchResult) -> FactCheckResult:
        system_prompt = (
            "你是一个新闻事实核查与背景分析助手。"
            "你要逐条检查输入中的最小可核查命题 claims，并区分三件事：这条说法有没有公开证据、这条说法是否混入了真实背景讨论、这条新闻是否存在夸大或误读。"
            "你必须只返回 JSON 对象，不要输出 markdown，不要解释。"
        )
        evidence_summary = self._build_fact_check_evidence_summary(web_research.claim_evidence)
        user_prompt = f"""
请输出一个 JSON 对象，字段必须严格如下：
{{
  "claim_verdicts": [
    {{
      "claim_id": "字符串",
      "verdict": "supported|partially_supported|uncertain|unsupported",
      "reason": "字符串",
      "citation_ids": ["字符串"]
    }}
  ],
  "risk_notes": ["字符串"],
  "context_notes": ["字符串"]
}}

你必须遵守这些规则：
1. 只能基于输入里的 claims 和 reference_sources 判断，但要充分利用其中的 note，说明“目前公开能确认什么、还缺什么、哪些可能是夸大转述”。
2. 不允许把“缺乏证据”说成“已经证伪”。
3. 不要把所有 claim 都机械写成同一种 uncertain 模板；要尽量区分：
   - 完全缺少公开证据
   - 有真实背景，但新闻表述说过头了
   - 可能把研究讨论、演练或旧闻说成现实事故
   - 现有公开信息明显对不上
4. 如果证据不足，输出 uncertain；如果有真实背景但新闻表述扩大、绝对化、误读了，优先输出 partially_supported。
5. 每条 claim 必须单独判断，不要把多个 claim 合并。
6. 每条 reason 都要写成普通读者能看懂的话，不要写成系统术语清单。
7. citation_ids 都要尽量给出；如果只有低置信度来源，也要如实引用。
8. risk_notes 要指出新闻在传播表达上的问题，例如匿名爆料、绝对化标题、因果跳跃、旧闻拼接、术语模糊。
9. context_notes 要补充读者理解这条新闻需要的真实背景，例如 AI 安全研究里真实讨论过什么、部署环境如何限制模型行为、为什么不能把研究现象直接等同于现实失控。
10. 不要输出多余字段。
11. web_evidence 是运行时外部检索得到的证据摘要，优先使用它，再参考 reference_sources。
12. verdict 仍然必须服从 evidence_tier 上限，不能因为新闻写得很确定就越级。
13. 没有 summary、只有零散 snippet、只有单一普通来源时，不要给 supported。
14. 因果类、影响类、动机类 claim 即使 evidence_tier 很高，也应保持谨慎，优先给 partially_supported。
15. citation_ids 优先引用 web_evidence 里的 url；如果没有可引用网页，再引用 reference_sources 的 evidence_id。

新闻标题：{item.headline}
来源：{item.source}
claims：{json.dumps([claim.model_dump() for claim in research.claims], ensure_ascii=False)}
reference_sources：{json.dumps([source.model_dump() for source in research.reference_sources], ensure_ascii=False)}
web_evidence：{json.dumps(evidence_summary, ensure_ascii=False)}
web_research_notes：{json.dumps(web_research.notes, ensure_ascii=False)}
""".strip()

        payload = await self.shared_model_client.generate_json(system_prompt, user_prompt)
        verdicts = [ClaimVerdict(**verdict) for verdict in payload.get("claim_verdicts", [])]
        if not verdicts:
            raise RuntimeError("Fact-check 阶段返回为空，模型没有生成 claim_verdicts。")
        verdicts = self._apply_verdict_caps(research.claims, web_research.claim_evidence, verdicts)
        return FactCheckResult(
            status="generated",
            claim_verdicts=verdicts,
            risk_notes=[str(value) for value in payload.get("risk_notes", [])],
            context_notes=[str(value) for value in payload.get("context_notes", [])],
        )

    async def _build_writer(
        self,
        item: IssueItem,
        research: ResearchResult,
        web_research: WebResearchResult,
        fact_check: FactCheckResult,
        writer_brief: dict[str, Any],
        storage_item_id: str,
    ) -> WriterResult:
        system_prompt = (
            "你是解释型新闻内容编剧助手。请把公开可见的事实材料整理成适合社交媒体传播的中文文案和分镜脚本。"
            "主角固定为两只线条小狗：一只小白狗和一只小金毛。"
            "你的重点不是给新闻下真假判词，而是向普通读者解释：这条新闻里的关键说法，目前公开能确认什么、还缺什么、真实背景是什么。"
            "你可以参考 fact_check 的判断来控制表达强度，但 writer 的主要依据必须是网页证据摘要和事实包，而不是 verdict 标签本身。"
            "面向普通读者写作：若出现专业词/缩写/英文术语，必须先用大白话做生词解释，再进行真假判断。"
            "你必须只返回 JSON 对象，不要输出 markdown。"
        )
        user_prompt = f"""
请根据下面的信息，生成一个适合“新闻讲解短视频”的漫画分镜脚本 JSON。

你输出的内容要同时满足这两个目标：
1. 明确告诉后续流程，这条内容一共要生成多少张“单格图片”。
2. 对每一张单格图片，给出独立分镜信息：画面、人物动作、人物台词、旁白和作图提示。

请严格输出以下 JSON 结构，不要增加多余字段：
{{
  "headline": "字符串",
  "social_caption": "字符串",
  "video_topic": "字符串",
  "image_count": "整数，按内容清晰度决定",
  "single_panels": [
    {{
      "image_index": 1,
      "panel_role": "起因|核查|证据|结论等简短标签",
      "image_theme": "这一张单图的主题",
      "image_goal": "这一张单图讲清什么公开事实或证据缺口",
      "story_beat": "这一张单图在整体叙事中的推进",
      "style_anchor": "固定画风提示词",
      "scene": "单场景画面内容",
      "characters": [
        {{
          "name": "小白狗 或 小金毛",
          "action": "动作",
          "expression": "表情",
          "dialogue": "这一张图说的话"
        }}
      ],
      "narration": "旁白",
      "fact_focus": "这一张图对应讲解的公开事实、证据缺口或真实背景",
      "visual_prompt": "给图片模型的中文提示词（仅单图）"
    }}
  ]
}}

必须遵守以下要求：
1. headline 要简短，明确说明漫画在讲“新闻里的关键说法为什么值得怀疑、哪些部分成立、哪些部分没证据”。
2. social_caption 控制在 120 字以内，要有传播感和趣味性。
4. 叙事优先级必须是：先讲公开能看到什么，再讲还缺什么关键证据，再讲新闻哪些地方可能说过头了。
5. 可以参考 fact_check 的判断边界，但不要把 unsupported、uncertain、claim_verdicts、citation_ids、e1-e7 这类内部标签直接写进 headline、旁白、台词、fact_focus 或画面文字。
6. 如果公开证据不足，要写成“目前公开还看不到”“现在能找到的大多是转述”，不要直接写成“已经证明是假的”。
7. 如果有真实背景但新闻说过头了，要把“真实背景”和“夸张延伸”分开讲清楚。
8. 输出必须是单图列表，禁止四宫格/分镜边框/拼图排版；每个 image_index 对应一张独立图片。
9. 图片总数由信息表达清晰度决定；以讲清事实为第一优先级，不为凑图重复表达。
10. 面向普通读者：出现专业词/缩写/英文术语（如 WSL2、ROCm、系统性风险、缓存TTL）时，必须先做生词解释，再做真假判断；无生词可直接判断。
11. 生词解释要用大白话短句，建议格式“术语=大白话解释（不超过20字）”。
12. 台词要口语化、像在给普通用户解释新闻，不要像系统汇报。
13. narration 和 dialogue 要口语化、日常化，避免术语堆叠和系统汇报腔。
14. 对 uncertain / partially_supported 的内容必须保留谨慎表达，但不要反复堆术语。
15. visual_prompt 必须适合直接拿去生成图片，并明确描述该单图画面。
16. style_anchor 必须包含这段内容：{self.COMIC_STYLE_ANCHOR}
17. 画面整体风格统一、适合手机端阅读，信息清楚，情绪有变化，适当带一点轻松感。
18. 不要输出多余字段，不要输出 markdown。

新闻标题：{item.headline}
新闻来源：{item.source}
claims：{json.dumps([claim.model_dump() for claim in research.claims], ensure_ascii=False)}
writer_fact_brief：{json.dumps(writer_brief, ensure_ascii=False)}
web_research_notes：{json.dumps(web_research.notes, ensure_ascii=False)}
事实核查边界：{json.dumps(fact_check.model_dump(), ensure_ascii=False)}
""".strip()

        payload = await self.shared_model_client.generate_json(system_prompt, user_prompt)
        images = self._normalize_single_panels(payload.get("single_panels", []))
        if not images:
            raise RuntimeError("Writer 阶段返回为空，模型没有生成可用的 single_panels。")

        db_path = self._save_story_scripts(
            storage_item_id=storage_item_id,
            headline=str(payload.get("headline") or item.headline),
            social_caption=str(payload.get("social_caption") or item.headline),
            video_topic=str(payload.get("video_topic") or item.headline),
            images=images,
        )
        return WriterResult(
            status="generated",
            headline=str(payload.get("headline") or item.headline),
            social_caption=str(payload.get("social_caption") or item.headline),
            video_topic=str(payload.get("video_topic") or item.headline),
            image_count=len(images),
            images=images,
            comic_script=images,
            script_db_path=db_path,
        )
    async def _build_image(self, item: IssueItem, writer: WriterResult, storage_item_id: str) -> ImageResult:
        story_images = self._load_story_scripts(storage_item_id)
        if not story_images:
            story_images = writer.images or writer.comic_script
        if not story_images:
            raise RuntimeError("Image 阶段缺少可用的 images 脚本。")

        reference_image_path = str(REFERENCE_IMAGE_PATH) if REFERENCE_IMAGE_PATH.exists() else ""
        episode_images: list[EpisodeImage] = []
        first_prompt = ""
        first_url = ""

        for generated_index, image_script in enumerate(story_images, start=1):
            story_index = int(image_script.get("image_index") or generated_index)
            panels = image_script.get("panels") if isinstance(image_script.get("panels"), list) else []
            panel = panels[0] if panels and isinstance(panels[0], dict) else {}
            image_prompt = await self._build_image_prompt(item, writer, image_script, generated_index, panel)
            self._mark_story_script_generating(storage_item_id, story_index)
            image_result = await self.shared_model_client.generate_image(
                image_prompt,
                width=1080,
                height=1440,
                reference_image_path=reference_image_path,
            )
            final_image_url = str(image_result.get("final_image_url") or "")
            revised_prompt = str(image_result.get("revised_prompt") or image_prompt)
            local_image_path = await self._save_generated_image(storage_item_id, generated_index, final_image_url)
            self._update_story_script_result(
                item_id=storage_item_id,
                image_index=story_index,
                image_prompt=revised_prompt,
                final_image_url=final_image_url,
                local_image_path=local_image_path,
                generation_status="generated",
            )
            if not first_prompt:
                first_prompt = revised_prompt
            if not first_url:
                first_url = final_image_url
            episode_images.append(
                EpisodeImage(
                    image_index=generated_index,
                    image_theme=str(image_script.get("image_theme") or f"第{generated_index}张"),
                    image_prompt=revised_prompt,
                    final_image_url=final_image_url,
                    local_image_path=local_image_path,
                    generation_status="generated",
                    script_record_id=int(image_script.get("script_record_id") or 0),
                )
            )

        episode_images.sort(key=lambda item: item.image_index)
        return ImageResult(
            status="generated",
            image_prompt=first_prompt,
            final_image_url=first_url,
            episode_images=episode_images,
        )

    async def _build_image_prompt(
        self,
        item: IssueItem,
        writer: WriterResult,
        image_script: dict[str, Any],
        image_index: int,
        panel: dict[str, Any],
    ) -> str:
        system_prompt = (
            "你是漫画分镜提示词助手。请根据单格脚本生成一段适合图片模型调用的中文提示词。"
            "重点是单格画面表达清楚，绝对不要输出多格拼图。"
            "只输出纯文本提示词，不要输出 markdown，不要解释。"
        )
        panel_json = json.dumps(panel, ensure_ascii=False) if isinstance(panel, dict) else "{}"
        user_prompt = f"""
请根据下面的信息生成一段适合图片模型调用的提示词：

标题：{writer.headline}
社交文案：{writer.social_caption}
视频主题：{writer.video_topic}
来源：{item.source}
第几张图：第{image_index}张
本张图片主题：{image_script.get("image_theme") or f"第{image_index}张"}
本张图片目标：{image_script.get("image_goal") or ""}
剧情推进：{image_script.get("story_beat") or ""}
固定风格：{image_script.get("style_anchor") or self.COMIC_STYLE_ANCHOR}
本图脚本：{panel_json}

要求：
1. 只生成一张“单格漫画”成品图，不要出现 2x2 拼图排版。
1.1 绝对禁止出现分镜边框、四宫格、连环画拼接、九宫格、漫画页排版。
2. 主角固定为输入参考图对应的两只线条小狗：一只小白狗，一只小金毛。
3. 角色形象尽量参考输入图片中的线条小狗外形和气质。
4. 必须严格覆盖本单图脚本中的 scene、dialogue、narration 和 fact_focus，不要遗漏。
5. 风格锚点必须体现：{self.COMIC_STYLE_ANCHOR}
6. 画面重点是新闻场景、角色反应、被夸大的标题、缺失的证据、真实背景与误读之间的对比。
7. 不要把 uncertain、supported、claim、claim_verdicts、citation_ids、e1-e7 等内部术语直接画成大字主视觉。
8. 完全还原脚本内容。可通过对话气泡框，手机屏幕、便签卡片、资料纸张、标题条等中传递信息。
8.1 文字内容优先围绕“疑点、证据缺口、核查结论”，避免无关口号。
8.2 若本图涉及生词/术语（如 WSL2、ROCm、系统性风险、缓存TTL），文字顺序必须先“生词解释”后“判断结论”。
8.3 生词解释要用大白话短句，建议格式“术语=解释”，单条不超过 20 字。
8.4 不强制奇偶图配对或每轮两图，按本单图脚本把信息讲清即可。
9. 不要生成配音、字幕条、播放器按钮、水印、直播 UI、账号名或复杂英文术语海报。
10. 新闻讲解风格，手机端阅读友好，表情生动，非写实，无复杂背景。
11. 只输出最终提示词正文。
""".strip()
        return await self.shared_model_client.generate_text(system_prompt, user_prompt)
    async def _build_wechat_publish(
        self,
        issue: IssuePayload,
        item: IssueItem,
        storage_item_id: str,
        writer: WriterResult,
        fact_check: FactCheckResult,
        image: ImageResult,
        wechat_article: WechatArticleResult,
    ) -> WechatPublishResult | None:
        if not self.wechat_publisher:
            return None

        ordered_episode_images = sorted(image.episode_images, key=lambda episode: episode.image_index)
        body_candidates = [episode.local_image_path or episode.final_image_url for episode in ordered_episode_images if episode.local_image_path or episode.final_image_url]
        cover_candidates = [image.final_image_url, item.cover_image]
        response = await self.wechat_publisher.publish_pipeline_article(
            issue_id=issue.id,
            item_id=storage_item_id,
            title=writer.headline,
            digest=writer.social_caption,
            source_name=item.source,
            source_url=item.article_url,
            social_caption=writer.social_caption,
            wechat_article=wechat_article.model_dump(),
            context_notes=fact_check.context_notes,
            risk_notes=fact_check.risk_notes,
            cover_image_candidates=[value for value in cover_candidates if value],
            body_image_candidates=[value for value in body_candidates if value],
            submit_publish=self.wechat_publisher.settings.normalized_account_mode == "enterprise",
        )
        draft_media_id = str(response.get("draft_result", {}).get("media_id") or "")
        publish_id = str(response.get("publish_result", {}).get("publish_id") or "")
        article_url = str(response.get("publish_result", {}).get("article_url") or "")
        return WechatPublishResult(
            status=str(response.get("status") or "unknown"),
            account_mode=str(response.get("account_mode") or ""),
            publish_mode=str(response.get("publish_mode") or ""),
            workspace_dir=str(response.get("workspace_dir") or ""),
            draft_media_id=draft_media_id,
            publish_id=publish_id,
            article_url=article_url,
            detail=response,
        )

    async def _build_wechat_article(
        self,
        item: IssueItem,
        fact_check: FactCheckResult,
        writer: WriterResult,
    ) -> WechatArticleResult:
        system_prompt = (
            "你是公众号深度稿件编辑。请把事实核查信息改写成适合微信公众号阅读的判断正文。"
            "不要输出内部术语标签，不要输出 markdown。你必须只返回 JSON。"
        )
        user_prompt = f"""
请根据输入生成一个 JSON 对象，字段严格如下：
{{
  "title": "字符串",
  "digest": "字符串，120字以内",
  "lead": "字符串，1段导语",
  "sections": [
    {{
      "heading": "字符串，小标题",
      "content": "字符串，2-4句，通俗可读"
    }}
  ],
  "ending": "字符串，结尾总结"
}}

硬性要求：
1. sections 保持 3 到 5 段。
2. 文风是公众号解释文，不要写成分镜脚本、流程报告、模型输出说明。
3. 不要出现 claim_id、verdict、citation_ids、e1/e2 等内部字段名。
4. 对证据不足的部分要明确“目前没有公开证据”。
5. 对有背景但被夸大的部分要明确“有讨论背景，但新闻说过头”。
6. 允许保留谨慎语气，但要易懂、自然。
7. 不要输出多余字段。

新闻标题：{item.headline}
新闻来源：{item.source}
原文摘要：{item.warning}
事实核查：{json.dumps(fact_check.model_dump(), ensure_ascii=False)}
现有社交文案：{writer.social_caption}
""".strip()

        payload = await self.shared_model_client.generate_json(system_prompt, user_prompt)
        sections_payload = payload.get("sections")
        normalized_sections = []
        if isinstance(sections_payload, list):
            for section in sections_payload:
                if not isinstance(section, dict):
                    continue
                heading = str(section.get("heading") or "").strip()
                content = str(section.get("content") or "").strip()
                if not (heading and content):
                    continue
                normalized_sections.append({"heading": heading, "content": content})

        if not normalized_sections:
            normalized_sections = [
                {"heading": "这条新闻在说什么", "content": str(item.warning).strip()},
                {"heading": "核查后能确认什么", "content": "目前公开信息不足以支持这条爆料中的关键结论，多个核心说法缺少可核验证据。"},
                {"heading": "读者该怎么判断", "content": "先看是否有官方披露与可追溯证据，再判断是否存在标题夸张和因果跳跃。"},
            ]

        title = str(payload.get("title") or writer.headline or item.headline).strip()
        digest = str(payload.get("digest") or writer.social_caption or item.warning).strip()[:120]
        lead = str(payload.get("lead") or item.warning).strip()
        ending = str(payload.get("ending") or "面对争议性新闻，先看证据，再下结论。").strip()
        return WechatArticleResult(
            status="generated",
            title=title,
            digest=digest,
            lead=lead,
            sections=normalized_sections,
            ending=ending,
        )

    def _build_fact_check_evidence_summary(self, claim_evidence: list[ClaimEvidenceBundle]) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        for bundle in claim_evidence:
            top_hits = []
            for hit in bundle.search_hits[:5]:
                top_hits.append(
                    {
                        "url": hit.url,
                        "title": hit.title,
                        "publisher": hit.publisher,
                        "published_at": hit.published_at,
                        "summary": hit.summary,
                        "snippet": hit.snippet,
                        "source_type": hit.source_type,
                        "content_quality": hit.content_quality,
                        "evidence_signal": hit.evidence_signal,
                        "score": hit.score,
                    }
                )
            summaries.append(
                {
                    "claim_id": bundle.claim_id,
                    "queries": bundle.queries,
                    "top_hits": top_hits,
                    "selected_urls": bundle.selected_urls,
                    "has_summary": bundle.has_summary,
                    "official_count": bundle.official_count,
                    "major_media_count": bundle.major_media_count,
                    "independent_domain_count": bundle.independent_domain_count,
                    "evidence_tier": bundle.evidence_tier,
                }
            )
        return summaries

    def _apply_verdict_caps(
        self,
        claims: list[Claim],
        claim_evidence: list[ClaimEvidenceBundle],
        verdicts: list[ClaimVerdict],
    ) -> list[ClaimVerdict]:
        claim_map = {claim.claim_id: claim for claim in claims}
        evidence_map = {bundle.claim_id: bundle for bundle in claim_evidence}
        adjusted: list[ClaimVerdict] = []
        for verdict in verdicts:
            claim = claim_map.get(verdict.claim_id)
            bundle = evidence_map.get(verdict.claim_id)
            if not claim or not bundle:
                adjusted.append(verdict)
                continue
            adjusted.append(
                ClaimVerdict(
                    claim_id=verdict.claim_id,
                    verdict=self._cap_verdict(claim, bundle, verdict.verdict),
                    reason=verdict.reason,
                    citation_ids=verdict.citation_ids,
                )
            )
        return adjusted

    def _cap_verdict(self, claim: Claim, bundle: ClaimEvidenceBundle, verdict: str) -> str:
        order = {
            "unsupported": 0,
            "uncertain": 1,
            "partially_supported": 2,
            "supported": 3,
        }
        reverse_order = {value: key for key, value in order.items()}
        verdict_value = order.get(verdict, order["uncertain"])

        if bundle.evidence_tier == "weak":
            cap = order["uncertain"]
        elif bundle.evidence_tier == "medium":
            cap = order["partially_supported"]
        else:
            cap = order["supported"] if self._is_simple_fact_claim(claim) else order["partially_supported"]

        if self._is_causal_or_motive_claim(claim):
            cap = min(cap, order["partially_supported"])

        return reverse_order[min(verdict_value, cap)]

    def _is_simple_fact_claim(self, claim: Claim) -> bool:
        if claim.claim_type in {"impact", "other"}:
            return False
        if self._is_causal_or_motive_claim(claim):
            return False
        text = f"{claim.text} {claim.predicate}".lower()
        simple_fact_markers = (
            "发布",
            "推出",
            "存在",
            "公告",
            "声明",
            "通报",
            "召开",
            "举行",
            "报道",
            "confirmed",
            "announced",
            "released",
            "launched",
        )
        if claim.claim_type in {"announcement", "event", "time", "number", "scope"}:
            return True if any(marker in text for marker in simple_fact_markers) else claim.claim_type in {"time", "number", "scope"}
        return False

    def _is_causal_or_motive_claim(self, claim: Claim) -> bool:
        text = f"{claim.text} {claim.predicate} {claim.object}".lower()
        markers = (
            "导致",
            "造成",
            "引发",
            "使得",
            "因为",
            "所以",
            "为了",
            "旨在",
            "意在",
            "担忧",
            "恐慌",
            "风险",
            "影响",
            "because",
            "cause",
            "caused",
            "driven by",
            "in order to",
            "impact",
            "risk",
        )
        return claim.claim_type == "impact" or any(marker in text for marker in markers)

    def _build_writer_brief(
        self,
        research: ResearchResult,
        web_research: WebResearchResult,
        fact_check: FactCheckResult,
    ) -> dict[str, Any]:
        evidence_map = {bundle.claim_id: bundle for bundle in web_research.claim_evidence}
        verdict_map = {verdict.claim_id: verdict for verdict in fact_check.claim_verdicts}
        claim_briefs: list[dict[str, Any]] = []

        for claim in research.claims:
            bundle = evidence_map.get(
                claim.claim_id,
                ClaimEvidenceBundle(
                    claim_id=claim.claim_id,
                    status="error",
                    error_stage="missing",
                    error_message="缺少联网检索结果。",
                ),
            )
            verdict = verdict_map.get(claim.claim_id)
            pages = bundle.pages[:2]
            top_hits = bundle.search_hits[:2]
            public_facts: list[str] = []
            citation_urls: list[str] = []

            for page in pages:
                summary_text = str(page.summary or page.excerpt or "").strip()
                if summary_text:
                    public_facts.append(summary_text[:180])
                if page.url and page.url not in citation_urls:
                    citation_urls.append(page.url)
            for hit in top_hits:
                if len(public_facts) >= 3:
                    break
                summary_text = str(hit.summary or hit.snippet or "").strip()
                if summary_text:
                    public_facts.append(summary_text[:180])
                if hit.url and hit.url not in citation_urls:
                    citation_urls.append(hit.url)

            if not public_facts and bundle.status == "error":
                public_facts.append(f"联网检索在 {bundle.error_stage or 'search'} 阶段失败：{bundle.error_message or '未知错误'}")
            elif not public_facts:
                public_facts.append("目前公开检索结果里还没有足够稳定的网页材料。")

            missing_evidence: list[str] = []
            if bundle.status == "error":
                missing_evidence.append("这条 claim 的联网检索没有顺利完成，不能把空结果当成没有事实。")
            if not bundle.selected_urls:
                missing_evidence.append("缺少可直接引用的网页或原始来源链接。")
            if bundle.evidence_tier == "weak":
                missing_evidence.append("目前缺少更强的一手来源、官方页面或多家独立信源互相印证。")
            if verdict and verdict.reason:
                missing_evidence.append(str(verdict.reason).strip()[:180])

            claim_briefs.append(
                {
                    "claim_id": claim.claim_id,
                    "claim_text": claim.text,
                    "claim_type": claim.claim_type,
                    "search_status": bundle.status,
                    "evidence_tier": bundle.evidence_tier,
                    "queries": bundle.queries,
                    "what_publicly_exists": public_facts[:3],
                    "what_is_missing": missing_evidence[:3],
                    "suggested_explainer_line": (str(verdict.reason).strip()[:180] if verdict and verdict.reason else "先讲公开网页里能看到什么，再讲仍然缺什么。"),
                    "citation_urls": citation_urls[:3],
                }
            )

        return {
            "focus": "解释公开事实目前是什么样的，而不是简单宣布新闻真假。",
            "claim_briefs": claim_briefs,
            "background_facts": [str(note) for note in fact_check.context_notes[:4]],
            "tone_guardrails": [str(note) for note in fact_check.risk_notes[:4]],
            "web_research_status": web_research.status,
            "web_research_notes": [str(note) for note in web_research.notes[:4]],
        }
    def _normalize_single_panels(self, raw_panels: Any) -> list[dict[str, Any]]:
        if not isinstance(raw_panels, list):
            return []

        normalized_images: list[dict[str, Any]] = []
        for fallback_index, panel in enumerate(raw_panels, start=1):
            if not isinstance(panel, dict):
                continue
            raw_image_index = panel.get("image_index")
            try:
                image_index = int(raw_image_index or fallback_index)
            except (TypeError, ValueError):
                image_index = fallback_index

            raw_characters = panel.get("characters") if isinstance(panel.get("characters"), list) else []
            normalized_characters: list[dict[str, str]] = []
            for character in raw_characters:
                if not isinstance(character, dict):
                    continue
                normalized_characters.append(
                    {
                        "name": str(character.get("name") or "").strip(),
                        "action": str(character.get("action") or "").strip(),
                        "expression": str(character.get("expression") or "").strip(),
                        "dialogue": str(character.get("dialogue") or "").strip(),
                    }
                )

            normalized_panel = {
                "panel_index": 1,
                "scene": str(panel.get("scene") or "").strip(),
                "characters": normalized_characters,
                "narration": str(panel.get("narration") or "").strip(),
                "fact_focus": str(panel.get("fact_focus") or "").strip(),
                "visual_prompt": str(panel.get("visual_prompt") or "").strip(),
            }
            panel_role = str(panel.get("panel_role") or "").strip()
            image_theme = str(panel.get("image_theme") or panel_role or f"第{image_index}张").strip()
            image_goal = str(panel.get("image_goal") or normalized_panel["fact_focus"]).strip()
            story_beat = str(panel.get("story_beat") or "").strip()
            style_anchor = str(panel.get("style_anchor") or self.COMIC_STYLE_ANCHOR).strip()
            normalized_images.append(
                {
                    "image_index": image_index,
                    "image_theme": image_theme,
                    "image_goal": image_goal,
                    "story_beat": story_beat,
                    "style_anchor": style_anchor,
                    "panels": [normalized_panel],
                }
            )
        normalized_images.sort(key=lambda item: int(item.get("image_index") or 0))
        for index, image in enumerate(normalized_images, start=1):
            image["image_index"] = index
            if not image.get("image_theme"):
                image["image_theme"] = f"第{index}张"
        return normalized_images
    def _sanitize_image_prompt(self, prompt: str) -> str:
        sanitized = str(prompt).strip()
        sanitized = sanitized.replace("\r", " ").replace("\n", " ")
        sanitized = re.sub(r"\s+", " ", sanitized)

        replacements = {
            "冒火": "红色强调",
            "爆炸": "图标强调",
            "燃烧": "视觉强调",
            "崩盘": "大幅波动",
            "爆跌": "明显下跌",
            "暴跌": "下跌",
            "恐慌": "紧张",
            "惊恐": "吃惊",
            "警告": "提醒",
            "警报": "提示",
            "正式警告": "公开提醒",
            "危险": "风险",
            "失控": "异常",
            "紧急开会": "临时会议传闻",
            "系统性金融风险": "更广泛的金融影响讨论",
            "华尔街": "金融市场",
            "鲍威尔": "金融界人士",
            "2万亿": "较大规模数字",
            "万亿": "大额数字",
        }
        for old, new in replacements.items():
            sanitized = sanitized.replace(old, new)

        sanitized = re.sub(r"[0-9]+万亿", "大额数字", sanitized)
        sanitized = re.sub(r"[0-9]+亿", "较大数字", sanitized)
        sanitized = re.sub(r"(特朗普|拜登|马斯克|OpenAI|Anthropic|Claude)(?=\S*)", "相关方", sanitized)
        sanitized = re.sub(r"[“\"].{6,30}?[”\"]", "资料标题", sanitized)

        if len(sanitized) > 220:
            sanitized = sanitized[:220].rstrip("，。；：,;: ")

        suffix = (
            "；整体采用温和、卡通化、象征性的新闻解释插画，"
            "参考输入图片中的线条小狗形象，使用资料卡片、便签、屏幕、简化图表和道具表达信息，"
            "不要出现可读的大字标题，不要出现真实政治或商界人物肖像、机构标识、火焰、爆炸、崩塌、警报灯、惊恐人群、"
            "灾难现场、对抗场景或强刺激词语。"
        )
        if suffix not in sanitized:
            sanitized = f"{sanitized}{suffix}"
        return sanitized

    def _save_story_scripts(
        self,
        storage_item_id: str,
        headline: str,
        social_caption: str,
        video_topic: str,
        images: list[dict[str, Any]],
    ) -> str:
        SCRIPT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(SCRIPT_DB_PATH) as conn:
            self._ensure_story_script_table(conn)
            conn.execute("DELETE FROM writer_image_scripts WHERE item_id = ?", (storage_item_id,))
            for image in images:
                cursor = conn.execute(
                    """
                    INSERT INTO writer_image_scripts (
                        item_id,
                        headline,
                        social_caption,
                        video_topic,
                        image_index,
                        image_theme,
                        image_goal,
                        story_beat,
                        style_anchor,
                        script_json,
                        generation_status,
                        image_prompt,
                        final_image_url,
                        local_image_path
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        storage_item_id,
                        headline,
                        social_caption,
                        video_topic,
                        int(image.get("image_index") or 0),
                        str(image.get("image_theme") or ""),
                        str(image.get("image_goal") or ""),
                        str(image.get("story_beat") or ""),
                        str(image.get("style_anchor") or self.COMIC_STYLE_ANCHOR),
                        json.dumps(image, ensure_ascii=False),
                        "pending",
                        "",
                        "",
                        "",
                    ),
                )
                image["script_record_id"] = int(cursor.lastrowid)
            conn.commit()
        return str(SCRIPT_DB_PATH)

    def _load_story_scripts(self, item_id: str) -> list[dict[str, Any]]:
        if not SCRIPT_DB_PATH.exists():
            return []
        SCRIPT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(SCRIPT_DB_PATH) as conn:
            self._ensure_story_script_table(conn)
            rows = conn.execute(
                """
                SELECT id, image_index, image_theme, image_goal, story_beat, style_anchor, script_json,
                       generation_status, image_prompt, final_image_url, local_image_path
                FROM writer_image_scripts
                WHERE item_id = ?
                ORDER BY image_index ASC, id ASC
                """,
                (item_id,),
            ).fetchall()
        loaded: list[dict[str, Any]] = []
        for row in rows:
            script_json = str(row[6] or "")
            try:
                payload = json.loads(script_json) if script_json else {}
            except json.JSONDecodeError:
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            payload["script_record_id"] = int(row[0])
            payload["image_index"] = int(row[1] or 0)
            payload["image_theme"] = str(row[2] or payload.get("image_theme") or "")
            payload["image_goal"] = str(row[3] or payload.get("image_goal") or "")
            payload["story_beat"] = str(row[4] or payload.get("story_beat") or "")
            payload["style_anchor"] = str(row[5] or payload.get("style_anchor") or self.COMIC_STYLE_ANCHOR)
            payload["generation_status"] = str(row[7] or "pending")
            payload["image_prompt"] = str(row[8] or "")
            payload["final_image_url"] = str(row[9] or "")
            payload["local_image_path"] = str(row[10] or "")
            loaded.append(payload)
        return loaded

    def _mark_story_script_generating(self, item_id: str, image_index: int) -> None:
        SCRIPT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(SCRIPT_DB_PATH) as conn:
            self._ensure_story_script_table(conn)
            conn.execute(
                "UPDATE writer_image_scripts SET generation_status = ?, generated_at = CURRENT_TIMESTAMP WHERE item_id = ? AND image_index = ?",
                ("generating", item_id, image_index),
            )
            conn.commit()

    def _update_story_script_result(
        self,
        item_id: str,
        image_index: int,
        image_prompt: str,
        final_image_url: str,
        local_image_path: str,
        generation_status: str,
    ) -> None:
        SCRIPT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(SCRIPT_DB_PATH) as conn:
            self._ensure_story_script_table(conn)
            conn.execute(
                """
                UPDATE writer_image_scripts
                SET image_prompt = ?,
                    final_image_url = ?,
                    local_image_path = ?,
                    generation_status = ?,
                    generated_at = CURRENT_TIMESTAMP
                WHERE item_id = ? AND image_index = ?
                """,
                (image_prompt, final_image_url, local_image_path, generation_status, item_id, image_index),
            )
            conn.commit()

    def _ensure_story_script_table(self, conn: sqlite3.Connection) -> None:
        SCRIPT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS writer_image_scripts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id TEXT NOT NULL,
                headline TEXT NOT NULL,
                social_caption TEXT NOT NULL,
                video_topic TEXT NOT NULL,
                image_index INTEGER NOT NULL,
                image_theme TEXT NOT NULL,
                image_goal TEXT NOT NULL,
                story_beat TEXT NOT NULL DEFAULT '',
                style_anchor TEXT NOT NULL DEFAULT '',
                script_json TEXT NOT NULL,
                generation_status TEXT NOT NULL DEFAULT 'pending',
                image_prompt TEXT NOT NULL DEFAULT '',
                final_image_url TEXT NOT NULL DEFAULT '',
                local_image_path TEXT NOT NULL DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                generated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(writer_image_scripts)").fetchall()}
        required_columns = {
            "story_beat": "ALTER TABLE writer_image_scripts ADD COLUMN story_beat TEXT NOT NULL DEFAULT ''",
            "style_anchor": "ALTER TABLE writer_image_scripts ADD COLUMN style_anchor TEXT NOT NULL DEFAULT ''",
            "generation_status": "ALTER TABLE writer_image_scripts ADD COLUMN generation_status TEXT NOT NULL DEFAULT 'pending'",
            "image_prompt": "ALTER TABLE writer_image_scripts ADD COLUMN image_prompt TEXT NOT NULL DEFAULT ''",
            "final_image_url": "ALTER TABLE writer_image_scripts ADD COLUMN final_image_url TEXT NOT NULL DEFAULT ''",
            "local_image_path": "ALTER TABLE writer_image_scripts ADD COLUMN local_image_path TEXT NOT NULL DEFAULT ''",
            "generated_at": "ALTER TABLE writer_image_scripts ADD COLUMN generated_at TEXT DEFAULT CURRENT_TIMESTAMP",
        }
        for column_name, statement in required_columns.items():
            if column_name not in existing_columns:
                conn.execute(statement)
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_writer_image_scripts_item_image ON writer_image_scripts(item_id, image_index)"
        )
        conn.commit()

    async def _save_generated_image(self, item_id: str, image_index: int, final_image_url: str) -> str:
        normalized = str(final_image_url or "").strip()
        if not normalized:
            return ""
        target_dir = GENERATED_IMAGE_ROOT / self._safe_name(item_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_stem = target_dir / f"{image_index:03d}"

        if normalized.startswith("data:image/"):
            return str(self._write_data_url_image(normalized, target_stem))

        if normalized.startswith("http://") or normalized.startswith("https://"):
            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    response = await client.get(normalized)
                    response.raise_for_status()
                    suffix = self._guess_suffix_from_url_or_type(normalized, response.headers.get("Content-Type", ""))
                    target_path = target_stem.with_suffix(suffix)
                    target_path.write_bytes(response.content)
                    return str(target_path)
            except httpx.HTTPError:
                # Keep the pipeline moving when the remote image URL is temporarily unreachable.
                return ""

        local_path = Path(normalized)
        if local_path.exists() and local_path.is_file():
            target_path = target_stem.with_suffix(local_path.suffix or ".png")
            target_path.write_bytes(local_path.read_bytes())
            return str(target_path)

        return ""

    def _write_data_url_image(self, data_url: str, target_stem: Path) -> Path:
        prefix, _, payload = data_url.partition(",")
        image_format = "png"
        if ";base64" in prefix and "/" in prefix:
            image_format = prefix.split("/")[-1].split(";")[0] or "png"
        image_bytes = base64.b64decode(payload)
        suffix = ".png" if image_format == "png" else f".{image_format}"
        target_path = target_stem.with_suffix(suffix)
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

    def _write_debug_json(self, item_id: str, filename: str, payload: dict[str, Any]) -> str:
        target_dir = DEBUG_OUTPUT_ROOT / self._safe_name(item_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / filename
        target_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(target_path)

    def _join_article_body(self, item: IssueItem) -> str:
        parts = [str(part).strip() for part in item.expanded_body if str(part).strip()]
        return "\n".join(parts)

    def _safe_name(self, value: str) -> str:
        normalized = "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in str(value or "workspace").strip())
        return normalized[:80] or "workspace"

    def _build_storage_item_id(self, run_stamp: str, item: IssueItem) -> str:
        base_value = item.id or str(item.news_id or "") or item.headline or "workspace"
        return self._safe_name(f"{run_stamp}-{base_value}")


































