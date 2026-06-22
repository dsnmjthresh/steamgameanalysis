"""
Verify games against Steam API — sequential to avoid rate limiting.
Queries with English language to get canonical English names.
Outputs verified_games.json with correct appid→name mappings.
"""
import asyncio, json, sys, httpx

APPIDS = sorted(set([
    730, 570, 1172470, 271590, 1245620, 2358720, 1086940, 1938090, 252490,
    440, 578080, 292030, 582010, 2239550, 381210, 359550, 1248130, 1174180,
    1222670, 431960, 105600, 413150, 1145360, 1145350, 275850, 346110,
    1063730, 374320, 489830, 1593500, 2322011, 1940340, 1966720, 1478810,
    1979980, 945360, 892970, 1623730, 440900, 281990, 236850, 394360,
    255710, 949230, 493340, 648350, 552520, 2208920, 1091500, 1085660,
    1301690, 1364780, 739630, 1203220, 632470, 2215430, 2300320, 238960,
    383150, 990080, 548430, 239140, 534380, 1151640, 2420110, 1551360,
    1948980, 1811260, 2357570, 1687950, 2050650, 1888160, 1745510,
    2000950, 703080, 1649240, 1659040, 1716740, 1712850, 417290, 221100,
    294100, 427520, 646570, 268910, 367520, 322330, 1239520, 1238840,
    1517290, 1293830, 389730, 1446780, 1326470, 1290000, 1328350,
    1158850, 107410, 306130, 872790, 1250410, 1172380, 251570, 252950,
    376210, 304930, 433850, 745940, 1262540, 1781410, 1809700, 1823910,
    999220, 1286830, 1190460, 594570, 289070, 227300, 582660, 1794680,
]))

async def get_game(client, appid, lang='english'):
    url = f'https://store.steampowered.com/api/appdetails?appids={appid}&cc=CN&l={lang}'
    try:
        r = await client.get(url)
        data = r.json()
        gd = data.get(str(appid), {}) if isinstance(data, dict) else {}
        if not gd.get('success'): return None
        d = gd['data']
        pi = d.get('price_overview') or {}
        recs = d.get('recommendations') or {}
        if not isinstance(recs, dict): recs = {}
        return {
            'appid': appid,
            'name': d.get('name', ''),
            'type': d.get('type', 'unknown'),
            'is_free': d.get('is_free', False),
            'initial_price': pi.get('initial', 0) if pi else 0,
            'currency': pi.get('currency', 'CNY') if pi else 'CNY',
            'discount_percent': pi.get('discount_percent', 0) if pi else 0,
            'recommendations_total': recs.get('total', 0),
            'genres': [g.get('description', '') for g in d.get('genres', [])],
            'developers': d.get('developers', []),
            'publishers': d.get('publishers', []),
            'header_image': d.get('header_image', ''),
        }
    except Exception as e:
        return None

async def main():
    verified = {}
    failed = []
    total = len(APPIDS)

    async with httpx.AsyncClient(timeout=20) as client:
        for idx, appid in enumerate(APPIDS):
            data = await get_game(client, appid)
            if data:
                verified[appid] = data
            else:
                failed.append(appid)

            if (idx + 1) % 5 == 0:
                print(f'  {idx+1}/{total}: {len(verified)} OK, {len(failed)} fail', file=sys.stderr)
            await asyncio.sleep(0.35)  # Rate limit: ~3 requests/sec

    print(f'\n{"="*60}', file=sys.stderr)
    print(f'VERIFIED: {len(verified)} games', file=sys.stderr)
    print(f'FAILED:   {len(failed)} appids', file=sys.stderr)
    if failed:
        print(f'Failed: {failed}', file=sys.stderr)
    print(f'{"="*60}', file=sys.stderr)

    # Save as JSON
    with open('verified_games.json', 'w', encoding='utf-8') as f:
        json.dump(list(verified.values()), f, ensure_ascii=False, indent=2)
    print(f'\nSaved {len(verified)} games to verified_games.json', file=sys.stderr)

    # Also print summary of name changes
    from seed_data import UNIQUE_GAMES as old_games
    old_map = {g['appid']: g['name'] for g in old_games}
    print('\nName differences (old → new):', file=sys.stderr)
    for appid, data in sorted(verified.items()):
        old_name = old_map.get(appid, '(NEW)')
        new_name = data['name']
        if old_name != new_name:
            print(f'  {appid}: "{old_name}" → "{new_name}"', file=sys.stderr)

asyncio.run(main())
