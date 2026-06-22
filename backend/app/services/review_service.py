from __future__ import annotations

import logging
from collections import Counter

from sqlmodel import Session, select

from app.db.models import ReviewAnalysis, utc_now
from app.schemas.common import dump_json, load_json
from app.schemas.review import ReviewItem, SentimentAnalysisResult
from app.services.steam_client import SteamClient

logger = logging.getLogger("steamanalysis.review_service")


PRAISE_KEYWORDS = (
    "优化",
    "剧情",
    "画面",
    "音乐",
    "手感",
    "更新",
    "内容",
    "好玩",
    "稳定",
    "fun",
    "story",
    "graphics",
    "music",
    "performance",
    "update",
)

COMPLAINT_KEYWORDS = (
    "差评",
    "bug",
    "崩溃",
    "卡顿",
    "优化差",
    "贵",
    "服务器",
    "外挂",
    "退款",
    "crash",
    "stutter",
    "expensive",
    "server",
    "cheat",
    "refund",
)


class ReviewService:
    async def fetch_reviews(
        self,
        steam: SteamClient,
        appid: int,
        language: str = "schinese",
        review_type: str = "all",
        count: int = 20,
    ) -> tuple[list[ReviewItem], str, object]:
        return await steam.get_reviews(
            appid=appid,
            language=language,
            review_type=review_type,
            count=count,
        )

    async def analyze_enhanced(
        self,
        steam: SteamClient,
        appid: int,
        count: int = 100,
        review_type: str = "all",
        language: str = "schinese",
        days: int = 0,
    ) -> SentimentAnalysisResult:
        """Enhanced review analysis with language stratification and statistical summary.

        Fetches reviews, applies filters (type, time window, language), and
        produces a detailed analysis with per-language breakdown when multiple
        languages are detected.
        """
        from datetime import UTC, datetime, timedelta

        fetch_count = count * 3 if (review_type != "all" or days > 0) else max(count, 100)
        fetch_count = min(fetch_count, 500)

        reviews, source_url, _ = await self.fetch_reviews(
            steam, appid=appid, language=language, count=fetch_count,
        )

        # Apply review_type filter
        if review_type == "positive":
            reviews = [r for r in reviews if r.voted_up]
        elif review_type == "negative":
            reviews = [r for r in reviews if not r.voted_up]

        # Apply time window filter
        if days > 0:
            cutoff = datetime.now(UTC) - timedelta(days=days)
            reviews = [r for r in reviews if r.timestamp_created >= cutoff]

        # Compute language stratification
        lang_distribution: dict[str, int] = {}
        for r in reviews:
            lang = r.language or "unknown"
            lang_distribution[lang] = lang_distribution.get(lang, 0) + 1

        # Cap and analyze
        reviews = reviews[:count]

        # Use LLM analysis with enhanced context
        result = await self.analyze_sentiment_llm(
            appid=appid, reviews=reviews, source_url=source_url,
        )

        # Add language stratification to summary
        if len(lang_distribution) > 1:
            lang_parts = [f"{lang}({cnt})" for lang, cnt in sorted(
                lang_distribution.items(), key=lambda x: x[1], reverse=True
            )[:5]]
            result.summary += f"\n\n语言分布：{', '.join(lang_parts)}。"

        # Add statistical note for small samples
        if len(reviews) < 30:
            result.summary += (
                f"\n\n⚠ 样本量仅 {len(reviews)} 条，统计意义有限。"
                f"建议增加样本量至 ≥100 以获得更稳定的结论。"
            )

        return result

    def analyze_sentiment(
        self,
        appid: int,
        reviews: list[ReviewItem],
        source_url: str | None,
    ) -> SentimentAnalysisResult:
        analyzed_at = utc_now()
        if not reviews:
            return SentimentAnalysisResult(
                appid=appid,
                total_reviews=0,
                positive_ratio=0,
                summary="Steam 评论接口没有返回可分析的评论样本。",
                source_url=source_url,
                analyzed_at=analyzed_at,
                reviews=[],
            )

        positive_count = sum(1 for review in reviews if review.voted_up)
        praise = self._keyword_counts(reviews, PRAISE_KEYWORDS, positive_only=True)
        complaints = self._keyword_counts(reviews, COMPLAINT_KEYWORDS, positive_only=False)
        positive_ratio = positive_count / len(reviews)
        summary = (
            f"本次抽样 {len(reviews)} 条最近评论，样本好评率约 {positive_ratio:.0%}。"
            f"正向反馈集中在 {self._join_keywords(praise)}；"
            f"负向反馈集中在 {self._join_keywords(complaints)}。"
        )
        return SentimentAnalysisResult(
            appid=appid,
            total_reviews=len(reviews),
            positive_ratio=positive_ratio,
            top_praise_keywords=praise,
            top_complaint_keywords=complaints,
            summary=summary,
            source_url=source_url,
            analyzed_at=analyzed_at,
            reviews=reviews,
        )

    def save_analysis(self, session: Session, result: SentimentAnalysisResult) -> ReviewAnalysis:
        analysis = ReviewAnalysis(
            appid=result.appid,
            total_reviews=result.total_reviews,
            positive_ratio=result.positive_ratio,
            top_praise_keywords_json=dump_json(result.top_praise_keywords),
            top_complaint_keywords_json=dump_json(result.top_complaint_keywords),
            summary=result.summary,
            source_url=result.source_url,
            analyzed_at=result.analyzed_at,
        )
        session.add(analysis)
        session.commit()
        session.refresh(analysis)
        return analysis

    def latest_analysis(self, session: Session, appid: int) -> SentimentAnalysisResult | None:
        analysis = session.exec(
            select(ReviewAnalysis)
            .where(ReviewAnalysis.appid == appid)
            .order_by(ReviewAnalysis.analyzed_at.desc())  # type: ignore[attr-defined]
        ).first()  # type: ignore[attr-defined]
        if analysis is None:
            return None
        return SentimentAnalysisResult(
            appid=analysis.appid,
            total_reviews=analysis.total_reviews,
            positive_ratio=analysis.positive_ratio or 0,
            top_praise_keywords=load_json(analysis.top_praise_keywords_json, []),
            top_complaint_keywords=load_json(analysis.top_complaint_keywords_json, []),
            summary=analysis.summary or "",
            source_url=analysis.source_url,
            analyzed_at=analysis.analyzed_at,
            reviews=[],
        )

    def _keyword_counts(
        self,
        reviews: list[ReviewItem],
        keywords: tuple[str, ...],
        positive_only: bool,
    ) -> list[str]:
        counter: Counter[str] = Counter()
        for review in reviews:
            if positive_only and not review.voted_up:
                continue
            if not positive_only and review.voted_up:
                continue
            text = review.review_text.lower()
            for keyword in keywords:
                if keyword.lower() in text:
                    counter[keyword] += 1
        return [keyword for keyword, _ in counter.most_common(5)]

    def _join_keywords(self, keywords: list[str]) -> str:
        return "、".join(keywords) if keywords else "样本中未形成稳定关键词"

    # ------------------------------------------------------------------
    # LLM-enhanced analysis (falls back to keyword rules when LLM unavailable)
    # ------------------------------------------------------------------

    async def analyze_sentiment_llm(
        self,
        appid: int,
        reviews: list[ReviewItem],
        source_url: str | None,
    ) -> SentimentAnalysisResult:
        """Analyze reviews using LLM for topic extraction and sentiment.

        When the LLM is unavailable this falls back to the keyword-based
        ``analyze_sentiment`` method transparently.
        """
        analyzed_at = utc_now()
        if not reviews:
            return SentimentAnalysisResult(
                appid=appid,
                total_reviews=0,
                positive_ratio=0,
                summary="没有可分析的评论。",
                source_url=source_url,
                analyzed_at=analyzed_at,
                reviews=[],
            )

        # Try LLM-based extraction
        try:
            from app.llm import create_chat_model

            llm = create_chat_model(temperature=0.2)
            if llm is not None:
                return await self._llm_analyze(appid, reviews, source_url, analyzed_at, llm)
        except Exception:
            logger.info("LLM review analysis failed — falling back to keyword rules")

        # Fallback to keyword-based analysis
        return self.analyze_sentiment(appid, reviews, source_url)

    async def _llm_analyze(
        self,
        appid: int,
        reviews: list[ReviewItem],
        source_url: str | None,
        analyzed_at,
        llm,
    ) -> SentimentAnalysisResult:
        positive_count = sum(1 for r in reviews if r.voted_up)
        positive_ratio = positive_count / len(reviews) if reviews else 0

        # Batch reviews into groups of 8 for LLM processing
        batch_size = 8
        all_topics: list[dict] = []

        for batch_start in range(0, min(len(reviews), 24), batch_size):
            batch = reviews[batch_start : batch_start + batch_size]
            reviews_text = "\n\n".join(
                f"[{i+1}] {'推荐' if r.voted_up else '不推荐'}: {r.review_text[:300]}"
                for i, r in enumerate(batch)
            )
            prompt = (
                "分析以下 Steam 游戏评论，提取关键话题和情感。\n"
                "输出 JSON 格式（不要 Markdown 代码块）：\n"
                '{"topics":[{"topic":"话题名","sentiment":"positive/negative/neutral",'
                '"mentions":出现次数,"quote":"一条代表性原文"}]}\n\n'
                + reviews_text
            )
            try:
                resp = await llm.ainvoke(prompt)
                text = str(getattr(resp, "content", resp))
                import json
                import re
                # Strip markdown code fences if present
                text = re.sub(r"```(?:json)?\s*", "", text).strip("` \n")
                parsed = json.loads(text)
                all_topics.extend(parsed.get("topics", []))
            except Exception:
                continue

        # Aggregate topics
        praise_keywords: list[str] = []
        complaint_keywords: list[str] = []
        topic_summaries: list[str] = []

        for topic in all_topics:
            name = topic.get("topic", "")
            sentiment = topic.get("sentiment", "neutral")
            mentions = topic.get("mentions", 1)
            if not name:
                continue
            if sentiment == "positive":
                praise_keywords.append(f"{name}(×{mentions})")
                topic_summaries.append(f"✅ {name}")
            elif sentiment == "negative":
                complaint_keywords.append(f"{name}(×{mentions})")
                topic_summaries.append(f"❌ {name}")
            else:
                topic_summaries.append(f"➖ {name}")

        if not praise_keywords:
            praise_keywords = [kw for kw, _ in Counter(
                r.review_text for r in reviews if r.voted_up
            ).most_common(3)]

        if not complaint_keywords:
            complaint_keywords = [kw for kw, _ in Counter(
                r.review_text for r in reviews if not r.voted_up
            ).most_common(3)]

        summary = (
            f"本次抽样 {len(reviews)} 条最近评论，样本好评率约 {positive_ratio:.0%}。\n"
            + ("\n".join(topic_summaries[:8]) if topic_summaries else "（LLM 未提取到明确话题）")
        )

        return SentimentAnalysisResult(
            appid=appid,
            total_reviews=len(reviews),
            positive_ratio=positive_ratio,
            top_praise_keywords=praise_keywords[:5],
            top_complaint_keywords=complaint_keywords[:5],
            summary=summary,
            source_url=source_url,
            analyzed_at=analyzed_at,
            reviews=reviews,
        )
