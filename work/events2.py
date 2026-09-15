"""Pass 2 (v2): features CSV from probe2.py -> match segments + events, with ground-truth check."""
import csv, sys, json

SRC = sys.argv[1]
rows = list(csv.DictReader(open(SRC)))
for r in rows:
    for k in r: r[k] = float(r[k])
DT = rows[1]['t'] - rows[0]['t']
import os
MIN_DEAD = float(os.environ.get('MIN_DEAD', 3.0)); DARK_THR = float(os.environ.get('DARK_THR', 0.25)); GAP = float(os.environ.get('GAP', 0.5))

# ground truth deaths per HUD slot (ally 4, enemy 4), from result scoreboards; HUD order = intro card order
GT = {'f2_video1.csv': {1: [2,0,6,4, 1,4,2,3], 2: [0,2,3,5, 1,2,1,2], 3: [1,5,4,2, 3,4,4,3]},
      'f2_video2.csv': {1: [1,2,2,0, 1,0,3,4], 2: [3,5,0,5, 2,0,4,0]}}.get(SRC, {})
GT_SELF = {'f2_video1.csv': {1: (3, 4, 6), 2: (3, 5, 1), 3: (3, 2, 5)},   # (self slot, deaths, kills+assists)
           'f2_video2.csv': {1: (0, 1, 4), 2: (0, 3, 3)}}.get(SRC, {})

def runs(flags, min_len):
    i = 0
    while i < len(flags):
        if flags[i]:
            j = i
            while j < len(flags) and flags[j]: j += 1
            if j - i >= min_len: yield i, j
            i = j
        else: i += 1

def smooth(flags, gap):
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

hud = [0.55 < r['timer_dark'] < 0.85 and 0.1 < r['pts_white'] < 0.5 for r in rows]
ingame = smooth(hud, int(6 / DT))
matches = list(runs(ingame, int(60 / DT)))
print(f'{len(matches)} match segment(s):')
for mi, (a, b) in enumerate(matches):
    print(f'  match {mi+1}: {rows[a]["t"]:.1f}s -> {rows[b-1]["t"]:.1f}s  ({rows[b-1]["t"]-rows[a]["t"]:.0f}s)')

events = []
def add(mi, seg, i, j, **kw):
    events.append(dict(match=mi+1, t=round(seg[i]['t'], 2), rel=round(seg[i]['t']-seg[0]['t'], 1), dur=round((j-i)*DT, 1), **kw))

for mi, (a, b) in enumerate(matches):
    seg = rows[a:b]; vis = hud[a:b]
    for s in range(8):
        dead = []; prev = False
        for r, v in zip(seg, vis):
            if v: prev = r[f's{s}_dark'] > DARK_THR      # dark grey squid silhouette = dead icon
            dead.append(prev)
        dead = smooth(dead, int(GAP / DT))
        for i, j in runs(dead, int(MIN_DEAD / DT)):
            add(mi, seg, i, j, type='hud_death', slot=s, team='ally' if s < 4 else 'enemy')
    kf = smooth([v and r['kf_dark'] > 0.6 for r, v in zip(seg, vis)], int(0.5 / DT))
    for i, j in runs(kf, int(1.0 / DT)): add(mi, seg, i, j, type='killfeed')
    # own death: 'やられた!' pops at bottom centre right at the splat; 'ふっかつまであと' shows while dead
    bot = smooth([r['bot_yar'] > 0.5 for r in seg], int(1.0 / DT))
    for i, j in runs(bot, 1): add(mi, seg, i, j, type='own_death_text')
    rsp = smooth([r['rsp'] > 0.6 for r in seg], int(1.5 / DT))
    for i, j in runs(rsp, int(1.0 / DT)): add(mi, seg, i, j, type='respawn_wait')
    bub = smooth([r['bub_yar'] > 0.6 for r in seg], int(1.0 / DT))
    for i, j in runs(bub, 1): add(mi, seg, i, j, type='death_bubble')

events.sort(key=lambda e: e['t'])
json.dump(events, open(SRC.replace('.csv', '_events.json'), 'w'), ensure_ascii=False, indent=1)
for mi in range(len(matches)):
    ev = [e for e in events if e['match'] == mi+1]
    print(f'\n== match {mi+1} ==')
    gt = GT.get(mi+1); bad = 0
    for s in range(8):
        n = sum(1 for e in ev if e['type'] == 'hud_death' and e['slot'] == s)
        line = f'  slot{s} ({"ally" if s<4 else "enemy"}) deaths: {n}'
        if gt: line += f'   truth {gt[s]}' + ('' if gt[s] == n else '  <-- MISMATCH'); bad += gt[s] != n
        print(line)
    cnt = {k: sum(1 for e in ev if e['type'] == k) for k in ('killfeed', 'own_death_text', 'respawn_wait', 'death_bubble')}
    gs = GT_SELF.get(mi+1)
    print('  ' + '  '.join(f'{k}={v}' for k, v in cnt.items()) + (f'   truth: self deaths {gs[1]}, kills+assists {gs[2]}' if gs else ''))
    if gt: print(f'  slots matching truth: {8-bad}/8')
if '-v' in sys.argv:
    for e in events: print(f"  m{e['match']} {e['rel']:6.1f}s  {e['type']:15s} {e.get('slot','')}  dur={e['dur']}")
