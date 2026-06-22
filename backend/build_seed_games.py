"""
Build complete verified game list: read verified_games.json,
add known-good games that transiently failed, estimate player counts,
write to verified_games_complete.json.
"""
import json

KNOWN_GOOD = {
    440:  {"name": "Team Fortress 2", "type": "game", "is_free": True, "initial_price": 0, "currency": "CNY", "recommendations_total": 1100000, "genres": ["Action", "Free to Play"], "developers": ["Valve"], "publishers": ["Valve"]},
    570:  {"name": "Dota 2", "type": "game", "is_free": True, "initial_price": 0, "currency": "CNY", "recommendations_total": 2200000, "genres": ["Action", "Strategy", "Free to Play"], "developers": ["Valve"], "publishers": ["Valve"]},
    730:  {"name": "Counter-Strike 2", "type": "game", "is_free": True, "initial_price": 0, "currency": "CNY", "recommendations_total": 8500000, "genres": ["Action", "Free to Play"], "developers": ["Valve"], "publishers": ["Valve"]},
}

with open('verified_games.json', 'r', encoding='utf-8') as f:
    verified = json.load(f)

all_games = {}

for g in verified:
    appid = g['appid']
    recs = g.get('recommendations_total', 0)
    is_free = g.get('is_free', False)

    if is_free:
        base = 200000 if recs > 1000000 else (80000 if recs > 500000 else (30000 if recs > 100000 else 5000))
    else:
        base = 40000 if recs > 1000000 else (20000 if recs > 500000 else (10000 if recs > 200000 else (5000 if recs > 50000 else 1500)))

    all_games[appid] = {
        'appid': appid,
        'name': g['name'],
        'type': g['type'],
        'base_players': base,
        'peak_mult': 1.3 if is_free else 1.5,
        'price': g.get('initial_price', 0),
        'currency': g.get('currency', 'CNY'),
        'is_free': is_free,
        'recommendations': recs,
        'genres': g.get('genres', []),
        'developers': g.get('developers', []),
        'publishers': g.get('publishers', []),
    }

for appid, data in KNOWN_GOOD.items():
    recs = data['recommendations_total']
    is_free = data['is_free']
    base = 800000 if appid == 730 else (450000 if appid == 570 else (70000 if appid == 440 else 10000))
    all_games[appid] = {
        'appid': appid, 'name': data['name'], 'type': data['type'],
        'base_players': base, 'peak_mult': 1.3 if is_free else 1.5,
        'price': data['initial_price'], 'currency': data['currency'],
        'is_free': is_free, 'recommendations': recs,
        'genres': data['genres'], 'developers': data['developers'], 'publishers': data['publishers'],
    }

result = sorted(all_games.values(), key=lambda g: g['appid'])
print(f"Total complete games: {len(result)}")

with open('verified_games_complete.json', 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
print(f"Written to verified_games_complete.json")
