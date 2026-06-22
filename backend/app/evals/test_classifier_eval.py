"""Evaluate TaskClassifier accuracy on 50+ CN/EN queries.

Usage: pytest backend/app/evals/test_classifier_eval.py -v -s
Writes results to backend/app/evals/results/classifier_eval.json

Target: ≥80% accuracy heuristic-only, ≥85% with LLM.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

import pytest


@dataclass
class _EvalCase:
    query: str
    expected: str  # expected task_type


# ---------------------------------------------------------------------------
# 50+ mixed CN/EN queries covering all major task types
# ---------------------------------------------------------------------------

EVAL_CASES: list[_EvalCase] = [
    # ---- single_game ----
    _EvalCase("CS2 现在有多少人在玩？", "single_game"),
    _EvalCase("How many players does CS2 have right now?", "single_game"),
    _EvalCase("查询一下 730 的游戏详情", "single_game"),
    _EvalCase("730 这个游戏的评价怎么样？", "single_game"),
    _EvalCase("What is the price of Elden Ring?", "single_game"),
    _EvalCase("Dota 2 的新闻有什么？", "single_game"),
    _EvalCase("帮我看看 Starfield 的成就统计", "single_game"),
    _EvalCase("Show me details for appid 570", "single_game"),
    _EvalCase("搜索黑神话", "single_game"),
    _EvalCase("有没有类似 CS2 的游戏？", "single_game"),
    _EvalCase("Can you find me info about Baldur's Gate 3?", "single_game"),
    _EvalCase("黑神话悟空打折了吗？", "single_game"),
    _EvalCase("CS2 的数据信息", "single_game"),
    _EvalCase("告诉我 Elden Ring 现在多少钱", "single_game"),
    _EvalCase("看看 PUBG 的在线人数", "single_game"),

    # ---- game_comparison ----
    _EvalCase("对比一下 CS2 和 Dota 2", "game_comparison"),
    _EvalCase("Compare CS2 and Dota 2", "game_comparison"),
    _EvalCase("730 和 570 哪个更受欢迎？", "game_comparison"),
    _EvalCase("对比 Elden Ring 和 Dark Souls 3", "game_comparison"),
    _EvalCase("CS2 和 Valorant 在线人数对比", "game_comparison"),
    _EvalCase("帮我比较这几个游戏：730、570、440", "game_comparison"),
    _EvalCase("Which is better, CS2 or Valorant?", "game_comparison"),
    _EvalCase("黑神话悟空和只狼的价格比较", "game_comparison"),

    # ---- review_analysis ----
    _EvalCase("分析 CS2 的玩家评论", "review_analysis"),
    _EvalCase("Analyze reviews for Elden Ring", "review_analysis"),
    _EvalCase("730 最近评价如何？", "review_analysis"),
    _EvalCase("帮我看看黑神话的差评都在说什么", "review_analysis"),
    _EvalCase("What are people saying about Starfield?", "review_analysis"),
    _EvalCase("玩家对 Dota 2 最新更新的评价", "review_analysis"),
    _EvalCase("Elden Ring 的口碑怎么样", "review_analysis"),
    _EvalCase("分析一下 CS2 的好评和差评", "review_analysis"),

    # ---- history_trend ----
    _EvalCase("CS2 这个月在线趋势怎么样？", "history_trend"),
    _EvalCase("What's the player trend for CS2 over the last week?", "history_trend"),
    _EvalCase("730 最近30天数据走势", "history_trend"),
    _EvalCase("看看黑神话悟空最近的价格变化曲线", "history_trend"),
    _EvalCase("Dota 2 的历史玩家数据", "history_trend"),
    _EvalCase("Show me the trend for appid 730", "history_trend"),
    _EvalCase("CS2 过去一个月的在线变化", "history_trend"),
    _EvalCase("CS2 玩家在线人数是上升还是下降", "history_trend"),

    # ---- web_sentiment ----
    _EvalCase("搜索一下网上对 CS2 的评价", "web_sentiment"),
    _EvalCase("What is the web sentiment around Elden Ring?", "web_sentiment"),
    _EvalCase("搜索关于黑神话悟空的新闻报道", "web_sentiment"),
    _EvalCase("社交媒体上对Starfield的讨论", "web_sentiment"),
    _EvalCase("Search web for CS2 community sentiment", "web_sentiment"),
    _EvalCase("网上怎么看Dota 2新版本？", "web_sentiment"),
    _EvalCase("社区对CS2更新的反应", "web_sentiment"),
    _EvalCase("论坛上玩家对黑神话的评价", "web_sentiment"),

    # ---- market_intelligence ----
    _EvalCase("分析一下当前PC游戏市场趋势", "market_intelligence"),
    _EvalCase("What are the top-selling games on Steam right now?", "market_intelligence"),
    _EvalCase("Steam 上最近哪些游戏最火？", "market_intelligence"),
    _EvalCase("2025年射击游戏市场分析", "market_intelligence"),
    _EvalCase("现在流行什么类型的游戏", "market_intelligence"),
    _EvalCase("Most popular Steam games this month", "market_intelligence"),

    # ---- knowledge_qa ----
    _EvalCase("CS2 的武器有哪些？", "knowledge_qa"),
    _EvalCase("How does the ranking system work in CS2?", "knowledge_qa"),
    _EvalCase("什么是VAC反作弊系统？", "knowledge_qa"),
    _EvalCase("如何安装CS2创意工坊地图？", "knowledge_qa"),
    _EvalCase("Dota 2 的英雄怎么玩", "knowledge_qa"),
    _EvalCase("Elden Ring 攻略指南", "knowledge_qa"),

    # ---- export ----
    _EvalCase("导出 CS2 的数据报告", "export"),
    _EvalCase("给我一份 730 的快照分析报告", "export"),
    _EvalCase("Export the analysis results for Dota 2", "export"),
    _EvalCase("下载 CS2 的分析报告", "export"),

    # ---- schedule_monitor ----
    _EvalCase("帮我每天监控 730 的在线人数", "schedule_monitor"),
    _EvalCase("设置一个黑神话的价格变化提醒", "schedule_monitor"),
    _EvalCase("Monitor CS2 player count every day", "schedule_monitor"),
    _EvalCase("每小时检查一次 Dota 2 的在线", "schedule_monitor"),
]


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_classifier_accuracy():
    """Run classifier eval and assert accuracy >= 80%."""
    from app.agent.task_classifier import TaskClassifier

    classifier = TaskClassifier()
    results: list[dict] = []
    correct = 0

    for i, case in enumerate(EVAL_CASES):
        classification = await classifier.classify(case.query, [])
        match = classification.task_type == case.expected
        if match:
            correct += 1
        results.append({
            "index": i,
            "query": case.query,
            "expected": case.expected,
            "actual": classification.task_type,
            "match": match,
            "confidence": classification.confidence,
            "reason": getattr(classification, "reason", ""),
        })

    accuracy = correct / len(EVAL_CASES)
    report = {
        "accuracy": round(accuracy, 4),
        "total": len(EVAL_CASES),
        "correct": correct,
        "results": results,
    }

    # Write report
    out_dir = os.path.join(os.path.dirname(__file__), "results")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "classifier_eval.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # Per-class accuracy breakdown
    per_class: dict[str, dict] = {}
    for r in results:
        exp = r["expected"]
        if exp not in per_class:
            per_class[exp] = {"total": 0, "correct": 0}
        per_class[exp]["total"] += 1
        if r["match"]:
            per_class[exp]["correct"] += 1

    print(f"\nClassifier accuracy: {accuracy:.1%} ({correct}/{len(EVAL_CASES)})")
    print("Per-class accuracy:")
    for cls_name, counts in sorted(per_class.items()):
        cls_acc = counts["correct"] / counts["total"] if counts["total"] else 0
        print(f"  {cls_name}: {cls_acc:.0%} ({counts['correct']}/{counts['total']})")

    # Print mismatches for debugging
    mismatches = [r for r in results if not r["match"]]
    if mismatches:
        print(f"\nMismatches ({len(mismatches)}):")
        for mm in mismatches[:10]:
            print(f"  [{mm['index']}] '{mm['query'][:60]}' → expected={mm['expected']}, got={mm['actual']}")

    # Target: 80% minimum (heuristic should achieve this)
    threshold = 0.80
    assert accuracy >= threshold, (
        f"Classifier accuracy {accuracy:.1%} below {threshold:.0%} threshold. "
        f"Mismatches: {len(mismatches)}. See {out_path} for details."
    )
