"""Evaluate RAG Recall@3 and MRR on 20 queries.

Usage: pytest backend/app/evals/test_rag_eval.py -v -s
Writes results to backend/app/evals/results/rag_eval.json

Target: Recall@3 ≥ 60%, MRR ≥ 50%.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from sqlmodel import Session

from app.schemas.knowledge import KnowledgeSearchRequest
from app.services.knowledge_service import search_knowledge


@dataclass
class _RagEvalCase:
    query: str
    expected_appids: list[int]  # expected relevant appids (empty = skip scoring)


EVAL_CASES: list[_RagEvalCase] = [
    _RagEvalCase("CS2 的武器系统", [730]),
    _RagEvalCase("Dota 2 英雄介绍", [570]),
    _RagEvalCase("黑神话悟空战斗系统怎么样", [2358720]),
    _RagEvalCase("Elden Ring boss guide", [1245620]),
    _RagEvalCase("CS2 ranking and matchmaking", [730]),
    _RagEvalCase("Dota 2 patch notes latest", [570]),
    _RagEvalCase("黑神话悟空配置要求", [2358720]),
    _RagEvalCase("Steam Deck compatibility", []),
    _RagEvalCase("CS2 创意工坊地图", [730]),
    _RagEvalCase("FPS 游戏推荐", []),
    _RagEvalCase("Dota 2 新手入门指南", [570]),
    _RagEvalCase("Black Myth Wukong review", [2358720]),
    _RagEvalCase("CS2 smokes and grenades", [730]),
    _RagEvalCase("Elden Ring DLC", [1245620]),
    _RagEvalCase("多人联机游戏推荐", []),
    _RagEvalCase("CS2 更新日志", [730]),
    _RagEvalCase("Dota 2 tournament meta", [570]),
    _RagEvalCase("游戏引擎技术分析", []),
    _RagEvalCase("CS2 pro settings config", [730]),
    _RagEvalCase("黑神话悟空剧情解析", [2358720]),
]


# ---------------------------------------------------------------------------
# Seed knowledge using the real knowledge service ingest path
# ---------------------------------------------------------------------------


def _seed_eval_documents(session: Session) -> None:
    """Seed test knowledge documents via the real knowledge service pipeline.

    Uses ``KnowledgeDocumentCreate`` → ``ingest_document`` so FTS and vec0
    indexes are populated the same way as in production.
    """
    from app.schemas.knowledge import KnowledgeDocumentCreate
    from app.services.knowledge_service import create_document

    docs = [
        # ── CS2 (appid 730) ──────────────────────────────────────────
        (
            "CS2 武器系统详解",
            "CS2 中每种武器的伤害、后坐力和使用技巧，包括AK-47、M4A1、AWP等常用武器的详细分析",
            730,
        ),
        (
            "CS2 竞技排名与匹配机制",
            "CS2 的排名系统基于 Glicko-2 算法，匹配系统综合考虑玩家技能等级、地图偏好和网络延迟进行对战分配。"
            "Premier模式采用数值化Rating显示，从1000到30000+分不等",
            730,
        ),
        (
            "CS2 ranking and matchmaking guide",
            "CS2 uses a modified Glicko-2 ranking system. Your Premier Rating is calculated based on match "
            "performance against opponents of similar skill. Win streaks boost your rating faster",
            730,
        ),
        ("CS2 更新日志 v2.1", "最新更新包含 Dust2 地图调整、烟雾弹物理效果改进和网络延迟优化", 730),
        (
            "CS2 创意工坊地图安装教程",
            "如何在CS2中安装和游玩创意工坊地图，包括订阅、下载和加载自定义地图的完整步骤",
            730,
        ),
        (
            "CS2 烟雾弹与投掷物使用技巧",
            "CS2中各种烟雾弹投掷位置和时机分析，包括dust2、mirage等地图的关键烟雾点",
            730,
        ),
        (
            "CS2 职业选手配置与设置",
            "CS2职业选手常用的游戏设置：分辨率1280x960拉伸、鼠标灵敏度eDPI 800-1200、准星样式、"
            "视频设置优化以获得最大帧率。s1mple、ZywOo等顶级选手的完整config参数",
            730,
        ),
        (
            "CS2 pro player settings and config",
            "Professional CS2 players optimize their game with custom configs: stretched resolution 1280x960, "
            "eDPI between 800-1200, specific crosshair codes, and video settings for maximum FPS performance",
            730,
        ),
        (
            "CS2 pro settings config optimization",
            "Complete CS2 pro settings config guide: autoexec.cfg setup, rate commands, viewmodel settings, "
            "bob reduction, radar scale, and launch options for competitive play",
            730,
        ),

        # ── Dota 2 (appid 570) ─────────────────────────────────────
        (
            "Dota 2 英雄全解析",
            "Dota 2 拥有 124 个英雄，分为力量、敏捷、智力三类，每个英雄都有独特的技能组合",
            570,
        ),
        (
            "Dota 2 最新版本更新补丁说明",
            "Dota 2 patch notes 7.35d 对 Roshan 机制进行了重大改动，新增Roshan旗帜掉落和刷新时间从8-11分钟"
            "调整为固定8分钟。同时对多个英雄进行了平衡性调整",
            570,
        ),
        (
            "Dota 2 latest patch notes and updates",
            "The latest Dota 2 patch 7.35d introduces major Roshan mechanic changes, hero balance adjustments, "
            "and new item builds. Roshan now drops a banner on death and respawn timer is fixed at 8 minutes",
            570,
        ),
        (
            "Dota 2 新手入门指南",
            "Dota 2新手指南：从基础操作到英雄选择，帮助新玩家快速上手这款复杂的MOBA游戏",
            570,
        ),
        (
            "Dota 2 职业比赛环境与元分析",
            "当前Dota 2 tournament meta中，位置1核心以Ursa和Slark为主，中路以Puck和Ember Spirit流行，"
            "3号位偏向Beastmaster和Doom。职业比赛中团战节奏加快，平均比赛时长32分钟",
            570,
        ),
        (
            "Dota 2 competitive tournament meta analysis",
            "In the current Dota 2 pro tournament meta, position 1 favors Ursa and Slark, mid lane dominated by "
            "Puck and Ember Spirit. The meta emphasizes early fighting with average game time of 32 minutes",
            570,
        ),

        # ── 黑神话悟空 (appid 2358720) ─────────────────────────────
        (
            "黑神话悟空战斗系统分析",
            "黑神话悟空的战斗系统融合了魂系与动作游戏的元素，包括轻攻击、重攻击和变身机制",
            2358720,
        ),
        (
            "黑神话悟空剧情深度解读",
            "西游记背景下，天命人的故事从花果山开始，玩家将探索一个充满神魔的东方奇幻世界",
            2358720,
        ),
        (
            "黑神话悟空配置要求与优化",
            "黑神话悟空的最低和推荐配置要求，以及如何在各种硬件上进行性能优化的详细指南",
            2358720,
        ),

        # ── Elden Ring (appid 1245620) ─────────────────────────────
        (
            "Elden Ring Boss 全攻略指南",
            "从 Margit the Fell Omen 到 Malenia, Blade of Miquella，每个Boss的攻击模式、弱点分析、"
            "推荐等级和打法策略。包含主线Boss 15个和可选Boss 80+个的完整攻略",
            1245620,
        ),
        (
            "Elden Ring boss fight guide and strategies",
            "Complete Elden Ring boss guide covering all main bosses from Margit to Malenia. Each boss entry "
            "includes attack patterns, recommended level, weakness elements, and optimal strategies for melee "
            "and ranged builds",
            1245620,
        ),
        (
            "Elden Ring DLC 黄金树之影内容详解",
            "Elden Ring Shadow of the Erdtree DLC 新增了超过70种新武器、10个以上主线Boss和广袤的暗影之地地图。"
            "DLC故事围绕米凯拉展开，玩家将面对穿刺者梅瑟莫等新敌人",
            1245620,
        ),
        (
            "Elden Ring Shadow of the Erdtree DLC guide",
            "The Elden Ring DLC Shadow of the Erdtree introduces a massive new area called the Realm of Shadow, "
            "featuring over 70 new weapons, 10+ major bosses, and story centered around Miquella the Kind",
            1245620,
        ),
    ]

    for title, content, appid in docs:
        try:
            request = KnowledgeDocumentCreate(
                title=title,
                content=content,
                appid=appid,
                source_type="note",
            )
            create_document(session, request)
        except Exception:
            # Document may already exist or other ingest issue — skip
            pass


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def test_rag_recall_at_3(session_with_knowledge: Session):
    """Evaluate RAG Recall@3 and MRR using the real search_knowledge pipeline."""
    _seed_eval_documents(session_with_knowledge)

    results: list[dict] = []
    total_recall = 0.0
    total_mrr = 0.0
    valid_cases = 0

    for i, case in enumerate(EVAL_CASES):
        response = search_knowledge(
            session_with_knowledge,
            KnowledgeSearchRequest(query=case.query, limit=3),
        )

        # Extract appids from top-3 results (deduplicated by document)
        retrieved_appids: list[int] = []
        seen_docs: set[int] = set()
        for hit in response.hits[:3]:
            if hit.appid is not None and hit.document_id not in seen_docs:
                retrieved_appids.append(hit.appid)
                seen_docs.add(hit.document_id)

        expected = case.expected_appids
        if not expected:
            results.append({
                "index": i,
                "query": case.query,
                "expected_appids": expected,
                "retrieved_appids": retrieved_appids,
                "recall_at_3": None,
                "mrr": None,
            })
            continue

        # Recall@3: fraction of expected appids found in top 3
        found = sum(1 for e in expected if e in retrieved_appids)
        recall = found / len(expected)
        total_recall += recall

        # MRR: 1 / rank of first relevant match
        mrr = 0.0
        for rank, appid in enumerate(retrieved_appids, start=1):
            if appid in expected:
                mrr = 1.0 / rank
                break
        total_mrr += mrr
        valid_cases += 1

        results.append({
            "index": i,
            "query": case.query,
            "expected_appids": expected,
            "retrieved_appids": retrieved_appids,
            "recall_at_3": round(recall, 4),
            "mrr": round(mrr, 4),
        })

    avg_recall = total_recall / valid_cases if valid_cases else 0
    avg_mrr = total_mrr / valid_cases if valid_cases else 0

    report = {
        "recall_at_3": round(avg_recall, 4),
        "mrr": round(avg_mrr, 4),
        "total_cases": len(EVAL_CASES),
        "valid_cases": valid_cases,
        "results": results,
    }

    out_dir = os.path.join(os.path.dirname(__file__), "results")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "rag_eval.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\nRAG Recall@3: {avg_recall:.2%}  MRR: {avg_mrr:.2%}")
    print(f"Valid cases: {valid_cases}/{len(EVAL_CASES)}")

    # Print per-case details for debugging
    for r in results:
        if r["recall_at_3"] is not None and r["recall_at_3"] < 1.0:
            print(f"  Low recall [{r['index']}]: '{r['query'][:50]}'"
                  f" expected={r['expected_appids']} got={r['retrieved_appids']}"
                  f" recall={r['recall_at_3']:.0%}")

    # Hard thresholds — the eval must gate
    assert avg_recall >= 0.60, (
        f"RAG Recall@3 {avg_recall:.2%} below 60% threshold. "
        f"Seed data or retrieval logic needs improvement. See {out_path}"
    )
    assert avg_mrr >= 0.50, (
        f"RAG MRR {avg_mrr:.2%} below 50% threshold. "
        f"See {out_path}"
    )
