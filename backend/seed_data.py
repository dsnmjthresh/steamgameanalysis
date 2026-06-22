"""
Comprehensive seed script for SteamAnalysis testing.
ALL 110 games verified against real Steam API (correct appid→name).
Generates 15 days of hourly snapshot data with realistic patterns.

Usage:
    cd backend
    python seed_data.py              # seed 15 days, 110 games
    python seed_data.py --clear      # clear DB first
    python seed_data.py --games 50 --days 7  # smaller dataset
"""

import argparse
import hashlib
import json
import math
import os
import random
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlmodel import Session, select
from sqlmodel import SQLModel

from app.core.config import get_settings
from app.db.models import (
    AnalysisReport, AppSetting, Conversation, Game, GameAlias,
    GameSnapshot, KnowledgeChunk, KnowledgeDocument, Message,
    MonitorAlert, MonitorTask, ReviewAnalysis, SentimentEvent,
    SnapshotLabel, SourceClaim, ToolCall, WebSource, utc_now,
)
from app.db.session import engine
from app.services.game_alias_service import seed_default_aliases
from app.services.knowledge_service import init_knowledge_indexes

# ---------------------------------------------------------------------------
# Load verified games from JSON
# ---------------------------------------------------------------------------

def load_verified_games() -> list[dict[str, Any]]:
    json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'verified_games_complete.json')
    if os.path.exists(json_path):
        with open(json_path, 'r', encoding='utf-8') as f:
            games = json.load(f)
        print(f"Loaded {len(games)} verified games from {json_path}")
        return games
    # Fallback: minimal verified list
    print("WARNING: verified_games_complete.json not found, using fallback list")
    return [
        {"appid": 730, "name": "Counter-Strike 2", "type": "game", "base_players": 800000, "peak_mult": 1.4, "price": 0, "currency": "CNY", "is_free": True, "recommendations": 8500000, "genres": ["Action"], "developers": ["Valve"], "publishers": ["Valve"]},
        {"appid": 570, "name": "Dota 2", "type": "game", "base_players": 450000, "peak_mult": 1.3, "price": 0, "currency": "CNY", "is_free": True, "recommendations": 2200000, "genres": ["Action"], "developers": ["Valve"], "publishers": ["Valve"]},
        {"appid": 1245620, "name": "ELDEN RING", "type": "game", "base_players": 35000, "peak_mult": 1.6, "price": 29800, "currency": "CNY", "is_free": False, "recommendations": 900000, "genres": ["Action"], "developers": ["FromSoftware"], "publishers": ["Bandai Namco"]},
    ]

REAL_GAMES = load_verified_games()

# ---------------------------------------------------------------------------
# Player count generation — realistic daily cycles
# ---------------------------------------------------------------------------

def player_count_at_time(base: int, peak_mult: float, dt: datetime, noise: float = 0.08) -> int:
    hour = dt.hour
    weekday = dt.weekday()
    peak_hour = 20.0
    hour_angle = ((hour - peak_hour) / 24.0) * 2 * math.pi
    daily_mult = 0.5 + 0.5 * (peak_mult - 0.5) * (1 + math.cos(hour_angle)) / 2
    if weekday >= 5:  # Weekend
        daily_mult *= 1.2
    elif weekday == 4 and hour >= 17:  # Friday evening
        daily_mult *= 1.1
    noise_factor = 1.0 + random.uniform(-noise, noise)
    return max(0, int(base * daily_mult * noise_factor))


def generate_snapshot_data(game: dict, dt: datetime) -> dict[str, Any]:
    pcount = player_count_at_time(game["base_players"], game["peak_mult"], dt)
    is_free = game["is_free"]
    price = game["price"]
    currency = game["currency"]

    discount = 0
    final_price = price
    if not is_free and dt.weekday() >= 5 and random.random() < 0.12:
        discount = random.choice([10, 20, 25, 33, 50, 67, 75])
        final_price = int(price * (100 - discount) / 100)
    elif not is_free and random.random() < 0.02:
        discount = random.choice([15, 25, 30, 40, 50])
        final_price = int(price * (100 - discount) / 100)

    base_recs = game["recommendations"]
    recs = base_recs + int(random.gauss(0, 10)) if base_recs > 0 else 0

    name = game["name"]
    appid = game["appid"]

    return {
        "player_count": pcount,
        "is_free": is_free,
        "currency": currency,
        "initial_price": price,
        "final_price": final_price,
        "discount_percent": discount,
        "recommendations_total": max(0, recs),
        "cc": "CN",
        "language": "schinese",
        "source": "steam_public",
        "raw_store_json": json.dumps({
            str(appid): {"success": True, "data": {
                "name": name, "type": game["type"], "is_free": is_free,
                "price_overview": None if is_free else {"currency": currency, "initial": price, "final": final_price, "discount_percent": discount},
                "recommendations": {"total": max(0, recs)},
                "genres": [{"description": g} for g in game.get("genres", [])],
                "developers": game.get("developers", []),
                "publishers": game.get("publishers", []),
            }}
        }),
        "raw_players_json": json.dumps({"response": {"player_count": pcount, "result": 1}}),
        "raw_news_json": json.dumps([{
            "title": f"{name} Update #{dt.strftime('%m%d')}",
            "url": f"https://store.steampowered.com/news/app/{appid}",
            "published_at": (dt - timedelta(hours=random.randint(1, 48))).isoformat(),
            "summary": f"Latest update for {name}",
        }]),
        "source_urls_json": json.dumps({
            "store_appdetails": f"https://store.steampowered.com/api/appdetails?appids={appid}",
            "current_players": f"https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/?appid={appid}",
            "news": f"https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/?appid={appid}",
        }),
    }


# ---------------------------------------------------------------------------
# Chinese game aliases (matched to verified game names)
# ---------------------------------------------------------------------------

EXTRA_ALIASES: list[dict[str, Any]] = [
    # Maps alias → verified canonical name
    {"appid": 730, "canonical_name": "Counter-Strike 2", "alias": "CS2", "locale": "zh-CN", "confidence": 1.0},
    {"appid": 730, "canonical_name": "Counter-Strike 2", "alias": "CSGO", "locale": "zh-CN", "confidence": 0.95},
    {"appid": 570, "canonical_name": "Dota 2", "alias": "刀塔2", "locale": "zh-CN", "confidence": 1.0},
    {"appid": 570, "canonical_name": "Dota 2", "alias": "DOTA2", "locale": "zh-CN", "confidence": 1.0},
    {"appid": 1245620, "canonical_name": "ELDEN RING", "alias": "艾尔登法环", "locale": "zh-CN", "confidence": 1.0},
    {"appid": 1245620, "canonical_name": "ELDEN RING", "alias": "老头环", "locale": "zh-CN", "confidence": 0.95},
    {"appid": 1245620, "canonical_name": "ELDEN RING", "alias": "法环", "locale": "zh-CN", "confidence": 0.9},
    {"appid": 2358720, "canonical_name": "Black Myth: Wukong", "alias": "黑神话悟空", "locale": "zh-CN", "confidence": 1.0},
    {"appid": 2358720, "canonical_name": "Black Myth: Wukong", "alias": "黑神话", "locale": "zh-CN", "confidence": 0.95},
    {"appid": 271590, "canonical_name": "Grand Theft Auto V Legacy", "alias": "GTA5", "locale": "zh-CN", "confidence": 1.0},
    {"appid": 271590, "canonical_name": "Grand Theft Auto V Legacy", "alias": "侠盗猎车手5", "locale": "zh-CN", "confidence": 1.0},
    {"appid": 1086940, "canonical_name": "Baldur's Gate 3", "alias": "博德之门3", "locale": "zh-CN", "confidence": 1.0},
    {"appid": 1086940, "canonical_name": "Baldur's Gate 3", "alias": "BG3", "locale": "zh-CN", "confidence": 0.9},
    {"appid": 292030, "canonical_name": "The Witcher 3: Wild Hunt", "alias": "巫师3", "locale": "zh-CN", "confidence": 1.0},
    {"appid": 275850, "canonical_name": "No Man's Sky", "alias": "无人深空", "locale": "zh-CN", "confidence": 1.0},
    {"appid": 578080, "canonical_name": "PUBG: BATTLEGROUNDS", "alias": "吃鸡", "locale": "zh-CN", "confidence": 0.95},
    {"appid": 578080, "canonical_name": "PUBG: BATTLEGROUNDS", "alias": "绝地求生", "locale": "zh-CN", "confidence": 1.0},
    {"appid": 1091500, "canonical_name": "Cyberpunk 2077", "alias": "赛博朋克2077", "locale": "zh-CN", "confidence": 1.0},
    {"appid": 1091500, "canonical_name": "Cyberpunk 2077", "alias": "2077", "locale": "zh-CN", "confidence": 0.9},
    {"appid": 1174180, "canonical_name": "Red Dead Redemption 2", "alias": "大表哥2", "locale": "zh-CN", "confidence": 0.95},
    {"appid": 1174180, "canonical_name": "Red Dead Redemption 2", "alias": "RDR2", "locale": "zh-CN", "confidence": 1.0},
    {"appid": 1174180, "canonical_name": "Red Dead Redemption 2", "alias": "荒野大镖客2", "locale": "zh-CN", "confidence": 1.0},
    {"appid": 413150, "canonical_name": "Stardew Valley", "alias": "星露谷", "locale": "zh-CN", "confidence": 1.0},
    {"appid": 413150, "canonical_name": "Stardew Valley", "alias": "星露谷物语", "locale": "zh-CN", "confidence": 1.0},
    {"appid": 359550, "canonical_name": "Tom Clancy's Rainbow Six Siege", "alias": "彩虹六号", "locale": "zh-CN", "confidence": 1.0},
    {"appid": 359550, "canonical_name": "Tom Clancy's Rainbow Six Siege", "alias": "R6", "locale": "zh-CN", "confidence": 0.95},
    {"appid": 381210, "canonical_name": "Dead by Daylight", "alias": "黎明杀机", "locale": "zh-CN", "confidence": 1.0},
    {"appid": 381210, "canonical_name": "Dead by Daylight", "alias": "DBD", "locale": "zh-CN", "confidence": 0.95},
    {"appid": 105600, "canonical_name": "Terraria", "alias": "泰拉瑞亚", "locale": "zh-CN", "confidence": 1.0},
    {"appid": 252490, "canonical_name": "Rust", "alias": "腐蚀", "locale": "zh-CN", "confidence": 0.9},
    {"appid": 374320, "canonical_name": "DARK SOULS III", "alias": "黑魂3", "locale": "zh-CN", "confidence": 1.0},
    {"appid": 374320, "canonical_name": "DARK SOULS III", "alias": "黑暗之魂3", "locale": "zh-CN", "confidence": 1.0},
    {"appid": 1145360, "canonical_name": "Hades", "alias": "哈迪斯", "locale": "zh-CN", "confidence": 1.0},
    {"appid": 367520, "canonical_name": "Hollow Knight", "alias": "空洞骑士", "locale": "zh-CN", "confidence": 1.0},
    {"appid": 489830, "canonical_name": "The Elder Scrolls V: Skyrim Special Edition", "alias": "老滚5", "locale": "zh-CN", "confidence": 0.95},
    {"appid": 489830, "canonical_name": "The Elder Scrolls V: Skyrim Special Edition", "alias": "上古卷轴5", "locale": "zh-CN", "confidence": 1.0},
    {"appid": 322330, "canonical_name": "Don't Starve Together", "alias": "饥荒联机", "locale": "zh-CN", "confidence": 1.0},
    {"appid": 646570, "canonical_name": "Slay the Spire", "alias": "杀戮尖塔", "locale": "zh-CN", "confidence": 1.0},
    {"appid": 1593500, "canonical_name": "God of War", "alias": "战神", "locale": "zh-CN", "confidence": 1.0},
    {"appid": 892970, "canonical_name": "Valheim", "alias": "英灵神殿", "locale": "zh-CN", "confidence": 1.0},
    {"appid": 1623730, "canonical_name": "Palworld", "alias": "幻兽帕鲁", "locale": "zh-CN", "confidence": 1.0},
    {"appid": 945360, "canonical_name": "Among Us", "alias": "太空狼人杀", "locale": "zh-CN", "confidence": 0.9},
    {"appid": 548430, "canonical_name": "Deep Rock Galactic", "alias": "深岩银河", "locale": "zh-CN", "confidence": 1.0},
    {"appid": 294100, "canonical_name": "RimWorld", "alias": "环世界", "locale": "zh-CN", "confidence": 1.0},
    {"appid": 427520, "canonical_name": "Factorio", "alias": "异星工厂", "locale": "zh-CN", "confidence": 1.0},
    {"appid": 1326470, "canonical_name": "Sons Of The Forest", "alias": "森林之子", "locale": "zh-CN", "confidence": 1.0},
    {"appid": 1888160, "canonical_name": "ARMORED CORE VI FIRES OF RUBICON", "alias": "装甲核心6", "locale": "zh-CN", "confidence": 1.0},
    {"appid": 281990, "canonical_name": "Stellaris", "alias": "群星", "locale": "zh-CN", "confidence": 1.0},
    {"appid": 1158850, "canonical_name": "The Great Ace Attorney Chronicles", "alias": "大逆转裁判", "locale": "zh-CN", "confidence": 0.9},
    {"appid": 255710, "canonical_name": "Cities: Skylines", "alias": "城市天际线", "locale": "zh-CN", "confidence": 1.0},
    {"appid": 221100, "canonical_name": "DayZ", "alias": "僵尸末日", "locale": "zh-CN", "confidence": 0.85},
    {"appid": 1794680, "canonical_name": "Vampire Survivors", "alias": "吸血鬼幸存者", "locale": "zh-CN", "confidence": 1.0},
    {"appid": 1190460, "canonical_name": "DEATH STRANDING", "alias": "死亡搁浅", "locale": "zh-CN", "confidence": 1.0},
    {"appid": 2208920, "canonical_name": "Assassin's Creed Valhalla", "alias": "刺客信条英灵殿", "locale": "zh-CN", "confidence": 1.0},
    {"appid": 1551360, "canonical_name": "Forza Horizon 5", "alias": "地平线5", "locale": "zh-CN", "confidence": 0.95},
    {"appid": 1172470, "canonical_name": "Apex Legends", "alias": "APEX", "locale": "zh-CN", "confidence": 0.95},
    {"appid": 1222670, "canonical_name": "The Sims 4", "alias": "模拟人生4", "locale": "zh-CN", "confidence": 1.0},
    {"appid": 1290000, "canonical_name": "PowerWash Simulator", "alias": "冲就完事模拟器", "locale": "zh-CN", "confidence": 1.0},
]

# ---------------------------------------------------------------------------
# Review keywords, knowledge docs, sample conversations
# ---------------------------------------------------------------------------

PRAISE_KEYWORDS_POOLS = [
    ["画面精美", "打击感好", "剧情优秀", "优化出色"],
    ["音乐动听", "自由度极高", "内容丰富", "手感流畅"],
    ["玩法创新", "美术风格独特", "合作有趣", "更新频繁"],
    ["社区活跃", "平衡性好", "沉浸感强", "性价比高"],
    ["情怀加分", "本地化优秀", "新手友好", "竞品无对手"],
]
COMPLAINT_KEYWORDS_POOLS = [
    ["服务器卡顿", "匹配时间久", "优化差", "BUG太多"],
    ["付费太贵", "内容太少", "更新慢", "外挂猖獗"],
    ["平衡性差", "新手不友好", "剧情敷衍", "重复度高"],
    ["画面过时", "UI难用", "没中文", "优化退步"],
]

KNOWLEDGE_DOCS = [
    {"title": "2026年Q2 Steam市场趋势分析", "source_type": "note", "content": "# 2026年Q2 Steam市场趋势分析\n\n## 总体趋势\n- Steam同时在线人数再创新高，峰值突破4000万\n- 亚洲市场增长强劲，中国和东南亚地区贡献主要增量\n- F2P游戏依然占据在线人数榜首\n\n## 品类分析\n- 生存建造类持续火热\n- 魂系游戏扩展到更多题材\n- 策略游戏稳定增长\n\n## 定价趋势\n- AAA游戏定价从$60→$70→$80\n- 中国区定价约美区的40-60%\n- 季票和Battle Pass成为主要收入来源"},
    {"title": "游戏定价策略研究笔记", "source_type": "note", "content": "# 游戏定价策略研究笔记\n\n## 区域定价模型\n1. 发达国家市场: 基准定价\n2. 新兴市场: 区域折扣定价\n3. 低收入市场: 深度折扣\n\n## 中国区定价特殊考量\n- 中国玩家对价格敏感度高\n- 中国区定价通常为美区的40-50%\n\n## 案例分析\n- Elden Ring: 298元定价\n- 黑神话悟空: 268元定价"},
    {"title": "Steam评测分析方法论", "source_type": "note", "content": "# Steam评测分析方法论\n\n## 关键指标\n- 好评率：正面评测比例\n- 评测趋势：近期 vs 历史的变化\n- 评测活跃度：评测发布频率\n\n## 常见评测模式\n- 重大更新翻车\n- 付费模式争议\n- 服务器问题\n- 口碑传播效应"},
    {"title": "Steam API数据采集最佳实践", "source_type": "note", "content": "# Steam API数据采集最佳实践\n\n## 公开API端点\n- store.steampowered.com/api/appdetails\n- api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers\n- store.steampowered.com/api/storesearch\n\n## 采集频率建议\n- 在线人数：每小时\n- 商店信息：每天\n- 评测：每天"},
    {"title": "2026年热门游戏发行日历", "source_type": "note", "content": "# 2026年热门游戏发行日历\n\n## Q1\n- Monster Hunter Wilds\n- Final Fantasy VII Rebirth (PC)\n\n## Q2\n- Elden Ring DLC\n- Hades II 正式版\n\n## Q3-Q4\n- GTA VI 主机版\n- Call of Duty 2026"},
]

SAMPLE_CONVERSATIONS = [
    {"title": "CS2在线人数趋势分析",
     "messages": [
         ("user", "帮我分析一下CS2最近一周的在线人数趋势"),
         ("assistant", "根据过去7天的快照数据，CS2的在线人数整体呈稳定趋势。日均在线约80万人，峰值出现在晚上8-11点，周末峰值比工作日高约15%。"),
         ("user", "对比一下CS2和Dota 2的人数"),
         ("assistant", "CS2过去7天平均在线80万，Dota 2平均45万。CS2的用户基数约为Dota 2的1.8倍。")]},
    {"title": "艾尔登法环折扣时机分析",
     "messages": [
         ("user", "老头环什么时候会打折？"),
         ("assistant", "根据历史数据，Elden Ring在过去7天内有过折扣调整。当前价格为298元。建议关注即将到来的季末促销。"),
         ("user", "历史最低价是多少？"),
         ("assistant", "Elden Ring在中国区历史最低价为198元（约33%折扣），出现在上季度Steam春季促销期间。")]},
    {"title": "多游戏在线人数对比",
     "messages": [
         ("user", "对比一下几个热门游戏的在线人数"),
         ("assistant", "当前在线人数排名：\n1. CS2: ~800,000\n2. Dota 2: ~450,000\n3. PUBG: ~200,000\n4. Apex: ~180,000\n5. Rust: ~90,000")]},
    {"title": "幻兽帕鲁评测分析",
     "messages": [
         ("user", "分析一下幻兽帕鲁的玩家评论"),
         ("assistant", "Palworld好评率约90%。玩家主要称赞其创新的怪物收集+生存建造玩法。主要批评集中在后期内容不足和部分优化问题。")]},
]

# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def clear_database(session: Session) -> None:
    from sqlmodel import delete
    tables = [SourceClaim, SentimentEvent, WebSource, ReviewAnalysis, MonitorAlert, MonitorTask,
              SnapshotLabel, GameSnapshot, Message, ToolCall, AnalysisReport, Conversation,
              KnowledgeChunk, KnowledgeDocument, GameAlias, Game, AppSetting]
    for table in tables:
        session.exec(delete(table))
    session.commit()
    print("Database cleared")


def seed_all(session: Session, num_games: int = 110, days: int = 15, hours_per_snapshot: int = 1) -> None:
    games_to_use = REAL_GAMES[:num_games]
    now = datetime.now(UTC)

    # --- 1. Games ---
    print(f"\nSeeding {len(games_to_use)} games (verified against Steam API)...")
    game_objects: dict[int, Game] = {}
    for g in games_to_use:
        game = Game(appid=g["appid"], name=g["name"], type=g["type"],
                    header_image=f"https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/{g['appid']}/header.jpg",
                    last_resolved_at=now)
        session.add(game)
        session.flush()
        game_objects[g["appid"]] = game
    session.commit()
    print(f"  Created {len(game_objects)} games")

    # --- 2. Game Aliases ---
    print("Seeding game aliases...")
    alias_count = 0
    for a in EXTRA_ALIASES:
        if a["appid"] in game_objects:
            normalized = a["alias"].lower().replace(" ", "").replace("-", "").replace("'", "")
            existing = session.exec(select(GameAlias).where(
                GameAlias.appid == a["appid"], GameAlias.normalized_alias == normalized, GameAlias.locale == a["locale"])).first()
            if not existing:
                session.add(GameAlias(appid=a["appid"], canonical_name=a["canonical_name"], alias=a["alias"],
                                      normalized_alias=normalized, locale=a.get("locale", "zh-CN"),
                                      alias_type="nickname", source="seed", confidence=a.get("confidence", 0.9)))
                alias_count += 1
    session.commit()
    print(f"  Created {alias_count} additional aliases")

    # --- 3. Snapshots ---
    total_hours = days * 24 // hours_per_snapshot
    print(f"Generating snapshots: {len(games_to_use)} games × {days} days × {24 // hours_per_snapshot} snapshots/hour = ~{len(games_to_use) * total_hours} total...")

    batch: list[GameSnapshot] = []
    batch_size = 500
    total_snapshots = 0

    for game_data in games_to_use:
        game = game_objects[game_data["appid"]]
        start_dt = now - timedelta(days=days)
        current = start_dt
        while current <= now:
            snap_data = generate_snapshot_data(game_data, current)
            snapshot = GameSnapshot(
                game_id=game.id or 0, appid=game_data["appid"], collected_at=current,
                source=snap_data["source"], cc=snap_data["cc"], language=snap_data["language"],
                player_count=snap_data["player_count"], is_free=snap_data["is_free"],
                currency=snap_data["currency"], initial_price=snap_data["initial_price"],
                final_price=snap_data["final_price"], discount_percent=snap_data["discount_percent"],
                recommendations_total=snap_data["recommendations_total"],
                raw_store_json=snap_data["raw_store_json"], raw_players_json=snap_data["raw_players_json"],
                raw_news_json=snap_data["raw_news_json"], source_urls_json=snap_data["source_urls_json"],
            )
            batch.append(snapshot)
            total_snapshots += 1
            if len(batch) >= batch_size:
                session.add_all(batch)
                session.commit()
                print(f"  Inserted {total_snapshots} snapshots...")
                batch = []
            current += timedelta(hours=hours_per_snapshot)

    if batch:
        session.add_all(batch)
        session.commit()
    print(f"  Created {total_snapshots} snapshots total")

    # --- 4. Snapshot Labels ---
    print("Adding labels to snapshots...")
    all_snapshot_ids = list(session.exec(select(GameSnapshot.id).order_by(GameSnapshot.collected_at)).all())
    label_count = 0
    special_labels = ["大版本更新", "Steam特卖", "周末高峰", "首发日", "免费周末"]
    for sid in random.sample(all_snapshot_ids, min(len(all_snapshot_ids) // 20, 800)):
        label = random.choice(special_labels)
        existing = session.exec(select(SnapshotLabel).where(SnapshotLabel.snapshot_id == sid, SnapshotLabel.label == label)).first()
        if not existing:
            session.add(SnapshotLabel(snapshot_id=sid, label=label))
            label_count += 1
    session.commit()
    print(f"  Added {label_count} snapshot labels")

    # --- 5. Review Analyses ---
    print("Seeding review analyses...")
    review_count = 0
    sample_games = random.sample(games_to_use, min(40, len(games_to_use)))
    for g in sample_games:
        total_reviews = random.randint(500, 100000)
        positive_ratio = round(random.uniform(0.65, 0.97), 3)
        praise = random.choice(PRAISE_KEYWORDS_POOLS)
        complaint = random.choice(COMPLAINT_KEYWORDS_POOLS)
        session.add(ReviewAnalysis(
            appid=g["appid"], total_reviews=total_reviews, positive_ratio=positive_ratio,
            top_praise_keywords_json=json.dumps(praise, ensure_ascii=False),
            top_complaint_keywords_json=json.dumps(complaint, ensure_ascii=False),
            summary=f"{g['name']}共{total_reviews}条评测，好评率{positive_ratio*100:.1f}%。玩家主要赞赏{praise[0]}、{praise[1]}，主要批评{complaint[0]}、{complaint[1]}。",
            source_url=f"https://steamcommunity.com/app/{g['appid']}/reviews/",
            analyzed_at=now - timedelta(hours=random.randint(1, 72))))
        review_count += 1
    session.commit()
    print(f"  Created {review_count} review analyses")

    # --- 6. Web Sentiment Events ---
    print("Seeding web sentiment data...")
    sentiment_sample = random.sample(games_to_use, min(20, len(games_to_use)))
    event_count, source_count, claim_count = 0, 0, 0
    for g in sentiment_sample:
        event_sentiment = random.choice(["positive", "negative", "mixed"])
        event = SentimentEvent(
            game_key=g["name"], appid=g["appid"], event_date=now - timedelta(days=random.randint(1, 14)),
            event_type="web_sentiment",
            summary=f"关于{g['name']}的网络舆情分析显示，整体情绪{'正面' if event_sentiment == 'positive' else '负面' if event_sentiment == 'negative' else '复杂'}。",
            sentiment=event_sentiment, severity=random.choice(["low", "medium", "high"]),
            evidence_count=random.randint(1, 5), confidence=round(random.uniform(0.6, 0.95), 2))
        session.add(event)
        session.flush()
        event_count += 1
        for _ in range(random.randint(1, 3)):
            source_url = f"https://example.com/article/{g['appid']}/{random.randint(10000, 99999)}"
            content = f"关于{g['name']}的玩家讨论 #{random.randint(1, 999999)}..."
            ws = WebSource(game_key=g["name"], appid=g["appid"], source_type=random.choice(["web", "reddit", "forum"]),
                           source_url=source_url, title=f"玩家讨论：{g['name']}最新动态",
                           author=f"用户{random.randint(100, 999)}",
                           published_at=now - timedelta(days=random.randint(1, 14)),
                           fetched_at=now - timedelta(hours=random.randint(1, 48)),
                           raw_text=content, excerpt=f"关于{g['name']}的讨论摘要...",
                           content_hash=hashlib.sha256(content.encode()).hexdigest())
            session.add(ws)
            session.flush()
            source_count += 1
            for _ in range(random.randint(1, 2)):
                stance = random.choice(["positive", "negative", "neutral"])
                aspect = random.choice(['画面', '玩法', '剧情', '优化', '服务器'])
                claim_text = f"{g['name']}的{aspect}{'很出色' if stance == 'positive' else '需要改进' if stance == 'negative' else '表现一般'}"
                session.add(SourceClaim(source_id=ws.id or 0, event_id=event.id, claim_type="player_feedback",
                                        claim_text=claim_text, stance=stance,
                                        confidence=round(random.uniform(0.5, 0.9), 2)))
                claim_count += 1
    session.commit()
    print(f"  Created {event_count} sentiment events, {source_count} web sources, {claim_count} claims")

    # --- 7. Knowledge Documents ---
    print("Seeding knowledge documents...")
    doc_count = 0
    for doc_data in KNOWLEDGE_DOCS:
        content = doc_data["content"]
        chunk_count = max(1, len(content) // 700)
        doc = KnowledgeDocument(title=doc_data["title"], source_type=doc_data["source_type"],
                                appid=None, tags_json=json.dumps(["研究", "分析"], ensure_ascii=False),
                                metadata_json=json.dumps({}),
                                content_hash=hashlib.sha256(content.encode()).hexdigest(),
                                chunk_count=chunk_count)
        session.add(doc)
        session.flush()
        session.add(KnowledgeChunk(document_id=doc.id or 0, appid=None, ordinal=0,
                                   heading=doc_data["title"], content=content,
                                   token_count=len(content) // 4,
                                   chunk_hash=hashlib.sha256(content.encode()).hexdigest(),
                                   embedding_json=json.dumps([0.0] * 256)))
        doc_count += 1
    session.commit()
    print(f"  Created {doc_count} knowledge documents")

    # --- 8. Conversations + Messages + Reports ---
    print("Seeding conversations and reports...")
    conv_count, msg_count, report_count = 0, 0, 0
    for conv_data in SAMPLE_CONVERSATIONS:
        conv = Conversation(title=conv_data["title"])
        session.add(conv)
        session.flush()
        conv_count += 1
        for role, content in conv_data["messages"]:
            session.add(Message(conversation_id=conv.id or 0, role=role, content=content))
            msg_count += 1
        report = AnalysisReport(query=conv_data["messages"][0][1],
                                answer_markdown=conv_data["messages"][1][1] if len(conv_data["messages"]) > 1 else "分析完成",
                                structured_result_json=json.dumps({"task_type": "game_analysis"}),
                                evidence_json=json.dumps([{"source": "Steam API", "url": "https://store.steampowered.com"}], ensure_ascii=False),
                                snapshot_ids_json=json.dumps(random.sample(all_snapshot_ids, min(5, len(all_snapshot_ids)))))
        session.add(report)
        report_count += 1
    session.commit()
    print(f"  Created {conv_count} conversations, {msg_count} messages, {report_count} reports")

    # --- 9. Monitor Tasks ---
    print("Seeding monitor tasks...")
    monitor_count = 0
    monitor_games = random.sample(games_to_use, min(15, len(games_to_use)))
    for g in monitor_games:
        if not session.exec(select(MonitorTask).where(MonitorTask.appid == g["appid"])).first():
            session.add(MonitorTask(appid=g["appid"], interval_minutes=random.choice([60, 120, 360]),
                                    enabled=True, last_run_at=now - timedelta(hours=random.randint(1, 24))))
            monitor_count += 1
    session.commit()
    print(f"  Created {monitor_count} monitor tasks")

    # --- 10. App Settings ---
    for key, value in {"default_cc": "CN", "default_language": "schinese", "default_currency": "CNY",
                       "deepseek_model": "deepseek-v4-pro", "allow_model_fallback": "true",
                       "collection_interval_minutes": "60"}.items():
        if not session.exec(select(AppSetting).where(AppSetting.key == key)).first():
            session.add(AppSetting(key=key, value=value))
    session.commit()
    print("  App settings seeded")

    # --- 11. Monitor Alerts ---
    alert_count = 0
    for g in monitor_games[:8]:
        snaps = session.exec(select(GameSnapshot.id).where(GameSnapshot.appid == g["appid"]).order_by(GameSnapshot.collected_at.desc()).limit(2)).all()
        if len(snaps) >= 2:
            session.add(MonitorAlert(appid=g["appid"], snapshot_id=snaps[0],
                                     alert_type=random.choice(["player_surge", "player_drop", "price_change", "new_historical_low"]),
                                     summary=random.choice([f"{g['name']}在线人数暴涨", f"{g['name']}在线人数暴跌", f"{g['name']}出现新折扣", f"{g['name']}达到历史最低价"]),
                                     severity=random.choice(["info", "warning", "high"])))
            alert_count += 1
    session.commit()
    print(f"  Created {alert_count} monitor alerts")

    # --- Summary ---
    print("\n" + "=" * 60)
    print("SEEDING COMPLETE!")
    print(f"  Games:           {len(game_objects)}")
    print(f"  Aliases:         {alias_count}")
    print(f"  Snapshots:       {total_snapshots}")
    print(f"  Snapshot Labels: {label_count}")
    print(f"  Review Analyses: {review_count}")
    print(f"  Sentiment Events:{event_count}")
    print(f"  Web Sources:     {source_count}")
    print(f"  Source Claims:   {claim_count}")
    print(f"  Knowledge Docs:  {doc_count}")
    print(f"  Conversations:   {conv_count}")
    print(f"  Messages:        {msg_count}")
    print(f"  Reports:         {report_count}")
    print(f"  Monitor Tasks:   {monitor_count}")
    print(f"  Monitor Alerts:  {alert_count}")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Seed SteamAnalysis database")
    parser.add_argument("--clear", action="store_true", help="Clear database before seeding")
    parser.add_argument("--games", type=int, default=110, help="Number of games (max 110)")
    parser.add_argument("--days", type=int, default=15, help="Days of snapshot history")
    parser.add_argument("--hours", type=int, default=1, help="Hours between snapshots")
    args = parser.parse_args()

    settings = get_settings()
    db_path = settings.database_url.replace("sqlite:///", "./")

    # Clear old database if requested
    if args.clear and os.path.exists(db_path):
        os.remove(db_path)
        print(f"Removed old database: {db_path}")

    # Create tables
    print("Creating database tables...")
    SQLModel.metadata.create_all(engine)

    try:
        init_knowledge_indexes(engine)
    except Exception as e:
        print(f"Warning: Could not init knowledge indexes: {e}")

    with Session(engine) as session:
        try:
            seed_default_aliases(session)
        except Exception as e:
            print(f"Warning: Could not seed default aliases: {e}")

        seed_all(session, num_games=min(args.games, len(REAL_GAMES)), days=args.days,
                 hours_per_snapshot=args.hours)

    print("\nDone! Start with: .venv/Scripts/python -m uvicorn app.main:app --reload --port 9000")


if __name__ == "__main__":
    main()
