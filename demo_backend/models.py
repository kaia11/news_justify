from typing import Any, Literal

from pydantic import BaseModel, Field


SourceType = Literal["primary", "secondary", "low_confidence"]
VerdictType = Literal["supported", "partially_supported", "uncertain", "unsupported"]
StageStatus = Literal["mocked", "generated", "pending_config", "partial_failure"]
ClaimType = Literal["event", "announcement", "number", "time", "scope", "impact", "other"]
SearchSourceType = Literal["official", "major_media", "secondary", "social", "unknown"]


class NewsItem(BaseModel):
    id: str
    news_id: int | None = None
    title: str
    summary: str
    url: str
    source: str
    score: str
    cover_url: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)


class IssueItem(BaseModel):
    id: str
    news_id: int | None = None
    source: str
    headline: str
    warning: str
    article_url: str
    cover_image: str = ""
    expanded_body: list[str] = Field(default_factory=list)


class IssuePayload(BaseModel):
    id: str
    title: str
    subtitle: str
    footer: str
    source_mode: Literal["mock", "cloud"]
    items: list[IssueItem]


class Claim(BaseModel):
    claim_id: str
    text: str
    claim_type: ClaimType
    subject: str
    predicate: str
    object: str
    time_scope: str = ""
    priority: int = 3


class EvidenceItem(BaseModel):
    evidence_id: str
    claim_id: str
    title: str
    url: str
    publisher: str
    type: SourceType
    note: str = ""


class SearchHit(BaseModel):
    query: str
    title: str
    url: str
    snippet: str = ""
    summary: str = ""
    publisher: str = ""
    published_at: str = ""
    domain: str = ""
    language: str = ""
    score: float = 0.0
    source_type: SearchSourceType = "unknown"
    content_quality: str = "empty"
    evidence_signal: str = "weak_signal"


class ExtractedPage(BaseModel):
    url: str
    title: str = ""
    domain: str = ""
    published_at: str = ""
    raw_content: str = ""
    excerpt: str = ""
    summary: str = ""
    source_type: SearchSourceType = "unknown"
    content_quality: str = "empty"
    evidence_signal: str = "weak_signal"


class ClaimEvidenceBundle(BaseModel):
    claim_id: str
    status: str = "ok"
    error_stage: str = ""
    error_message: str = ""
    queries: list[str] = Field(default_factory=list)
    search_hits: list[SearchHit] = Field(default_factory=list)
    selected_urls: list[str] = Field(default_factory=list)
    pages: list[ExtractedPage] = Field(default_factory=list)
    has_summary: bool = False
    official_count: int = 0
    major_media_count: int = 0
    independent_domain_count: int = 0
    evidence_tier: str = "weak"


class WebResearchResult(BaseModel):
    status: StageStatus
    provider: str = ""
    claim_evidence: list[ClaimEvidenceBundle] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ClaimVerdict(BaseModel):
    claim_id: str
    verdict: VerdictType
    reason: str
    citation_ids: list[str] = Field(default_factory=list)


class ResearchResult(BaseModel):
    status: StageStatus
    claims: list[Claim]
    reference_sources: list[EvidenceItem]


class FactCheckResult(BaseModel):
    status: StageStatus
    claim_verdicts: list[ClaimVerdict]
    risk_notes: list[str]
    context_notes: list[str]


class WriterResult(BaseModel):
    status: StageStatus
    headline: str
    social_caption: str
    video_topic: str = ""
    image_count: int = 0
    images: list[dict[str, Any]] = Field(default_factory=list)
    comic_script: list[dict[str, Any]] = Field(default_factory=list)
    script_db_path: str = ""


class WechatArticleSection(BaseModel):
    heading: str
    summary: str = ""
    key_point: str = ""
    explain: str = ""
    transition: str = ""
    content: str = ""


class WechatArticleResult(BaseModel):
    status: StageStatus
    title: str
    digest: str
    lead: str
    sections: list[WechatArticleSection] = Field(default_factory=list)
    ending: str = ""


class EpisodeImage(BaseModel):
    image_index: int
    image_theme: str
    bottom_caption: str = ""
    image_prompt: str
    original_image_prompt: str = ""
    safe_retry_prompt: str = ""
    used_safe_retry: bool = False
    final_image_url: str
    local_image_path: str = ""
    generation_status: str = "pending"
    script_record_id: int = 0


class ImageResult(BaseModel):
    status: StageStatus
    image_prompt: str
    original_image_prompt: str = ""
    safe_retry_prompt: str = ""
    used_safe_retry: bool = False
    final_image_url: str
    episode_images: list[EpisodeImage] = Field(default_factory=list)


class WechatPublishResult(BaseModel):
    status: str
    account_mode: str = ""
    publish_mode: str = ""
    workspace_dir: str = ""
    draft_media_id: str = ""
    publish_id: str = ""
    article_url: str = ""
    detail: dict[str, Any] = Field(default_factory=dict)


class DemoPipelineItemResult(BaseModel):
    issue_item: IssueItem
    research: ResearchResult
    web_research: WebResearchResult
    fact_check: FactCheckResult
    writer: WriterResult
    image: ImageResult
    wechat_article: WechatArticleResult
    wechat_publish: WechatPublishResult | None = None
    debug_artifacts: dict[str, str] = Field(default_factory=dict)


class DemoPipelineResponse(BaseModel):
    source_mode: Literal["mock", "cloud"]
    issue: IssuePayload
    model_strategy: str
    model_configured: bool
    model_strategy_details: dict[str, str] = Field(default_factory=dict)
    results: list[DemoPipelineItemResult]



