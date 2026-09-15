"""Pass 2: turn features.csv into a match timeline + events (prototype)."""
import csv, sys, json
from itertools import groupby

rows = list(csv.DictReader(open(sys.argv[1] if len(sys.argv) > 1 else 'features.csv')))
for r in rows:
    for k in r: r[k] = float(r[k])
DT = rows[1]['t'] - rows[0]['t']
MIN_DEAD = float(sys.argv[2]) if len(sys.argv) > 2 else 4.0  # seconds; respawn is >= ~5.5 s

def runs(flags, min_len):
    """yield (start_idx, end_idx_exclusive) for runs of True at least min_len samples"""
    i = 0
    while i < len(flags):
        if flags[i]:
            j = i
            while j < len(flags) and flags[j]: j += 1
            if j - i >= min_len: yield i, j
            i = j
        else: i += 1

def smooth(flags, gap):
    """fill False gaps shorter than `gap` samples between True runs"""
    out = list(flags); i = 0
    while i < len(out):
        if not out[i]:
            j = i
            while j < len(out) and not out[j]: j += 1
            if 0 < i and j < len(out) and j - i <= gap:
                for k in range(i, j): out[k] = True
            i = j
        else: i += 1
    return out

# --- 1. in-game segments: timer box present (dark box) and not a menu/result (mean_v sane)
hud = [0.55 < r['timer_dark'] < 0.85 and 0.1 < r['pts_white'] < 0.5 for r in rows]  # timer box + points counter
ingame = smooth(hud, int(6 / DT))  # bridge map screen / cutscenes up to 6 s
matches = [(a, b) for a, b in runs(ingame, int(60 / DT))]
print(f'{len(matches)} match segment(s):')
for mi, (a, b) in enumerate(matches):
    print(f'  match {mi+1}: {rows[a]["t"]:.1f}s -> {rows[b-1]["t"]:.1f}s  ({rows[b-1]["t"]-rows[a]["t"]:.0f}s)')

events = []
for mi, (a, b) in enumerate(matches):
    seg = rows[a:b]
    t0 = seg[0]['t']
    # --- 2. HUD deaths for the 8 slots (own slot never shows an X; it is filtered out by being always-alive)
    vis = hud[a:b]
    for s in range(8):
        dead = []; prev = False
        for r, v in zip(seg, vis):
            if v: prev = r[f'slot{s}_sat'] < 0.15  # grey X icon: no team colour, dark silhouette
            dead.append(prev)  # HUD hidden (map etc.): carry previous state
        dead = smooth(dead, 2)
        for i, j in runs(dead, int(MIN_DEAD / DT)):
            events.append(dict(match=mi+1, t=round(seg[i]['t'], 2), rel=round(seg[i]['t']-t0, 1), type='hud_death',
                               slot=s, team='ally' if s < 4 else 'enemy', dur=round((j-i)*DT, 1)))
    # --- 3. own kills: black kill-feed band at bottom center
    kf = [v and r['kf_dark'] > 0.6 for r, v in zip(seg, vis)]
    kf = smooth(kf, 2)
    for i, j in runs(kf, int(1.0 / DT)):
        events.append(dict(match=mi+1, t=round(seg[i]['t'], 2), rel=round(seg[i]['t']-t0, 1), type='killfeed', dur=round((j-i)*DT, 1)))
    # --- 4. own deaths: black bubble in the middle with white text (dark AND some white)
    db = [v and r['db_dark'] > 0.5 and r['db_white'] > 0.08 for r, v in zip(seg, vis)]
    db = smooth(db, 2)
    for i, j in runs(db, 1):
        events.append(dict(match=mi+1, t=round(seg[i]['t'], 2), rel=round(seg[i]['t']-t0, 1), type='death_bubble', dur=round((j-i)*DT, 1)))

GT = {1: [2,0,6,4, 1,4,2,3], 2: [0,2,3,5, 1,2,1,2], 3: [1,5,4,2, 3,4,4,3]} if 'features2' not in sys.argv[1:2] else {}
events.sort(key=lambda e: e['t'])
json.dump(events, open('events.json', 'w'), ensure_ascii=False, indent=1)
for mi in range(len(matches)):
    ev = [e for e in events if e['match'] == mi+1]
    print(f'\n== match {mi+1} ==')
    for s in range(8):
        n = sum(1 for e in ev if e['type']=='hud_death' and e['slot']==s)
        gt = GT.get(mi+1, [None]*8)[s]
        print(f'  slot{s} ({"ally" if s<4 else "enemy"}) deaths: {n}' + (f'   (truth {gt}){"  <-- MISMATCH" if gt != n else ""}' if gt is not None else ''))
    print('  killfeed runs:', sum(1 for e in ev if e['type']=='killfeed'), ' death bubbles:', sum(1 for e in ev if e['type']=='death_bubble'))
    for e in ev:
        print('   ', f"{e['rel']:6.1f}s", e['type'], e.get('slot',''), f"dur={e['dur']}")
