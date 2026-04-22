from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from demo_backend.config import Settings
from demo_backend.models import Claim, ClaimEvidenceBundle, ExtractedPage, IssueItem, ResearchResult, SearchHit, WebResearchResult


class WebResearchService:
    SEARCH_URL = "https://api.bochaai.com/v1/web-search"
    QIANFAN_SEARCH_URL = "https://qianfan.baidubce.com/v2/ai_search/chat/completions"
    OFFICIAL_DOMAINS = (
        ".gov.cn",
        ".gov",
        ".edu.cn",
        ".edu",
        "openai.com",
        "anthropic.com",
        "deepseek.com",
        "aliyun.com",
        "alibabagroup.com",
        "tencent.com",
        "baidu.com",
    )
    MAJOR_MEDIA_DOMAINS = (
        "reuters.com",
        "apnews.com",
        "bbc.com",
        "nytimes.com",
        "wsj.com",
        "caixin.com",
        "thepaper.cn",
        "36kr.com",
        "ifeng.com",
        "xinhuanet.com",
        "people.com.cn",
    )
    SOCIAL_DOMAINS = (
        "x.com",
        "twitter.com",
        "weibo.com",
        "zhihu.com",
        "bilibili.com",
        "douyin.com",
        "toutiao.com",
    )
    RELATIVE_TIME_TERMS = ("刚刚", "刚才", "今天", "昨日", "昨天", "昨晚", "近日", "近期", "最新", "目前", "当日")

    def __init__(self, settings: Settings):
        self.settings = settings
        self._runtime_notes: list[str] = []

    async def run(self, item: IssueItem, research: ResearchResult) -> WebResearchResult:
        primary_provider = self._normalize_provider(self.settings.factcheck_search_provider)
        provider_chain = self._build_provider_chain()
        if not self.settings.factcheck_enable_web_search:
            return WebResearchResult(
                status="pending_config",
                provider=primary_provider,
                notes=["FACTCHECK_ENABLE_WEB_SEARCH=false，联网检索已关闭。"],
            )
        if not provider_chain:
            return WebResearchResult(
                status="pending_config",
                provider=primary_provider,
                notes=[self._build_missing_provider_message(primary_provider)],
            )

        bundles: list[ClaimEvidenceBundle] = []
        self._runtime_notes = []
        notes: list[str] = []
        has_failure = False
        for claim in research.claims:
            queries = self.build_queries_for_claim(claim, item)
            try:
                bundles.append(await self.collect_claim_evidence(claim, item, queries))
            except Exception as exc:
                has_failure = True
                error_message = self._format_exception_message(exc)
                notes.append(f"claim {claim.claim_id} 联网检索失败：{error_message}")
                bundles.append(
                    self._build_error_bundle(
                        claim_id=claim.claim_id,
                        queries=queries,
                        error_stage="search",
                        error_message=error_message,
                    )
                )
        status = "partial_failure" if has_failure else "generated"
        notes.extend(self._runtime_notes)
        return WebResearchResult(
            status=status,
            provider=" -> ".join(provider_chain),
            claim_evidence=bundles,
            notes=notes,
        )

    async def collect_claim_evidence(self, claim: Claim, item: IssueItem, queries: list[str] | None = None) -> ClaimEvidenceBundle:
        normalized_queries = queries or self.build_queries_for_claim(claim, item)
        if not normalized_queries:
            return self._build_error_bundle(
                claim_id=claim.claim_id,
                queries=[],
                error_stage="build_queries",
                error_message="未生成可用检索词，已跳过联网检索。",
            )

        hits = await self.search_queries(claim, item, normalized_queries)
        selected_urls: list[str] = []
        pages: list[ExtractedPage] = []
        selected_source_keys: set[tuple[str, str]] = set()
        for hit in hits:
            if not hit.url or hit.url in selected_urls:
                continue
            source_key = self._build_independent_source_key(hit)
            if source_key in selected_source_keys:
                continue
            selected_urls.append(hit.url)
            selected_source_keys.add(source_key)
            pages.append(
                ExtractedPage(
                    url=hit.url,
                    title=hit.title,
                    domain=hit.domain,
                    published_at=hit.published_at,
                    raw_content="",
                    excerpt=hit.snippet,
                    summary=hit.summary,
                    source_type=hit.source_type,
                    content_quality=hit.content_quality,
                    evidence_signal=hit.evidence_signal,
                )
            )
            if len(selected_urls) >= min(3, len(hits)):
                break

        official_count = self._count_independent_hits_by_type(hits, "official")
        major_media_count = self._count_independent_hits_by_type(hits, "major_media")
        independent_domain_count = len(self._build_independent_source_keys(hits))
        has_summary = any(bool(hit.summary.strip()) for hit in hits)
        evidence_tier = self._compute_evidence_tier(has_summary, official_count, major_media_count, independent_domain_count)

        return ClaimEvidenceBundle(
            claim_id=claim.claim_id,
            status="ok",
            queries=normalized_queries,
            search_hits=hits,
            selected_urls=selected_urls,
            pages=pages,
            has_summary=has_summary,
            official_count=official_count,
            major_media_count=major_media_count,
            independent_domain_count=independent_domain_count,
            evidence_tier=evidence_tier,
        )

    def build_queries_for_claim(self, claim: Claim, item: IssueItem) -> list[str]:
        subject = self._clean_query_text(claim.subject)
        predicate = self._clean_query_text(claim.predicate)
        obj = self._clean_query_text(claim.object)
        time_scope = self._normalize_time_scope(claim.time_scope)
        headline = self._clean_query_text(item.headline)
        queries: list[str] = []

        def add_query(value: str) -> None:
            normalized = self._clean_query_text(value)
            if not normalized or self._looks_like_query_noise(normalized):
                return
            if normalized not in queries:
                queries.append(normalized)

        add_query(claim.text)
        add_query(f"{subject} {predicate} {obj}")
        if time_scope:
            add_query(f"{subject} {time_scope} {predicate}")
        if headline and subject:
            add_query(f"{subject} {headline}")
        if self._needs_english_queries(claim, item):
            add_query(f"{subject} {predicate} {obj} official")
            add_query(f"{subject} {predicate} Reuters")
        else:
            add_query(f"{subject} 官方 {predicate} {obj}")
            add_query(f"{subject} 媒体报道 {predicate} {obj}")

        limit = max(1, int(self.settings.factcheck_max_queries_per_claim or 5))
        return queries[:limit]

    async def search_queries(self, claim: Claim, item: IssueItem, queries: list[str]) -> list[SearchHit]:
        if not queries:
            return []

        all_hits: list[SearchHit] = []
        seen_urls: set[str] = set()
        provider_chain = self._build_provider_chain()
        if not provider_chain:
            raise RuntimeError(self._build_missing_provider_message(self._normalize_provider(self.settings.factcheck_search_provider)))
        for query in queries:
            data = None
            provider_used = ""
            last_error: Exception | None = None
            for provider in provider_chain:
                try:
                    data = await self._search_single_query(provider, query)
                    provider_used = provider
                    break
                except Exception as exc:
                    last_error = exc
                    if provider != provider_chain[-1]:
                        self._runtime_notes.append(
                            f"query={query} 使用 {provider} 检索失败，已自动切换到 {provider_chain[provider_chain.index(provider) + 1]}：{self._format_exception_message(exc)}"
                        )
                        continue
                    raise
            if data is None:
                if last_error:
                    raise last_error
                continue
            for hit in self._parse_search_hits(provider_used, claim, item, query, data):
                if hit.url in seen_urls:
                    continue
                seen_urls.add(hit.url)
                all_hits.append(hit)
        all_hits.sort(key=lambda value: value.score, reverse=True)
        return all_hits

    async def _search_single_query(self, provider: str, query: str) -> dict:
        if provider == "bocha":
            return await self._search_single_query_via_bocha(query)
        if provider == "baidu":
            return await self._search_single_query_via_baidu(query)
        raise RuntimeError(f"暂不支持的联网检索 provider：{provider}")

    async def _search_single_query_via_bocha(self, query: str) -> dict:
        payload = {
            "query": query,
            "summary": True,
            "count": max(1, int(self.settings.factcheck_max_results_per_query or 5)),
        }
        if self.settings.factcheck_news_only:
            payload["freshness"] = "noLimit"
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                self.SEARCH_URL,
                headers={
                    "Authorization": f"Bearer {self.settings.bocha_api_key.strip()}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            return self._raise_for_search_error(response, provider="bocha", query=query)

    async def _search_single_query_via_baidu(self, query: str) -> dict:
        payload = {
            "messages": [{"content": query, "role": "user"}],
            "stream": False,
            "model": self.settings.qianfan_search_model.strip() or "ernie-4.5-turbo-32k",
            "search_source": self.settings.qianfan_search_source.strip() or "baidu_search_v2",
            "resource_type_filter": [
                {
                    "type": "web",
                    "top_k": max(1, min(int(self.settings.factcheck_max_results_per_query or 5), 20)),
                }
            ],
            "search_mode": "required",
            "enable_deep_search": False,
            "enable_followup_queries": False,
            "enable_corner_markers": False,
        }
        if self.settings.factcheck_news_only:
            payload["search_recency_filter"] = "year"
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                self.QIANFAN_SEARCH_URL,
                headers={
                    "Authorization": f"Bearer {self.settings.qianfan_api_key.strip()}",
                    "X-Appbuilder-Authorization": f"Bearer {self.settings.qianfan_api_key.strip()}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            return self._raise_for_search_error(response, provider="baidu", query=query)

    def _raise_for_search_error(self, response: httpx.Response, provider: str, query: str) -> dict:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            response_body = response.text.strip()
            if response_body:
                raise RuntimeError(f"provider={provider}，query={query}，HTTP {response.status_code}，响应内容：{response_body}") from exc
            raise RuntimeError(f"provider={provider}，query={query}，HTTP {response.status_code}") from exc
        data = response.json()
        if isinstance(data, dict) and str(data.get("code") or "").strip():
            message = str(data.get("message") or "").strip() or "未知错误"
            raise RuntimeError(f"provider={provider}，query={query}，code={data.get('code')}，message={message}")
        return data

    def _parse_search_hits(self, provider: str, claim: Claim, item: IssueItem, query: str, payload: dict) -> list[SearchHit]:
        if provider == "baidu":
            return self._parse_baidu_search_hits(claim, item, query, payload)

        candidate_lists = [
            payload.get("data", {}).get("webPages", {}).get("value") if isinstance(payload.get("data"), dict) else None,
            payload.get("webPages", {}).get("value") if isinstance(payload.get("webPages"), dict) else None,
            payload.get("data", {}).get("items") if isinstance(payload.get("data"), dict) else None,
            payload.get("items"),
            payload.get("data"),
        ]
        records = next((value for value in candidate_lists if isinstance(value, list)), [])
        hits: list[SearchHit] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            url = str(record.get("url") or record.get("link") or record.get("displayUrl") or "").strip()
            title = str(record.get("name") or record.get("title") or "").strip()
            summary = self._clean_summary_or_snippet(record.get("summary"))
            snippet = self._clean_summary_or_snippet(record.get("snippet") or record.get("description"))
            if not (url and title):
                continue
            domain = urlparse(url).netloc.lower()
            source_type = self._infer_source_type(domain)
            publisher = str(record.get("siteName") or record.get("site_name") or domain or "").strip()
            published_at = str(
                record.get("datePublished")
                or record.get("published_at")
                or record.get("publishedAt")
                or record.get("dateLastCrawled")
                or ""
            ).strip()
            language = str(record.get("language") or "").strip()
            content_quality = "summary" if summary else ("snippet" if snippet else "empty")
            evidence_signal = self._build_evidence_signal(source_type=source_type, content_quality=content_quality)
            score = self._score_hit(
                claim=claim,
                item=item,
                title=title,
                summary=summary,
                snippet=snippet,
                domain=domain,
                query=query,
                source_type=source_type,
                published_at=published_at,
            )
            hits.append(
                SearchHit(
                    query=query,
                    title=title,
                    url=url,
                    snippet=snippet,
                    summary=summary,
                    publisher=publisher,
                    published_at=published_at,
                    domain=domain,
                    language=language,
                    score=score,
                    source_type=source_type,
                    content_quality=content_quality,
                    evidence_signal=evidence_signal,
                )
            )
        return hits

    def _parse_baidu_search_hits(self, claim: Claim, item: IssueItem, query: str, payload: dict) -> list[SearchHit]:
        records = payload.get("references")
        if not isinstance(records, list):
            return []

        hits: list[SearchHit] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            if str(record.get("type") or "").strip().lower() != "web":
                continue
            url = str(record.get("url") or "").strip()
            title = str(record.get("title") or "").strip()
            snippet = self._clean_summary_or_snippet(record.get("content"))
            if not (url and title):
                continue
            domain = urlparse(url).netloc.lower()
            source_type = self._infer_source_type(domain)
            publisher = str(record.get("web_anchor") or domain or "").strip()
            published_at = str(record.get("date") or "").strip()
            score = self._score_hit(
                claim=claim,
                item=item,
                title=title,
                summary="",
                snippet=snippet,
                domain=domain,
                query=query,
                source_type=source_type,
                published_at=published_at,
            )
            hits.append(
                SearchHit(
                    query=query,
                    title=title,
                    url=url,
                    snippet=snippet,
                    summary="",
                    publisher=publisher,
                    published_at=published_at,
                    domain=domain,
                    language="zh-CN",
                    score=score,
                    source_type=source_type,
                    content_quality="snippet" if snippet else "empty",
                    evidence_signal=self._build_evidence_signal(
                        source_type=source_type,
                        content_quality="snippet" if snippet else "empty",
                    ),
                )
            )
        return hits

    def _score_hit(
        self,
        claim: Claim,
        item: IssueItem,
        title: str,
        summary: str,
        snippet: str,
        domain: str,
        query: str,
        source_type: str,
        published_at: str,
    ) -> float:
        score = 0.0
        haystack = f"{title} {summary} {snippet}".lower()
        for token in [value.lower() for value in query.split() if len(value.strip()) >= 2]:
            if token in haystack:
                score += 1.0
        if source_type == "official":
            score += 6.0
        elif source_type == "major_media":
            score += 4.0
        elif source_type == "secondary":
            score += 2.0
        elif source_type == "social":
            score -= 1.0
        if summary:
            score += 1.5
        elif snippet:
            score += 0.5
        if domain.endswith(".gov.cn") or domain.endswith(".gov"):
            score += 2.0
        score += self._score_recency(claim, item, published_at)
        return score

    def _score_recency(self, claim: Claim, item: IssueItem, published_at: str) -> float:
        if claim.claim_type not in {"event", "announcement"}:
            return 0.0
        published_dt = self._parse_datetime(published_at)
        if not published_dt:
            return 0.0
        reference_dt = self._extract_reference_datetime(item) or datetime.now(timezone.utc)
        day_gap = abs((reference_dt - published_dt).days)
        if day_gap <= 3:
            return 3.0
        if day_gap <= 7:
            return 2.0
        if day_gap <= 30:
            return 1.0
        if day_gap > 180:
            return -2.0
        return 0.0

    def _compute_evidence_tier(self, has_summary: bool, official_count: int, major_media_count: int, independent_domain_count: int) -> str:
        if has_summary and (official_count >= 1 or major_media_count >= 2):
            return "strong"
        if has_summary and independent_domain_count >= 2:
            return "medium"
        return "weak"

    def _build_evidence_signal(self, source_type: str, content_quality: str) -> str:
        if content_quality == "summary" and source_type == "official":
            return "official_summary"
        if content_quality == "summary" and source_type == "major_media":
            return "major_media_summary"
        if content_quality == "snippet":
            return "single_snippet"
        return "weak_signal"

    def _normalize_time_scope(self, time_scope: str) -> str:
        normalized = self._clean_query_text(time_scope)
        if not normalized:
            return ""
        if any(term in normalized for term in self.RELATIVE_TIME_TERMS):
            return ""
        return normalized

    def _strip_relative_time_terms(self, value: str) -> str:
        normalized = str(value or "").strip()
        for term in self.RELATIVE_TIME_TERMS:
            normalized = normalized.replace(term, " ")
        return " ".join(normalized.split())

    def _clean_query_text(self, value: str) -> str:
        normalized = self._strip_relative_time_terms(str(value or "").strip())
        normalized = normalized.replace("，", " ").replace("。", " ").replace("：", " ").replace("；", " ")
        normalized = normalized.replace(",", " ").replace(".", " ").replace(":", " ").replace(";", " ")
        return " ".join(normalized.split())

    def _looks_like_query_noise(self, value: str) -> bool:
        normalized = str(value or "").strip()
        if not normalized:
            return True
        if normalized in self.RELATIVE_TIME_TERMS:
            return True
        tokens = normalized.split()
        return all(token in self.RELATIVE_TIME_TERMS for token in tokens)

    def _clean_summary_or_snippet(self, value: object) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        cut_markers = (
            "免责声明",
            "相关阅读",
            "延伸阅读",
            "来源:",
            "来源：",
            "责任编辑",
        )
        for marker in cut_markers:
            index = text.find(marker)
            if index > 0:
                text = text[:index].strip()
        return " ".join(text.split())

    def _extract_reference_datetime(self, item: IssueItem) -> datetime | None:
        raw = item.article_url or ""
        for token in str(raw).replace("_", "-").split('/'):
            dt = self._parse_datetime(token)
            if dt:
                return dt
        for token in str(item.id or "").replace("_", "-").split('-'):
            dt = self._parse_datetime(token)
            if dt:
                return dt
        compact = ''.join(ch for ch in str(item.id or '') if ch.isdigit())
        if len(compact) >= 8:
            dt = self._parse_datetime(compact[:8])
            if dt:
                return dt
        return None

    def _parse_datetime(self, value: str) -> datetime | None:
        normalized = str(value or "").strip()
        if not normalized:
            return None
        candidates = [normalized]
        if normalized.endswith('Z'):
            candidates.append(normalized[:-1] + '+00:00')
        formats = (
            "%Y-%m-%d",
            "%Y%m%d",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%d %H:%M:%S",
        )
        for candidate in candidates:
            try:
                parsed = datetime.fromisoformat(candidate)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed
            except ValueError:
                pass
            for fmt in formats:
                try:
                    parsed = datetime.strptime(candidate, fmt)
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=timezone.utc)
                    return parsed
                except ValueError:
                    continue
        return None

    def _canonical_domain(self, domain: str) -> str:
        normalized = str(domain or "").lower().strip()
        return normalized[4:] if normalized.startswith("www.") else normalized

    def _normalize_text_for_fingerprint(self, value: str) -> str:
        return "".join(ch.lower() for ch in str(value or "") if ch.isalnum())

    def _build_independent_source_key(self, hit: SearchHit) -> tuple[str, str]:
        domain = self._canonical_domain(hit.domain)
        if not domain:
            return ("", "")
        content_basis = hit.summary or hit.snippet or hit.title
        fingerprint = self._normalize_text_for_fingerprint(content_basis)[:120]
        if not fingerprint:
            fingerprint = self._normalize_text_for_fingerprint(hit.title)[:120]
        return (domain, fingerprint)

    def _build_independent_source_keys(self, hits: list[SearchHit]) -> set[tuple[str, str]]:
        independent_keys: set[tuple[str, str]] = set()
        seen_content: set[str] = set()
        for hit in hits:
            key = self._build_independent_source_key(hit)
            if not key[0]:
                continue
            if key[1] and key[1] in seen_content:
                continue
            independent_keys.add(key)
            if key[1]:
                seen_content.add(key[1])
        return independent_keys

    def _build_error_bundle(self, claim_id: str, queries: list[str], error_stage: str, error_message: str) -> ClaimEvidenceBundle:
        return ClaimEvidenceBundle(
            claim_id=claim_id,
            status="error",
            error_stage=error_stage,
            error_message=error_message,
            queries=queries,
        )

    def _format_exception_message(self, exc: Exception) -> str:
        message = str(exc).strip()
        return message or exc.__class__.__name__

    def _normalize_provider(self, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in {"qianfan", "baidu", "baidu_search"}:
            return "baidu"
        if normalized == "bocha":
            return "bocha"
        return normalized

    def _build_provider_chain(self) -> list[str]:
        providers: list[str] = []
        for raw_provider in (
            self.settings.factcheck_search_provider,
            self.settings.factcheck_fallback_provider,
        ):
            provider = self._normalize_provider(raw_provider)
            if not provider or provider in providers:
                continue
            if self._provider_is_configured(provider):
                providers.append(provider)
        return providers

    def _provider_is_configured(self, provider: str) -> bool:
        if provider == "bocha":
            return bool(self.settings.bocha_api_key.strip())
        if provider == "baidu":
            return bool(self.settings.qianfan_api_key.strip())
        return False

    def _build_missing_provider_message(self, provider: str) -> str:
        if provider == "baidu":
            return "缺少 QIANFAN_API_KEY，且没有可用的 fallback provider，已跳过联网检索。"
        if provider == "bocha":
            return "缺少 BOCHA_API_KEY，且没有可用的 fallback provider，已跳过联网检索。"
        return f"FACTCHECK_SEARCH_PROVIDER={provider or '空'} 未配置可用的 API Key，已跳过联网检索。"
    def _count_independent_hits_by_type(self, hits: list[SearchHit], target_type: str) -> int:
        keys: set[tuple[str, str]] = set()
        seen_content: set[str] = set()
        for hit in hits:
            if hit.source_type != target_type:
                continue
            key = self._build_independent_source_key(hit)
            if not key[0]:
                continue
            if key[1] and key[1] in seen_content:
                continue
            keys.add(key)
            if key[1]:
                seen_content.add(key[1])
        return len(keys)

    def _infer_source_type(self, domain: str) -> str:
        normalized = self._canonical_domain(domain)
        if any(normalized.endswith(item) or normalized == item for item in self.OFFICIAL_DOMAINS):
            return "official"
        if any(normalized.endswith(item) or normalized == item for item in self.MAJOR_MEDIA_DOMAINS):
            return "major_media"
        if any(normalized.endswith(item) or normalized == item for item in self.SOCIAL_DOMAINS):
            return "social"
        if normalized:
            return "secondary"
        return "unknown"

    def _needs_english_queries(self, claim: Claim, item: IssueItem) -> bool:
        if (self.settings.factcheck_search_lang_mode or "auto").strip().lower() != "auto":
            return False
        haystack = f"{claim.text} {item.headline}".lower()
        keywords = ("openai", "anthropic", "claude", "gpt", "google", "meta", "microsoft", "tesla", "nvidia")
        return any(keyword in haystack for keyword in keywords)

