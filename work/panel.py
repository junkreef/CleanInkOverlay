"""Own result panel (1080p): the screen after the team poses that the recorder detects as 表彰 (medals.looks_like_medals).

Left: own character. Right: the same banner as the scoreboard (mode / rule / stage, same position, so
result_parser.banner_signature reads it), own row (points + kills/assists, deaths, specials), "ゲットした表彰" with the
medal banners (medals.py), and the four gear cards (weapon first). It also shows when the scoreboard is skipped
(schedule change), so it gives the own row of such a match.

- points: white digits 33-34 px high at y 271-305, from x ~1335 (the scoreboard's are 27-28 px)
- stats: 'x' + 2 digits 20 px high at y 295-315, three groups (STAT_X); the scoreboard's 'small' glyphs read a 6 as 8
  here, so both have their own glyph sets ('panel_big', 'panel_small'), built from panels whose scoreboard row is known
- weapon: the weapon card's icon is drawn identically every time (gray 32x32 correlation >= 0.9999 over 200 panels,
  another weapon 0.57) but not like the wiki icons (masked NCC picked a wrong weapon on every panel). So it is learnt:
  the icon's colour thumbnail is a signature (signatures.Library, kind 'panel_weapon') labelled with the own weapon of
  the scoreboard whenever both are seen; a panel without a scoreboard looks its weapon up there.

    python work/panel.py FRAME.png [...]     # print what is read
    python work/panel.py --glyphs [DB]       # build the glyph sets from the stored panels + their scoreboard rows
"""
import cv2, json, numpy as np, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from result_parser import Glyphs, GLYPH_DIR, white_mask, glyph_boxes, merge_boxes, norm_glyph, banner_signature, BANNER_THR

ROOT = os.path.join(os.path.dirname(__file__), '..')
POINTS = (262, 312, 1300, 1480)          # y0, y1, x0, x1
STATS_Y = (290, 320)
STAT_X = [(1515, 1560), (1593, 1638), (1670, 1715)]   # the two digits of each group (the 'x' left of them stays out)
ICON = (805, 915, 885, 990)              # weapon card icon
ICON_SIG = (24, 24)
WEAPON_THR = 0.97                        # same weapon >= 0.9999
GLYPH_MIN = 0.6                          # lowest glyph score of a row that is believed (stored panels: >= 0.71)


def parts(f):
    """[(mask, boxes)] for the points and the three stat groups"""
    m = white_mask(f[POINTS[0]:POINTS[1], POINTS[2]:POINTS[3]]); out = [(m, merge_boxes(glyph_boxes(m, 25, 45)))]
    for x0, x1 in STAT_X:
        m2 = white_mask(f[STATS_Y[0]:STATS_Y[1], x0:x1]); out.append((m2, glyph_boxes(m2, 15, 25)))
    return out


def weapon_signature(f):
    y0, y1, x0, x1 = ICON
    return cv2.resize(f[y0:y1, x0:x1], ICON_SIG, interpolation=cv2.INTER_AREA).astype(np.float32).ravel() / 255


def to_int(s):
    try: return int(s)
    except (TypeError, ValueError): return None


def read_panel(f, glyphs, lib):
    """-> dict(points, kills_assists, deaths, specials, glyph_score, stage, mode, rule (+ *_id), weapon, weapon_sig).
    Numbers are None when unreadable; weapon is None until the library knows this icon (the signature is kept so the
    recorder can label it from the scoreboard). Nothing is added to the library here."""
    out = {}
    scores = []
    for key, (m, b), which in zip(('points', 'kills_assists', 'deaths', 'specials'), parts(f), ('panel_big',) + ('panel_small',) * 3):
        text, sc = glyphs.read(m, b, which); scores += sc
        out[key] = to_int(text.rstrip('p') if key == 'points' else text) if (key != 'points' or text.endswith('p')) else None
    out['glyph_score'] = min(scores or [0.0])
    if out['glyph_score'] < GLYPH_MIN:
        for key in ('points', 'kills_assists', 'deaths', 'specials'): out[key] = None
    for kind in ('stage', 'mode', 'rule'):
        sid, label, _ = lib.identify(banner_signature(f, kind), kind, add_unknown=False, thr=BANNER_THR)
        out[kind] = label; out[kind + '_id'] = sid
    sig = weapon_signature(f)
    _, out['weapon'], out['weapon_score'] = lib.identify(sig, 'panel_weapon', add_unknown=False, thr=WEAPON_THR)
    out['weapon_sig'] = sig
    return out


def learn_weapon(lib, sig, weapon):
    """label the panel's weapon icon with the scoreboard's own weapon -> True when the library changed"""
    if sig is None or not weapon: return False
    sid, label, _ = lib.identify(sig, 'panel_weapon', thr=WEAPON_THR)
    if label == weapon: return False
    lib.label(sid, weapon); return True


def build_glyphs(db=os.path.join(ROOT, 'data', 'splatoon.db')):
    """glyph sets from every stored panel whose match has the own scoreboard row (points / k+a / d / sp). Digits never
    seen on a panel yet (8 and 9 as stats) are taken from the scoreboard's sets: a rough stand-in until they show up"""
    import sqlite3
    rows = sqlite3.connect(db).execute('select m.medal_image, p.points, p.kills_assists, p.deaths, p.specials from matches m join match_players p '
                                       'on p.match_id = m.id and p.is_self = 1 where m.medal_image is not null').fetchall()
    acc = {'panel_big': {}, 'panel_small': {}}; n = 0
    for img, *gt in rows:
        p = os.path.join(ROOT, img)
        if None in gt or not os.path.exists(p): continue
        n += 1
        for i, ((m, b), text) in enumerate(zip(parts(cv2.imread(p)), (f'{gt[0]}p',) + tuple('%02d' % v for v in gt[1:]))):
            if len(b) != len(text): print('  skipped', img, text, len(b)); continue
            for box, ch in zip(b, text): acc['panel_big' if i == 0 else 'panel_small'].setdefault(ch, []).append(norm_glyph(m, box))
    base = Glyphs().sets
    for which, src in (('panel_big', 'big'), ('panel_small', 'small')):
        d = {k: np.mean(v, axis=0) for k, v in acc[which].items()}
        for ch, v in base[src].items():
            if ch.isdigit() and ch not in d: d[ch] = v; print(f'  {which}: {ch} from {src}')
        json.dump({k: v.tolist() for k, v in sorted(d.items())}, open(os.path.join(GLYPH_DIR, which + '.json'), 'w', encoding='utf-8'))
        print(which, {k: len(v) for k, v in sorted(acc[which].items())})
    print(n, 'panels')


if __name__ == '__main__':
    if sys.argv[1] == '--glyphs': build_glyphs(*sys.argv[2:]); sys.exit()
    from signatures import Library
    g, lib = Glyphs(), Library()
    for p in sys.argv[1:]:
        r = read_panel(cv2.imread(p), g, lib); r.pop('weapon_sig')
        print(os.path.basename(p), r)
