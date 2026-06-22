from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from app.agent.prompts import TASK_CLASSIFIER_PROMPT
from app.core.config import Settings, get_settings
from app.llm import create_chat_model_sync

TaskType = Literal[
    "single_game",
    "game_comparison",
    "review_analysis",
    "web_sentiment",
    "market_intelligence",
    "knowledge_qa",
    "history_trend",
    "schedule_monitor",
    "export",
    "unknown",
]


TASK_TYPES: tuple[TaskType, ...] = (
    "single_game",
    "game_comparison",
    "review_analysis",
    "web_sentiment",
    "market_intelligence",
    "knowledge_qa",
    "history_trend",
    "schedule_monitor",
    "export",
    "unknown",
)


@dataclass(frozen=True)
class TaskClassification:
    task_type: TaskType
    reason: str
    confidence: float = 0.75
    source: Literal["llm", "heuristic", "hybrid"] = "heuristic"
    alternative_types: list[tuple[str, str]] = field(default_factory=list)  # (task_type, reason) pairs


class TaskClassifier:
    """LLM-first task classifier with a deterministic fallback."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._llm = self._build_llm()

    def _build_llm(self):
        return create_chat_model_sync(
            temperature=0.1,
            model=self.settings.deepseek_fallback_model,
        )

    async def classify(self, query: str, history: list[dict] | None = None) -> TaskClassification:
        heuristic = self._heuristic(query, history or [])
        if heuristic.confidence >= 0.88:
            return heuristic

        if self._llm is not None:
            try:
                expanded_query = self._expand_query(query, history or [], heuristic)
                prompt = TASK_CLASSIFIER_PROMPT.format(query=expanded_query)

                import time as time_mod

                from app.core.metrics import record_llm_call

                t0 = time_mod.perf_counter()
                llm_status = "success"
                try:
                    response = await self._llm.ainvoke(prompt)
                except Exception:
                    llm_status = "error"
                    raise
                finally:
                    model = self.settings.deepseek_fallback_model or "unknown"
                    record_llm_call(model, llm_status, int((time_mod.perf_counter() - t0) * 1000))

                text = str(getattr(response, "content", response)).strip()
                parsed = self._parse_llm_response(text, heuristic)
                if parsed is not None:
                    return parsed
            except Exception:
                pass
        return heuristic

    def _parse_llm_response(
        self,
        text: str,
        heuristic: TaskClassification | None = None,
    ) -> TaskClassification | None:
        normalized = text.strip().lower()
        for task_type in TASK_TYPES:
            if normalized.startswith(task_type) or re.search(rf"\b{task_type}\b", normalized):
                reason = text.split(":", 1)[-1].strip() if ":" in text else text
                if heuristic and heuristic.task_type == task_type:
                    return TaskClassification(
                        task_type=task_type,
                        reason=f"关键词路由与 LLM 路由一致：{reason[:130]}",
                        confidence=max(heuristic.confidence, 0.86),
                        source="hybrid",
                    )
                if heuristic and heuristic.confidence >= 0.72:
                    return TaskClassification(
                        task_type=task_type,
                        reason=(
                            f"关键词初判为 {heuristic.task_type}，LLM 仲裁改为 {task_type}："
                            f"{reason[:100]}"
                        ),
                        confidence=0.82,
                        source="hybrid",
                    )
                return TaskClassification(task_type=task_type, reason=reason[:160], source="llm")
        return None

    def _heuristic(self, query: str, history: list[dict]) -> TaskClassification:
        lowered = query.lower()

        # ── export ──
        if any(word in lowered for word in ("导出", "下载", "markdown报告", "json报告",
                                             "导出报告", "下载报告", "报告文件",
                                             "export report", "download report", "save report",
                                             "export the analysis", "一份.*报告")):
            return TaskClassification("export", "命中导出/下载报告表达。", confidence=0.90)
        # "给我一份...报告" pattern
        if re.search(r'(给我|出一份).*报告', lowered):
            return TaskClassification("export", "命中导出/下载报告表达。", confidence=0.89)
        # "Export ... results for ..."
        if re.search(r'export.*result', lowered):
            return TaskClassification("export", "命中导出结果表达。", confidence=0.89)

        # ── schedule_monitor ──
        if any(word in lowered for word in ("监控", "定时", "每隔", "提醒", "告警", "每天", "每小时",
                                             "monitor", "schedule", "alert me", "every day",
                                             "notify me")):
            return TaskClassification("schedule_monitor", "命中定时监控/提醒表达。", confidence=0.89)

        # ── web_sentiment ──
        if any(word in lowered for word in (
            "舆情", "全网", "网页", "社区", "论坛", "玩家不满", "骂", "炎上", "节奏",
            "更新后", "版本更新后", "公告后", "口碑崩", "社交媒体", "网上", "搜索一下",
            "public opinion", "community sentiment", "backlash", "web sentiment",
            "search web", "search the web", "social media", "sentiment around",
        )):
            return TaskClassification("web_sentiment", "命中网页舆情/社区反馈分析表达。", confidence=0.87)

        # ── review_analysis (check BEFORE history_trend to avoid "最近评价" misclassification) ──
        if any(word in lowered for word in ("评论", "好评", "差评", "review", "reviews",
                                             "玩家反馈", "用户评价", "抱怨", "吐槽",
                                             "analyze reviews", "差评都在说什么",
                                             "差评", "最新更新.*评价", "玩家.*评价")):
            return TaskClassification("review_analysis", "命中评论/评价分析表达。", confidence=0.85)
        if re.search(r'people\s+(are\s+)?saying|what\s+are\s+people', lowered):
            return TaskClassification("review_analysis", "命中「people saying」评论分析表达。", confidence=0.83)
        # "评价" and "口碑" when asking about quality/opinion
        if any(word in lowered for word in ("评价怎么样", "评价如何", "口碑怎么样", "口碑如何",
                                             "风评怎么样", "评分怎么样",
                                             "的评价", "的口碑", "最近评价",
                                             "对.*的评价", "对.*口碑")):
            return TaskClassification("review_analysis", "命中评价/口碑分析表达。", confidence=0.83)

        # ── game_comparison ──
        if re.search(r"\b(vs|v\.s\.|versus)\b", lowered):
            return TaskClassification("game_comparison", "命中 vs/versus 对比表达。", confidence=0.88)
        if any(word in lowered for word in ("对比", "比较", "比一下", "哪个更好", "哪个更",
                                             "compare", "comparison", "better than",
                                             "which is better", "比较一下",
                                             "对比一下", "比一比")):
            return TaskClassification("game_comparison", "命中游戏对比表达。", confidence=0.86)
        # "X 和 Y 哪个更Z" pattern
        if re.search(r'和\s*.+\s*哪个更', lowered):
            return TaskClassification("game_comparison", "命中「和...哪个更」对比表达。", confidence=0.84)

        # ── market_intelligence (BEFORE history_trend to capture "市场趋势") ──
        if any(word in lowered for word in ("市场", "热门", "推荐", "值得买", "值得关注", "发售",
                                             "流行", "最火", "热玩", "喜欢玩", "什么类型",
                                             "哪类", "玩家偏好", "大家都在玩", "现在流行",
                                             "排行榜", "top", "best selling", "top-selling",
                                             "most popular", "trending", "新品",
                                             "射击游戏市场", "rpg游戏", "什么游戏",
                                             "market analysis", "market trend",
                                             "哪些游戏", "什么游戏最", "市场趋势",
                                             "市场分析")):
            return TaskClassification("market_intelligence", "命中市场洞察/推荐表达。", confidence=0.82)

        # ── history_trend ──
        if any(word in lowered for word in ("历史玩家", "历史快照", "数据走势",
                                             "trend analysis", "player trend", "price trend")):
            return TaskClassification("history_trend", "命中明确历史趋势表达。", confidence=0.84)
        if any(word in lowered for word in ("走势", "曲线", "过去", "下降", "上升",
                                             "history", "historical", "over the last",
                                             "over the past", "最近30天", "最近7天",
                                             "趋势", "变化")):
            return TaskClassification("history_trend", "命中历史趋势/变化表达。", confidence=0.84)
        if re.search(r'最近\d*天|最近\d*周|最近\d*月|这个月|过去\d', lowered):
            return TaskClassification("history_trend", "命中时间窗口趋势表达。", confidence=0.82)
        # "最近" with game name = trend
        if "最近" in lowered:
            has_game_name = bool(re.search(
                r'(?:cs2|dota|elden|starfield|baldur|'
                r'黑神话|悟空|只狼|艾尔登|pubg|apex|'
                r'valorant|\d{3,8})', lowered,
            ))
            if has_game_name:
                return TaskClassification("history_trend", "命中「最近+游戏名」趋势表达。", confidence=0.72)

        # ── knowledge_qa ──
        if any(word in lowered for word in ("知识库", "资料库", "根据资料", "检索", "rag",
                                             "怎么玩", "攻略", "指南",
                                             "how does", "how to", "guide",
                                             "武器", "英雄", "装备",
                                             "地图", "模式", "反作弊", "vac",
                                             "ranking system", "workshop", "创意工坊",
                                             "系统", "机制")):
            return TaskClassification("knowledge_qa", "命中知识库/攻略/RAG 检索表达。", confidence=0.83)

        # ── contextual single_game ──
        if history and any(word in lowered for word in ("它", "这个", "该游戏", "刚才")):
            return TaskClassification("single_game", "根据上下文继续分析上一个游戏。", confidence=0.68)

        # ── single_game (default attempt — look for game-name-like patterns) ──
        # Check if query is asking for player count, price, news, etc.
        has_game_data_keyword = any(word in lowered for word in (
            "多少人", "在线", "玩家", "价格", "多少钱", "打折", "免费",
            "新闻", "公告", "成就", "详情", "数据", "信息", "appid",
            "how many players", "player count", "price", "discount",
            "news", "achievement", "details", "info", "find me",
            "show me", "look up", "告诉我", "帮我查", "看看", "查询",
            "搜索", "打折了吗", "最新", "评价怎么样", "成就统计",
        ))
        has_game_name_hint = bool(re.search(
            r'(?:cs[:\s]?go|cs2|dota\s*2|elden\s*ring|starfield|baldur.*gate|'
            r'黑神话|悟空|只狼|艾尔登|法环|pubg|apex|valorant|原神|崩坏|'
            r'\d{3,8})',
            lowered,
        ))
        if has_game_data_keyword or has_game_name_hint:
            return TaskClassification("single_game", "按单游戏公开数据查询处理。", confidence=0.72)

        return TaskClassification("single_game", "默认按单游戏公开数据查询处理。", confidence=0.55)

    def _expand_query(
        self,
        query: str,
        history: list[dict],
        heuristic: TaskClassification,
    ) -> str:
        recent_context = ""
        if history:
            recent_items = []
            for item in history[-4:]:
                role = item.get("role")
                content = str(item.get("content") or "").strip()
                if role in {"user", "assistant"} and content:
                    recent_items.append(f"{role}: {content[:160]}")
            recent_context = "\n".join(recent_items)
        return (
            f"{query}\n\n"
            f"关键词初判：{heuristic.task_type}，理由：{heuristic.reason}，置信度：{heuristic.confidence:.2f}。\n"
            f"最近上下文：\n{recent_context or '无'}"
        )
