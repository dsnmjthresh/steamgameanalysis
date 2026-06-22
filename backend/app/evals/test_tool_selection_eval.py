"""Evaluate tool selection based on task type classification.

Usage: pytest backend/app/evals/test_tool_selection_eval.py -v -s
Writes results to backend/app/evals/results/tool_selection_eval.json

Target: ≥75% accuracy.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

import pytest

from app.agent.task_classifier import TaskClassifier


@dataclass
class _ToolEvalCase:
    query: str
    expected_task_type: str  # the true task type for this query
    expected_tools: list[str]  # tools expected for this task


# Simplified mapping: task_type -> expected tools
_TASK_TOOLS: dict[str, list[str]] = {
    "single_game": [
        "get_current_players", "get_appdetails", "get_game_news",
        "get_achievement_stats",
    ],
    "game_comparison": ["compare_snapshots", "get_appdetails"],
    "review_analysis": ["get_reviews", "analyze_reviews"],
    "web_sentiment": ["analyze_web_sentiment"],
    "history_trend": ["get_trend_analysis", "list_snapshots"],
    "market_intelligence": ["search_games"],
    "knowledge_qa": ["rag_search"],
    "export": [],
    "schedule_monitor": ["save_snapshot"],
    "unknown": [],
}

EVAL_CASES: list[_ToolEvalCase] = [
    # single_game queries
    _ToolEvalCase("CS2 现在有多少人在玩？", "single_game", _TASK_TOOLS["single_game"]),
    _ToolEvalCase("查询一下 730 的游戏详情", "single_game", _TASK_TOOLS["single_game"]),
    _ToolEvalCase("Dota 2 的新闻有什么？", "single_game", _TASK_TOOLS["single_game"]),
    _ToolEvalCase("Can you find me info about Baldur's Gate 3?", "single_game", _TASK_TOOLS["single_game"]),
    _ToolEvalCase("黑神话悟空打折了吗？", "single_game", _TASK_TOOLS["single_game"]),
    _ToolEvalCase("Show me details for appid 570", "single_game", _TASK_TOOLS["single_game"]),
    _ToolEvalCase("告诉我 Elden Ring 现在多少钱", "single_game", _TASK_TOOLS["single_game"]),

    # comparison
    _ToolEvalCase("对比一下 CS2 和 Dota 2", "game_comparison", _TASK_TOOLS["game_comparison"]),
    _ToolEvalCase("730 和 570 哪个更受欢迎？", "game_comparison", _TASK_TOOLS["game_comparison"]),
    _ToolEvalCase("Which is better, CS2 or Valorant?", "game_comparison", _TASK_TOOLS["game_comparison"]),
    _ToolEvalCase("黑神话悟空和只狼的价格比较", "game_comparison", _TASK_TOOLS["game_comparison"]),
    _ToolEvalCase("CS2 和 Valorant 在线人数对比", "game_comparison", _TASK_TOOLS["game_comparison"]),

    # review
    _ToolEvalCase("分析 CS2 的玩家评论", "review_analysis", _TASK_TOOLS["review_analysis"]),
    _ToolEvalCase("Analyze reviews for Elden Ring", "review_analysis", _TASK_TOOLS["review_analysis"]),
    _ToolEvalCase("帮我看看黑神话的差评都在说什么", "review_analysis", _TASK_TOOLS["review_analysis"]),
    _ToolEvalCase("What are people saying about Starfield?", "review_analysis", _TASK_TOOLS["review_analysis"]),
    _ToolEvalCase("Elden Ring 的口碑怎么样", "review_analysis", _TASK_TOOLS["review_analysis"]),

    # trend
    _ToolEvalCase("CS2 这个月在线趋势怎么样？", "history_trend", _TASK_TOOLS["history_trend"]),
    _ToolEvalCase("What's the player trend for CS2?", "history_trend", _TASK_TOOLS["history_trend"]),
    _ToolEvalCase("730 最近30天数据走势", "history_trend", _TASK_TOOLS["history_trend"]),
    _ToolEvalCase("Dota 2 的历史玩家数据", "history_trend", _TASK_TOOLS["history_trend"]),
    _ToolEvalCase("CS2 过去一个月的在线变化", "history_trend", _TASK_TOOLS["history_trend"]),

    # web sentiment
    _ToolEvalCase("搜索一下网上对 CS2 的评价", "web_sentiment", _TASK_TOOLS["web_sentiment"]),
    _ToolEvalCase("What is the web sentiment around Elden Ring?", "web_sentiment", _TASK_TOOLS["web_sentiment"]),
    _ToolEvalCase("社交媒体上对Starfield的讨论", "web_sentiment", _TASK_TOOLS["web_sentiment"]),
    _ToolEvalCase("Search web for CS2 community sentiment", "web_sentiment", _TASK_TOOLS["web_sentiment"]),
    _ToolEvalCase("社区对CS2更新的反应", "web_sentiment", _TASK_TOOLS["web_sentiment"]),

    # market intelligence
    _ToolEvalCase("分析一下当前PC游戏市场趋势", "market_intelligence", _TASK_TOOLS["market_intelligence"]),
    _ToolEvalCase("What are the top-selling games on Steam?", "market_intelligence", _TASK_TOOLS["market_intelligence"]),
    _ToolEvalCase("Steam 上最近哪些游戏最火？", "market_intelligence", _TASK_TOOLS["market_intelligence"]),
    _ToolEvalCase("现在流行什么类型的游戏", "market_intelligence", _TASK_TOOLS["market_intelligence"]),

    # knowledge
    _ToolEvalCase("CS2 的武器有哪些？", "knowledge_qa", _TASK_TOOLS["knowledge_qa"]),
    _ToolEvalCase("How does the ranking system work in CS2?", "knowledge_qa", _TASK_TOOLS["knowledge_qa"]),
    _ToolEvalCase("什么是VAC反作弊系统？", "knowledge_qa", _TASK_TOOLS["knowledge_qa"]),
    _ToolEvalCase("Elden Ring 攻略指南", "knowledge_qa", _TASK_TOOLS["knowledge_qa"]),

    # export
    _ToolEvalCase("导出 CS2 的数据报告", "export", _TASK_TOOLS["export"]),
    _ToolEvalCase("Export the analysis results for Dota 2", "export", _TASK_TOOLS["export"]),
    _ToolEvalCase("下载 CS2 的分析报告", "export", _TASK_TOOLS["export"]),

    # monitor
    _ToolEvalCase("帮我每天监控 730 的在线人数", "schedule_monitor", _TASK_TOOLS["schedule_monitor"]),
    _ToolEvalCase("Monitor CS2 player count every day", "schedule_monitor", _TASK_TOOLS["schedule_monitor"]),
    _ToolEvalCase("每小时检查一次 Dota 2 的在线", "schedule_monitor", _TASK_TOOLS["schedule_monitor"]),
]


@pytest.mark.anyio
async def test_tool_selection_accuracy():
    """Run tool-selection eval: classification accuracy determines tool match."""
    classifier = TaskClassifier()
    results: list[dict] = []
    correct = 0

    for i, case in enumerate(EVAL_CASES):
        classification = await classifier.classify(case.query, [])
        expected_task_type = case.expected_task_type
        expected_tools = case.expected_tools
        actual_tools = _TASK_TOOLS.get(classification.task_type, [])

        # Tool selection is correct if the classified task_type matches
        # the expected task_type and the tool sets align
        task_match = classification.task_type == expected_task_type
        overlap = set(expected_tools) & set(actual_tools) if expected_tools else (not actual_tools)
        tool_match = bool(overlap) or (not expected_tools and not actual_tools)

        if task_match and tool_match:
            correct += 1

        results.append({
            "index": i,
            "query": case.query,
            "expected_task_type": expected_task_type,
            "classified_task_type": classification.task_type,
            "expected_tools": expected_tools,
            "actual_tools": actual_tools,
            "task_type_match": task_match,
            "tool_match": tool_match,
            "correct": task_match and tool_match,
            "confidence": classification.confidence,
        })

    accuracy = correct / len(EVAL_CASES)
    report = {
        "accuracy": round(accuracy, 4),
        "total": len(EVAL_CASES),
        "correct": correct,
        "results": results,
    }

    out_dir = os.path.join(os.path.dirname(__file__), "results")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "tool_selection_eval.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    threshold = 0.75

    print(f"\nTool selection accuracy: {accuracy:.1%} ({correct}/{len(EVAL_CASES)})"
          f"  [threshold={threshold:.0%}]")

    # Print mismatches
    mismatches = [r for r in results if not r["correct"]]
    if mismatches:
        print(f"Mismatches ({len(mismatches)}):")
        for mm in mismatches[:10]:
            print(f"  [{mm['index']}] '{mm['query'][:60]}'"
                  f" → expected_task={mm['expected_task_type']},"
                  f" got={mm['classified_task_type']}")

    assert accuracy >= threshold, (
        f"Tool selection accuracy {accuracy:.1%} below {threshold:.0%} threshold."
    )
