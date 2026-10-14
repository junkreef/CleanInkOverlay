"""Match recorder: rule screen -> in-match timeline -> 表彰 (medals) -> result screen -> SQLite.

    uv run python -m app.recorder --video 2026-09-12_14-13-43.mp4   # offline, ~10 fps sampling
    uv run python -m app.recorder --live                              # OBS Virtual Camera
    add --db data/test.db to write elsewhere, --dry to print without writing, --from/--to to cut a video
The engine (class Recorder) only sees frames and an app.store.Store: every DB write and file write goes through the store.

Every sampled frame (~10 fps) is first classified: which screen is it (rule / medals / result / hud / other)?
That runs regardless of state, so a screen is noticed whenever it appears; its content is analysed once,
when it has been stable for a few samples. The state only says what we are accumulating:
  IDLE        nothing; a rule screen starts a match, a result screen alone stores a match without timeline
  WAIT_HUD    rule screen seen; waiting for the HUD at 3:00 (slot icons kept) and the first 2:59 (t0)
  INGAME      timer, 8 slot states, own special gauge (state + fill level), own paint points (once per second),
              killfeed name, death bubble card, own-death texts
  WAIT_RESULT HUD gone; the medal screen and the result screen are picked up whenever they show up
A rule screen while INGAME / WAIT_RESULT means the previous match was aborted or its result was skipped.
"""
import argparse, json, os, sys, time, datetime, collections
import cv2, numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from result_parser import parse, Glyphs, RESULT_ROWS, NAME, WEAPON, crop as rcrop, white_mask
from signatures import signature, Library
from weapon_match import load_main_weapons, load_wiki_icons, icon_source, imread_u, score_icon, extra_parts, UNKNOWN_BELOW, VARIANT_PART
from weapon_icons import harvestable, lossless, group_name, panel_bg
from scan_screens import looks_like_rule
from live_result_watch import looks_like_result
from rule_screen import read_cards
from medals import looks_like_medals, parse_medals
import hud

ROOT = os.path.join(os.path.dirname(__file__), '..')
TPL_DIR = os.path.join(os.path.dirname(__file__), 'templates')
KF_X0, KF_X1 = 800, 1200          # killfeed text area (name + ' をたおした!')
KF_SUFFIX = 125                   # px from the text's right edge occupied by ' をたおした!'
KF_BANDS = [(998 - 66 * k, 1036 - 66 * k) for k in range(5)]   # text rows 1001-1029 of the newest message (bottom); older ones 66 px up each (2nd row verified); up to 4 kills + own death. Kept tight so the next band's edge never enters the crop
KF_DECIDE = 0.4                   # a new killfeed name is judged this long after it appeared (push-up animation takes ~0.2 s)
KF_RECENT = 0.6                   # a known message last seen within this many seconds before a candidate may be its changed look
BUBBLE_CARD = (690, 1010, 1040, 1920)
MIN_DEAD = 3.0; DEAD_THR = 0.25; GAP = 0.5
BUB_CAPTURE = 0.5                 # 'やられた!' template score that starts a bubble (background stays <= 0.22)
BUB_CARD_SCALES = (1.5,)          # bubble card = rule-screen card x1.5: of x1.4/1.5/1.6, 1.5 won on all 293 recorded bubble frames
BUB_CARD_K = 0.5                  # both sides matched at half size: ~14 ms per bubble frame (3 scales: 42 ms at half size, 175 ms at full size), scores within ~0.02 of full size (14 recorded bubbles)
BUB_KILLER = 0.5                  # best card score that names the killer (correct ~0.94, wrong <= 0.30)
BUB_EVIDENCE_BELOW = 1.01         # save the best card crop + frame of bubbles scoring below this (samples/bubbles/); every bubble for now, 0.8 once live positives are collected
RING_SECONDS = 15                 # small frames kept for evidence when an own death shows no bubble
STABLE = {'rule': 3, 'medals': 3, 'result': 10}


def tm(bgr, tpl):
    return float(cv2.matchTemplate(white_mask(bgr, 190) * 255, tpl, cv2.TM_CCOEFF_NORMED).max())


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


def card_templates(cards):
    """enemy rule-screen cards -> [(slot, [template per scale])] at the bubble matching size; None without cards"""
    if not cards: return None
    shrink = lambda img, k: cv2.resize(img, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
    return [(c['slot'], [shrink(shrink(c['card'], s), BUB_CARD_K) for s in BUB_CARD_SCALES]) for c in cards[4:]]


def card_scores(crop, tpl):
    """full-size BUBBLE_CARD crop -> [(score, slot)] best first"""
    small = cv2.resize(crop, None, fx=BUB_CARD_K, fy=BUB_CARD_K, interpolation=cv2.INTER_AREA)
    return sorted(((max(float(cv2.matchTemplate(small, t, cv2.TM_CCOEFF_NORMED).max()) for t in ts), slot) for slot, ts in tpl), reverse=True)


def classify(f):
    """which screen is this frame? checked in order of cost; None = anything else (lobby, intro, map...)"""
    if looks_like_rule(f): return 'rule'
    if looks_like_medals(f): return 'medals'
    if looks_like_result(f): return 'result'
    if hud.hud_visible(f): return 'hud'
    return None


class Recorder:
    def __init__(self, source, store, dry=False, log=print, debug=False):
        self.source, self.store, self.dry, self.log, self.debug = source, store, dry, log, debug
        self.load_icons()
        self.wiki_icons = load_wiki_icons() if icon_source() != 'captured' else {}   # aligns / trims new captured templates
        self.glyphs = Glyphs(); self.lib = store.signatures()
        self.tpl_yar = cv2.imread(os.path.join(TPL_DIR, 'yarareta.png'), 0)
        self.tpl_rsp = cv2.imread(os.path.join(TPL_DIR, 'respawn.png'), 0)
        self.state = 'IDLE'; self.m = None; self.t_state = 0.0; self.t_last_store = -1e9
        self.scr = None; self.n_scr = 0                       # current screen and how many samples it has lasted
        self.medals_pending = None                            # (t, medals, image) from the last 表彰 screen
        self.ring = collections.deque()                       # (t, 480x270 frame) for the last RING_SECONDS
        self.rsp_t = None; self.prev_rsp = 0.0

    def stamp(self, t):
        return datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S') if self.source == 'live' else f'{os.path.basename(self.source)}_{t:07.1f}'

    # ------------------------------------------------------------ per frame
    def process(self, f, t):
        scr = classify(f)
        self.n_scr = self.n_scr + 1 if scr == self.scr else 1; self.scr = scr
        if scr in STABLE and self.n_scr == STABLE[scr]:       # a screen has just become stable: analyse it once
            if scr == 'rule': self.on_rule(f, t)
            elif scr == 'medals': self.on_medals(f, t)
            elif scr == 'result': self.on_result(f, t)
        s = self.state
        if s == 'WAIT_HUD':
            if scr == 'hud':
                rem, clock, sc = hud.read_timer(f, self.glyphs)
                if rem == 180 and len(self.m['start_patches']) < 3 and (not self.m['start_patches'] or t - self.m['start_patches'][-1][0] >= 0.4):
                    self.m['start_patches'].append((t, [hud.slot_img(f, i, 28).copy() for i in range(8)]))
                if rem is not None and rem < 180:
                    self.m['t0'] = t - (180 - rem)                # rem is shown during [180-rem, 181-rem) after start
                    self.state = 'INGAME'; self.t_state = t; self.log(f'[{t:8.1f}] INGAME  (t0={self.m["t0"]:.1f})')
            elif t - self.t_state > 150:
                self.log(f'[{t:8.1f}] no HUD after rule screen, back to IDLE'); self.state = 'IDLE'; self.m = None
        elif s == 'INGAME':
            self.sample(f, t, scr == 'hud')
        elif s == 'WAIT_RESULT':
            if t - self.t_state > 300:
                self.log(f'[{t:8.1f}] no result screen, storing match without it'); self.finish(None, t)

    # ------------------------------------------------------------ screens
    def on_rule(self, f, t):
        if self.state == 'INGAME':
            self.log(f'[{t:8.1f}] rule screen during a match: previous match aborted, starting over')
        elif self.state == 'WAIT_RESULT':
            self.log(f'[{t:8.1f}] rule screen before the result: storing the previous match without it'); self.finish(None, t)
        self.start_match(f, t)

    def on_medals(self, f, t):
        meds = parse_medals(f, self.lib); self.store.save_libraries()
        path = self.store.save_image(self.stamp(t), 'medals', f)
        self.medals_pending = dict(t=t, medals=meds, image=path)
        self.log(f'[{t:8.1f}] MEDALS ' + (', '.join(f'{md["name"] or md["sig_id"]} ({md["rank"]} {md["score"]})' for md in meds) or 'none'))

    def on_result(self, f, t):
        if self.state in ('INGAME', 'WAIT_RESULT'):
            self.finish(f, t)
        elif self.state == 'IDLE' and t - self.t_last_store > 120:      # result without a rule screen (started mid-match)
            self.m = dict(t_rule=None, card_tpl=None, start_patches=[], samples=[], kf=[], bubbles=[], t0=t, notes='no rule screen')
            self.finish(f, t)

    def start_match(self, f, t):
        ts = self.stamp(t)
        path = self.store.save_image(ts, 'rule', f)
        self.m = dict(ts=ts, t_rule=t, rule_image=path, card_tpl=card_templates(read_cards(f)), start_patches=[], samples=[], kf=[], bubbles=[], t0=None, notes=None)
        self.state = 'WAIT_HUD'; self.t_state = t; self.ring.clear(); self.rsp_t = None
        self.log(f'[{t:8.1f}] RULE SCREEN -> waiting for HUD')

    # ------------------------------------------------------------ in match
    def sample(self, f, t, vis):
        m = self.m
        rem, clock, _ = hud.read_timer(f, self.glyphs) if vis else (None, None, 0)
        # a match can be aborted (connection error) and a new one started without a rule screen: timer back at 3:00
        if vis and rem == 180 and t - m['t0'] > 30:
            self.log(f'[{t:8.1f}] timer back at 3:00: previous match aborted, waiting for the new start (cards unknown)')
            self.m = dict(m, card_tpl=None, start_patches=[], samples=[], kf=[], bubbles=[], kf_cands=[], kf_rows=[], pts_sec=None, t0=None, notes='restarted without rule screen')
            self.state = 'WAIT_HUD'; self.t_state = t; return
        row = dict(t=t, vis=vis, rem=rem, clock=clock)
        if vis:
            row['slots'] = [hud.slot_state(f, i) for i in range(8)]
            row['g_or'], row['g_wh'] = hud.gauge_state(f); row['g_lv'] = hud.gauge_level(f)
            sec = int(t - m['t0'])                                    # paint points: first clean read of each second (~5 ms; rolling digits fail and retry next sample)
            if m.get('pts_sec') != sec:
                pts, _ = hud.read_points(f, self.glyphs)
                if pts is not None: row['pts'] = pts; m['pts_sec'] = sec
            self.killfeed(f, t)
        bub = hud.crop(f, hud.BUBBLE)
        row['bub'] = tm(bub, self.tpl_yar) if (bub.max(axis=2) < 60).mean() > 0.3 else 0.0
        if row['bub'] > BUB_CAPTURE:                                  # every sample of the bubble scores the killer card; the best one is kept
            if not m['bubbles'] or t - m['bubbles'][-1]['t'] > 6.0: m['bubbles'].append(dict(t=t, n=0, best=None, second=None))
            b = m['bubbles'][-1]; b['n'] += 1
            if m.get('card_tpl'):
                crop = hud.crop(f, BUBBLE_CARD); sc = card_scores(crop, m['card_tpl'])
                if b['best'] is None or sc[0][0] > b['best'][0]:
                    b['best'], b['second'] = sc[0], sc[1]
                    b['crop'] = crop.copy(); b['frame'] = cv2.resize(f, (crop.shape[0] * 16 // 9, crop.shape[0]), interpolation=cv2.INTER_AREA)   # evidence at crop height, grabbed now
        row['yar'] = tm(hud.crop(f, hud.BOTTOM), self.tpl_yar); row['rsp'] = tm(hud.crop(f, hud.RESPAWN), self.tpl_rsp)
        m['samples'].append(row)
        self.evidence(f, t, row['rsp'])
        elapsed = t - m['t0']
        last_vis = max((r['t'] for r in m['samples'] if r['vis']), default=t)
        if (rem == 0 and t - last_vis > 2) or (elapsed > 150 and t - last_vis > 8) or t - last_vis > 60:
            self.state = 'WAIT_RESULT'; self.t_state = t; self.log(f'[{t:8.1f}] match over (elapsed {elapsed:.0f}s) -> waiting for result')

    def evidence(self, f, t, rsp):
        """keep small frames; when the 'respawn in N s' text (own death) came and went without any bubble, save
        the frames around it so the miss can be examined later (samples/misses/)"""
        self.ring.append((t, cv2.resize(f, (480, 270), interpolation=cv2.INTER_AREA)))
        while self.ring and t - self.ring[0][0] > RING_SECONDS: self.ring.popleft()
        if rsp > 0.9 and self.prev_rsp <= 0.9 and (self.rsp_t is None or t - self.rsp_t > 6): self.rsp_t = t
        self.prev_rsp = rsp
        if self.rsp_t is not None and t - self.rsp_t > 8:
            t_r = self.rsp_t; self.rsp_t = None
            if not any(t_r - 4 <= b['t'] <= t_r + 8 for b in self.m['bubbles']):
                frames = [fr for tt, fr in self.ring if t_r - 5 <= tt <= t_r + 8][::5]       # every 0.5 s
                if frames:
                    while len(frames) % 6: frames.append(np.zeros_like(frames[0]))
                    sheet = np.vstack([np.hstack(frames[i:i + 6]) for i in range(0, len(frames), 6)])
                    p = self.store.save_evidence(f'{self.m.get("ts", "x")}_{t_r - self.m["t0"]:05.1f}s', sheet)
                    self.log(f'[{t:8.1f}] own death at {t_r - self.m["t0"]:.1f}s without a bubble: frames saved to {p}')

    def killfeed(self, f, t):
        """Read every killfeed row ('NAME をたおした!'): the newest message sits at the bottom, older ones are pushed
        up 66 px, and simultaneous kills appear as two rows at once. Each row's name signature either refreshes a kill
        already seen (same message still displayed) or becomes a candidate. A candidate is judged KF_DECIDE s after it
        appeared: if the number of message rows grew meanwhile it is a new kill (push-up or simultaneous rows);
        if not, it is a message that was displayed a moment ago with a changed look (a flash behind it) and merges."""
        m = self.m; kf = m['kf']; cands = m.setdefault('kf_cands', []); hist = m.setdefault('kf_rows', [])
        sigs = []
        for y0, y1 in KF_BANDS:
            band = f[y0:y1, KF_X0:KF_X1]
            if (band.max(axis=2) < 60).mean() < 0.6: continue
            if tm(band, self.tpl_yar) > 0.6: continue                   # own 'やられた!' can share the stack
            cols = np.where((band.min(axis=2) > 190).sum(axis=0) > 0)[0]
            if len(cols) < 10 or cols.max() - KF_SUFFIX < 20: continue
            sig = signature(band[:, :cols.max() - KF_SUFFIX])
            if sig is not None: sigs.append(sig)
        n_rows = len(sigs)
        for sig in sigs:                                                  # 1. known kills still on screen
            best = max(((float(np.corrcoef(sig, k['sig'])[0, 1]), i) for i, k in enumerate(kf) if t - k['t_last'] < 8.0), default=(-1, None))
            if best[0] > 0.8: kf[best[1]]['t_last'] = t; sig = None
            else:                                                         # 2. candidates already seen
                for c in cands:
                    if c['seen'][-1] < t and float(np.corrcoef(sig, c['sig'])[0, 1]) > 0.8: c['seen'].append(t); sig = None; break
            if sig is not None:                                           # 3. new candidate; rows before it appeared
                cands.append(dict(t=t, sig=sig, seen=[t], rows_before=hist[-1][1] if hist else 0, rows_max=n_rows))
        hist.append((t, n_rows)); del hist[:-10]
        for c in list(cands):
            c['rows_max'] = max(c['rows_max'], n_rows)
            if t - c['t'] < KF_DECIDE: continue
            cands.remove(c)
            if len(c['seen']) < 3 or t - c['seen'][-1] > 0.15: continue    # not stable, or already gone (text in transit while pushed up)
            if c['rows_max'] > c['rows_before']:
                kf.append(dict(t=c['t'], t_last=t, sig=c['sig']))
            else:
                old = [k for k in kf if 0 < c['t'] - k['t_last'] <= KF_RECENT or k['t_last'] >= c['t']]
                if old: k = max(old, key=lambda k: k['t_last']); k['sig'] = c['sig']; k['t_last'] = t
                else: kf.append(dict(t=c['t'], t_last=t, sig=c['sig']))

    def load_icons(self):
        # the unknown groups stay out of these sets: in the matcher a group made from one bad crop of a known weapon would
        # compete with that weapon's template and take its later rows; harvest_icons tries the groups after the matcher
        lib = self.store.weapon_icons(); d = lib.captured_dir
        self.icons = load_main_weapons(captured_dir=d)                # 56 px composites for the result screen
        self.icons_big = load_main_weapons(size=256, captured_dir=d)  # RGBA for HUD icon linking
        self.icons_version = lib.version

    def fit_group(self, c):
        """the unknown group a crop looks like (score >= UNKNOWN_BELOW and no part either lacks), else None"""
        lib = self.store.weapon_icons(); bg = panel_bg(c); best = None
        for gid in lib.groups():
            t = lib.templates[group_name(gid)]; sc = score_icon(c, t, bg)
            if sc >= UNKNOWN_BELOW and max(extra_parts(c, t)) < VARIANT_PART and (best is None or sc > best[0]): best = (sc, gid)
        return best and best[1]

    def harvest_icons(self, f, res, ts):
        """keep confidently matched result-row icons as samples of our own weapon templates (weapon_icons.py), so the
        wiki icons get replaced as weapons show up; an icon matching no weapon goes to the unknown group it fits, or a new
        one (row['weapon_unknown']), to be named on the web page. Live only: a recording's H.264 crops can pass `lossless`
        but are noisy enough to start groups of known weapons. Reloads the icon sets when a template changed."""
        if self.source != 'live': return
        lib = self.store.weapon_icons(); added = []; v = lib.version
        for row, y in zip(res['rows'], RESULT_ROWS.values()):
            stem = f'{ts}_{row["row"]}'
            if row['weapon']:
                if not (harvestable(row) and lib.wants(row['weapon'], stem)): continue
                c = rcrop(f, WEAPON, y)
                if not lossless(c): continue
                lib.add_sample(row['weapon'], c, stem, wiki=self.wiki_icons.get(row['weapon'])); added.append(row['weapon'])
            elif (row['weapon_score'] or 0) >= 0.6:                   # an icon, but none we know (score 0.6: not an empty row)
                c = rcrop(f, WEAPON, y)
                if not lossless(c): continue
                gid = self.fit_group(c)
                if gid: lib.add_sample(group_name(gid), c, stem)
                else: gid = lib.new_group(c, stem)
                row['weapon_unknown'] = gid; added.append(f'? {gid}')
        if added:
            self.store.save_libraries()
            if lib.version != v: self.load_icons()
            self.log(f'    weapon icon samples added: {", ".join(added)}')

    # ------------------------------------------------------------ end of match
    def finish(self, f, t):
        m = self.m; self.state = 'IDLE'
        res = None; result_image = None; ts = m.get('ts') or self.stamp(t)
        if f is not None:
            if self.store.weapon_icons().version != self.icons_version: self.load_icons()   # e.g. an icon named on the web
            res = parse(f, self.icons, self.glyphs, self.lib); self.store.save_libraries()
            if not result_sane(res):
                self.log(f'[{t:8.1f}] result screen did not parse sanely (self row / weapons / points) - discarded')
                if m.get('t0') is None or not m['samples']:            # nothing else to keep
                    self.m = None; return
                res = None; f = None
        m['ts'] = ts
        if f is not None:
            if not self.dry: self.harvest_icons(f, res, ts)
            result_image = self.store.save_image(ts, 'result', f)
            for row, y in zip(res['rows'], RESULT_ROWS.values()):
                row['name_sig'] = signature(rcrop(f, NAME, y))          # raw look of the name, matched against killfeed rows below (not stored, not identified)
        medals = []; medal_image = None
        if self.medals_pending and t - self.medals_pending['t'] < 120:
            medals = self.medals_pending['medals']; medal_image = self.medals_pending['image']; self.medals_pending = None
        match, players, events, timeline = self.build_record(res, t, result_image)
        match['medal_image'] = medal_image
        self.log(f'[{t:8.1f}] MATCH {match["result"]} {match["stage"]} {match["my_pct"]}-{match["enemy_pct"]}  players={len(players)} events={len(events)} medals={len(medals)}')
        for p in sorted(players, key=lambda p: p['slot']):
            self.log(f'    slot{p["slot"]} {p["team"]:5s}{"*" if p["is_self"] else " "} {str(p["weapon"]):20s} p={p["points"]} ka={p["kills_assists"]} d={p["deaths"]} sp={p["specials"]} link={p["link_score"]}')
        for e in events:
            self.log(f'    {e["t_ms"]/1000:6.1f}s {str(e["clock"]):5s} {e["type"]:9s} slot={e["slot"]} target={e["target_slot"]} ({e["source"]} {e["confidence"]})')
        for md in medals:
            self.log(f'    medal {md["position"]} {md["rank"]:6s} {md["name"] or md["sig_id"]}')
        self.bubble_evidence(ts)
        pts = [r for r in timeline if r['points'] is not None]
        self.log(f'    timeline {len(timeline)} s, points read in {len(pts)} s (last {pts[-1]["points"] if pts else None} at {pts[-1]["t_s"] if pts else None}s), gauge ready in {sum(r["ready"] for r in timeline)} s')
        me = next((p for p in players if p['is_self']), None)
        if me:
            n_sp = sum(1 for e in events if e['type'] == 'special'); n_rd = sum(1 for e in events if e['type'] == 'special_ready'); n_kb = sum(1 for e in events if e['type'] == 'killed_by')
            self.log(f'    self check: specials gauge {n_sp} (ready {n_rd}) / result {me["specials"]}, points HUD {pts[-1]["points"] if pts else None} / result {me["points"]}, killed_by bubbles {n_kb} / deaths {me["deaths"]}')
        if not self.dry:
            mid = self.store.insert_match(match, players, events, medals, timeline); self.log(f'    -> db match id {mid}')
        self.t_last_store = t
        self.store.save_json(ts, '', dict(match=match, players=players, events=events, medals=medals, timeline=timeline))
        if self.debug: self.store.save_json(ts, '_samples', m['samples'])
        self.m = None

    def bubble_evidence(self, ts):
        """log each bubble's best card score (and runner-up); below BUB_EVIDENCE_BELOW save the best crop next to the
        frame it came from (samples/bubbles/) so a low score can be examined later. Runs whether or not the result parsed."""
        m = self.m; t0 = m.get('t0') or 0.0
        for b in m['bubbles']:
            best, second = b['best'], b['second']
            self.log(f'    bubble {b["t"] - t0:6.1f}s frames={b["n"]} best={f"{best[0]:.2f} slot{best[1]}" if best else "-"} 2nd={f"{second[0]:.2f} slot{second[1]}" if second else "-"}')
            if best and best[0] < BUB_EVIDENCE_BELOW:
                p = self.store.save_bubble(f'{ts}_{b["t"] - t0:05.1f}s_card{best[0]:.2f}_2nd{second[0]:.2f}', np.hstack([b['crop'], b['frame']]))
                self.log(f'      -> {p}')

    def build_record(self, res, t_end, result_image):
        m = self.m; t0 = m['t0']
        # --- timeline from HUD samples
        S = m['samples']; dt = 0.1
        if len(S) > 1: dt = (S[-1]['t'] - S[0]['t']) / (len(S) - 1)
        death_runs = {s: [] for s in range(8)}
        for s in range(8):
            dead = []; pd = False
            for r in S:
                if r['vis']: pd = r['slots'][s]['dark'] > DEAD_THR
                dead.append(pd)
            death_runs[s] = list(runs(smooth(dead, int(GAP / dt)), int(MIN_DEAD / dt)))
        hud_deaths = {s: len(v) for s, v in death_runs.items()}
        # --- link HUD slots to result rows via weapon icons (+ death counts as tie-break)
        players = []; slot_row = {}; self_slot = None
        if res:
            rows = res['rows']; self_team = res['self_result'] or 'win'
            for r in rows: r['hteam'] = 'ally' if r['team'] == self_team else 'enemy'
            scores = {s: {} for s in range(8)}
            for _, patches in m['start_patches']:
                for s in range(8):
                    cands = {r['weapon'] for r in rows if r['hteam'] == ('ally' if s < 4 else 'enemy') and r['weapon']}
                    for w, v in hud.slot_weapon_scores_patch(patches[s], cands, self.icons_big).items():
                        scores[s][w] = max(scores[s].get(w, 0), v)
            slot_row = assign(scores, rows, hud_deaths)
            for s, ri in slot_row.items():
                r = rows[ri]
                players.append(dict(slot=s, team='ally' if s < 4 else 'enemy', is_self=int(r['self']),
                                    weapon=r['weapon'], weapon_score=r['weapon_score'], weapon_conf=r['weapon_conf'],
                                    points=to_int(r['points']), kills_assists=to_int(r['kills']), deaths=to_int(r['deaths']), specials=to_int(r['specials']),
                                    result_row=ri % 4, link_score=round(scores[s].get(r['weapon'], 0.0), 3) if m['start_patches'] else None))   # NULL = slot order is arbitrary (no match start seen)
                if r['self']: self_slot = s
        # --- events
        events = []
        def clock_at(t):
            best = min((r for r in S if r['clock']), key=lambda r: abs(r['t'] - t), default=None)
            return best['clock'] if best and abs(best['t'] - t) < 2 else None
        def ev(t, type_, slot=None, target=None, source='hud', conf=None, dur=None, weapon=None):
            events.append(dict(t_ms=int(round((t - t0) * 1000)), clock=clock_at(t), type=type_, slot=slot, target_slot=target, weapon=weapon, source=source, confidence=conf, duration_ms=int(dur * 1000) if dur else None))
        for s in range(8):
            for i, j in death_runs[s]: ev(S[i]['t'], 'death', slot=s, source='hud', conf=round(max(r['slots'][s]['dark'] for r in S[i:j] if r['vis']), 2), dur=(j - i) * dt)
        for t in hud.special_uses(S):                             # own specials from the gauge (other players: result count only)
            ev(t, 'special', slot=self_slot, source='gauge')
        for t in hud.special_ready(S):                            # own gauge became full (white ring)
            ev(t, 'special_ready', slot=self_slot, source='gauge')
        if res:
            for k in m['kf']:                                     # own kills: killfeed name -> result row -> slot
                best = max(((float(np.corrcoef(k['sig'], r['name_sig'])[0, 1]) if r['name_sig'] is not None else -1), ri) for ri, r in enumerate(rows))
                row_slot = {v: kk for kk, v in slot_row.items()}
                ev(k['t'], 'kill', slot=self_slot, target=row_slot.get(best[1]) if best[0] >= 0.5 else None, source='killfeed', conf=round(best[0], 2))
            for b in m['bubbles']:                                # own deaths with killer: bubble card -> rule card -> slot (best frame, scored in sample())
                best = b['best']
                ev(b['t'], 'killed_by', slot=self_slot, target=best[1] if best and best[0] > BUB_KILLER else None, source='bubble', conf=round(best[0], 2) if best else None)
        events.sort(key=lambda e: e['t_ms'])
        started = (datetime.datetime.now() - datetime.timedelta(seconds=t_end - t0)) if self.source == 'live' else video_time(self.source, t0)
        match = dict(started_at=started.isoformat(timespec='seconds'), ended_at=None, mode=res['mode'] if res else None, rule=res['rule'] if res else None,
                     stage=res['stage'] if res else None, result=res['self_result'] if res else None,
                     my_pct=pct(res, True), enemy_pct=pct(res, False), duration_s=round(max((r['t'] for r in S if r['vis']), default=t0) - t0, 1) if S else None,
                     source='live' if self.source == 'live' else os.path.basename(self.source), rule_image=m.get('rule_image'), result_image=result_image,
                     raw_json=json.dumps(strip(res), ensure_ascii=False) if res else None, notes=m.get('notes'))
        return match, players, events, timeline_rows(S, t0)


def timeline_rows(S, t0):
    """per second since the timer start, from HUD-visible samples: points = first clean read in that second (a read
    that breaks the non-decreasing count against both neighbours is dropped), gauge = median fill 0..1, ready = the
    ring was white in any sample. Seconds without a visible HUD (map open, transitions) get no row."""
    secs = {}
    for r in S:
        if not r['vis'] or 'g_lv' not in r: continue
        k = int(r['t'] - t0)
        if not 0 <= k <= 180: continue
        d = secs.setdefault(k, dict(lv=[], ready=False, pts=None))
        d['lv'].append(r['g_lv']); d['ready'] = d['ready'] or r['g_wh'] >= hud.READY_WHITE
        if d['pts'] is None and 'pts' in r: d['pts'] = r['pts']
    ks = [k for k in sorted(secs) if secs[k]['pts'] is not None]
    for i, k in enumerate(ks):                                    # single misreads: outside [previous, next] while previous <= next
        prev = secs[ks[i - 1]]['pts'] if i else 0; nxt = secs[ks[i + 1]]['pts'] if i + 1 < len(ks) else None
        v = secs[k]['pts']
        if v < prev or (nxt is not None and prev <= nxt < v): secs[k]['pts_bad'] = True
    return [dict(t_s=k, points=None if d.get('pts_bad') else d['pts'], gauge=round(float(np.median(d['lv'])), 3), ready=int(d['ready']))
            for k, d in sorted(secs.items())]


def result_sane(res):
    """a real result screen has a self row, weapon icons (mostly matching something, at least 3 known: a copy without many
    templates yet sees unknown weapons) and numeric points"""
    if not res or not any(r['self'] for r in res['rows']): return False
    if sum(1 for r in res['rows'] if (r['weapon_score'] or 0) >= 0.6) < 6 or sum(1 for r in res['rows'] if r['weapon']) < 3: return False
    return sum(1 for r in res['rows'] if to_int(r['points']) is not None) >= 6


def assign(scores, rows, hud_deaths, w_death=0.05):
    import itertools
    link = {}
    for team, slots in (('ally', range(0, 4)), ('enemy', range(4, 8))):
        ris = [i for i, r in enumerate(rows) if r['hteam'] == team]
        best = None
        for perm in itertools.permutations(ris):
            tot = 0.0
            for s, ri in zip(slots, perm):
                tot += scores[s].get(rows[ri]['weapon'], 0.0) - w_death * abs(hud_deaths.get(s, 0) - to_int(rows[ri]['deaths'], 0))
            if best is None or tot > best[0]: best = (tot, perm)
        for s, ri in zip(slots, best[1]): link[s] = ri
    return link


def to_int(s, default=None):
    try: return int(s)
    except (TypeError, ValueError): return default


def pct(res, mine):
    """the % bar is drawn from my team's point of view: left = my team, right = enemy, win or lose"""
    if not res: return None
    v = res.get('pct_left') if mine else res.get('pct_right')
    try: return float(str(v).rstrip('%'))
    except ValueError: return None


def strip(res):
    return {k: ([{kk: vv for kk, vv in r.items() if kk not in ('name_sig',)} for r in v] if k == 'rows' else v) for k, v in res.items()}


def video_time(path, t):
    """sample videos are named YYYY-MM-DD_HH-MM-SS(.mp4): start time + offset"""
    import re
    mo = re.search(r'(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})-(\d{2})', os.path.basename(path))
    if not mo: return datetime.datetime.fromtimestamp(os.path.getmtime(path))
    base = datetime.datetime.fromisoformat(f'{mo.group(1)}T{mo.group(2)}:{mo.group(3)}:{mo.group(4)}')
    return base + datetime.timedelta(seconds=t)


if __name__ == '__main__':                     # the CLI lives in app/recorder.py:  uv run python -m app.recorder --live
    sys.path.insert(0, ROOT)
    from app.recorder import main
    main()
