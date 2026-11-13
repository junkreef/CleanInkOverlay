"""Match recorder: rule screen -> in-match timeline -> 表彰 (medals) -> result screen -> SQLite.

    uv run python -m app.recorder --video 2026-09-12_14-13-43.mp4   # offline, ~10 fps sampling
    uv run python -m app.recorder --live                              # OBS Virtual Camera
    add --db data/test.db to write elsewhere, --dry to print without writing, --from/--to to cut a video
The engine (class Recorder) only sees frames and an app.store.Store: every DB write and file write goes through the store.

Every sampled frame (~10 fps) is first classified: which screen is it (rule / medals / result / hud / other)?
That runs regardless of state, so a screen is noticed whenever it appears; its content is analysed once,
when it has been stable for a few samples. The state only says what we are accumulating:
  IDLE        nothing; a rule screen starts a match (its rule name, a 'title' signature, picks the analysis below),
              a result screen alone stores a match without timeline
  WAIT_HUD    rule screen seen; waiting for the HUD at its start (3:00 for ナワバリ; slot icons kept) and the first
              second after it (t0)
  INGAME      timer, 8 slot states, own special gauge (state + fill level), own paint points (once per second),
              killfeed name, death bubble card, own-death texts
  WAIT_RESULT HUD gone; the judge screen (paint % + WIN!/LOSE...), the medal screen and the result screen are picked up
              whenever they show up. Without a result screen (schedule change: the game goes straight back to the
              lobby) the match keeps the judge screen's win / lose and paint %, and the own row + stage from the
              own result panel (the 表彰 screen, work/panel.py). So it is stored when no scoreboard came AFTER_SCREENS_WAIT
              after the judge / 表彰 screen went (RESULT_WAIT after the HUD without them)
A rule screen while INGAME / WAIT_RESULT means the previous match was aborted or its result was skipped.
A past match played in the replay viewer (メモリープレイヤー, its mark top left: work/replay.py) is not recorded at all
(watch_replay).

Rules: the rule name on the rule screen decides (RULE_ANALYSIS); without one (not named yet in the Web UI, or no rule
screen seen) the timer at the start does: 3:00 = ナワバリ, more = another rule. ナワバリ runs exactly as before.
Any other rule ('nonturf': the ガチ rules, a new イベントマッチ rule) is a match of the length its timer starts at,
whose HUD has no paint points: its HUD is told by the timer box (hud.timer_hud), it can go into overtime (「延長中!」,
up to +5 min) and its % is never stored (these rules show counts / ノックアウト! where ナワバリ has the % bar). Kills,
deaths and specials come from the same squids / killfeed / bubbles / gauge as in ナワバリ. ガチヤグラ / ガチホコ also
read the objective's track once per second (work/objective.py: position, who holds it, each team's best), ガチエリア /
ガチアサリ both counts, the penalties and who holds the zones / attacks (work/area.py).
"""
import argparse, json, os, sys, time, datetime, collections, math
import cv2, numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from result_parser import parse, read_banners, Glyphs, RESULT_ROWS, NAME, WEAPON, crop as rcrop, white_mask, dark_share
from signatures import signature, Library
from weapon_match import load_main_weapons, load_wiki_icons, icon_source, imread_u, fit_group
from weapon_icons import harvestable, lossless, group_name, HARVEST_MIN_SCORE
from scan_screens import looks_like_rule
from live_result_watch import looks_like_result
from rule_screen import read_cards, title_signature
import objective, area
from rule_miss import MissWatch
from medals import looks_like_medals, parse_medals
from judge import read_label, read_judge
from schedule import looks_like_schedule_update
from counts import read_judge_counts, read_scoreboard_counts
from panel import read_panel, learn_weapon
from replay import replay_mark
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
RING_STEP = 0.5                   # s between them (the miss sheet shows one every 0.5 s; shrinking every sample took 1.6 ms of it)
STABLE = {'rule': 3, 'medals': 3, 'result': 10, 'schedule': 3}   # 'schedule': the notice shows ~0.9 s
# 表彰 / result screen: analysed on a still sample, and when the screen goes before its STABLE count (a player pressing
# つづける! on the scoreboard), its last still sample is analysed then. The panels slide in and out in ~0.1 s, and a moving
# frame can pass the check yet read wrongly (2026-11-10_00-38-55: the 10th sample was the scoreboard 27 px off, leaving
# after ~1 s, and the screen was discarded). Still = the panel box differs from the previous sample by at most STILL_MAX
# (mean abs, every 4th px). Measured 2026-11-13 on 2026-10-11_22-14-08 / 2026-11-04_22-59-07: a settled screen <= 0.65 one
# sample apart (H.264 noise; 0.0x frame to frame), the slide >= 2.5 up to its last moving frame; 1 px off is 5.4
STILL_BOX = (300, 1000, 800, 1850)   # y0, y1, x0, x1: the scoreboard's rows and the 表彰 panel, not the animated character left of them
STILL_MAX = 1.0
SETTLE = ('medals', 'result')
JUDGE_LABEL_MIN = 0.9             # label score that counts as a win / lose vote (the real labels score >= 0.98)
COUNT_FIELDS = ('my_count', 'enemy_count', 'knockout', 'my_team_points', 'enemy_team_points')   # ガチルール: matches columns from work/counts.py
JUDGE_GAP = 30.0                  # s: judge frames further apart than this belong to different matches
RESULT_WAIT = 300.0               # s: a match ends without its result screen when nothing came for this long after the end of its HUD (ガチルール: or its judge screen); a schedule change says so at once (on_schedule)
AFTER_SCREENS_WAIT = 60.0         # s: ... or this long after the last sample of its judge / 表彰 screen, when one was seen (the scoreboard
                                  # skipped, e.g. つづける! pressed on the おカネ / ランク screen; log2 of 2026-11-13 waited the full 300 s).
                                  # The scoreboard comes 7.1-12.2 s after the 表彰 screen went (8 recorded matches, ナワバリ and ガチ;
                                  # the 表彰 screen itself shows 2.5-2.9 s) and at most ~29 s after it appeared (291 live ナワバリ
                                  # matches since 2026-10-20: 表彰 saved -> scoreboard stored 9.1-29.5 s)
TITLE_THR = 0.8                   # rule-name signature: the same name >= 0.91 (269 stored ナワバリ screens), ガチホコバトル vs ナワバリバトル 0.63
RULE_ANALYSIS = {'ナワバリバトル': 'turf', 'ガチヤグラ': 'track', 'ガチホコバトル': 'track', 'ガチエリア': 'zones', 'ガチアサリ': 'zones'}   # other names: 'other'
OVERTIME_MAX = 300                # s: overtime lasts at most 5 minutes
RULE_CARDS_AT = 1.0               # s after the rule screen appeared: the player cards fade in one by one and are all there
                                  # from ~0.5 s (correlation with their final look ~0 at 0.2 s, >= 0.90 at 0.5 s, >= 0.89-0.99 at 1 s,
                                  # 11 rule screens; the screen lasts 2.0-6.5 s). Taken at 0.2 s, the killer cards scored 0.4 instead of 0.8
MAP_AFTER = 0.2                   # s after the map (top left ×) was last seen: closing, the × goes first and the timer reads again while the gauge
                                  # is still see-through over the blurred ink (all 7 false special frames of 53 own deaths were within 0.05 s of the map)
OBJ_MIN_SHARE = 0.3               # an unnamed rule keeps its track / area reads when they cover this share of its HUD seconds (track on ガチエリア: 0)
END_GRACE = 15.0                  # s without HUD after 0:00 / overtime before a non-ナワバリ match counts as over (a splat in overtime shows the map ~10 s)
REPLAY_CONFIRM = 3                # samples in a row with the replay viewer's mark (work/replay.py) that make it a replay (logged once)
REPLAY_HOLD = 30.0                # s after the mark was last confirmed during which IDLE / WAIT_RESULT still ignore every screen: the mark is
                                  # gone from the judge screen and the team pose that close a playback (~15 s, 2026-04-08_00-24-01.mp4 207.8-222.8 s)


def tm(bgr, tpl):
    m = white_mask(bgr, 190)
    if not cv2.countNonZero(m): return 0.0                  # what TM_CCOEFF_NORMED gives on a flat image anyway, without the 0.6 ms
    return float(cv2.matchTemplate(m * 255, tpl, cv2.TM_CCOEFF_NORMED).max())


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


CHECK = {'rule': lambda f: looks_like_rule(f), 'medals': lambda f: looks_like_medals(f), 'result': lambda f: looks_like_result(f),
         'judge': lambda f: read_label(f)[0] is not None, 'schedule': lambda f: looks_like_schedule_update(f), 'map': lambda f: hud.map_open(f), 'hud': lambda f: hud.hud_visible(f)}
ALL_SCREENS = ('rule', 'medals', 'result', 'judge', 'schedule', 'map', 'hud')   # checked in this order: the first that matches wins
# the screens each state acts on (NOTES「レコーダーの状態と画面の判定」, docs/recorder_states.svg); the others are not checked
# there. The HUD stays last: it also passes on a few 表彰 / result / rule screens (14 of ~900 saved ones)
SCREENS = {
    'IDLE': ('rule', 'medals', 'result', 'judge'),                      # rule: a match starts; result (+ its judge / 表彰): the recorder started mid-match
    'WAIT_HUD': ('rule', 'hud'),                                         # hud: the timer starts; rule: another rule screen starts over
    'INGAME': ('rule', 'medals', 'result', 'judge', 'schedule', 'map', 'hud'),  # judge: a ガチ match is over (ノックアウト); the screens after it in case the end of the HUD was missed; map: the HUD is behind it
    'WAIT_RESULT': ('rule', 'medals', 'result', 'judge', 'schedule'),    # whatever comes after the match; no HUD
}


def classify(f, screens=ALL_SCREENS):
    """which screen is this frame, of `screens`? None = anything else (lobby, intro, map...)"""
    return next((s for s in screens if CHECK[s](f)), None)


class Recorder:
    def __init__(self, source, store, dry=False, log=print, debug=False):
        self.source, self.store, self.dry, self.log, self.debug = source, store, dry, log, debug
        self.load_icons()
        self.wiki_icons = load_wiki_icons() if icon_source() != 'captured' else {}   # aligns / trims new captured templates
        self.glyphs = Glyphs(); self.lib = store.signatures()
        self.tpl_yar = imread_u(os.path.join(TPL_DIR, 'yarareta.png'), 0)
        self.tpl_rsp = imread_u(os.path.join(TPL_DIR, 'respawn.png'), 0)
        self.state = 'IDLE'; self.m = None; self.t_state = 0.0; self.t_last_store = -1e9
        self.scr = None; self.n_scr = 0; self.t_scr = 0.0     # current screen, how many samples it has lasted, since when
        self.scr_box = None; self.still = None; self.scr_done = False   # 表彰 / result screen: its last sample's STILL_BOX, its last still (t, frame), analysed yet
        self.t_after = None                                   # last sample of a judge / 表彰 screen (AFTER_SCREENS_WAIT)
        self.t_gave_up = None                                 # when a match was last stored without its scoreboard by a time limit
        self.t_map = -1e9                                     # when the map was last seen
        self.medals_pending = None                            # (t, medals, image) from the last 表彰 screen
        self.ring = collections.deque()                       # (t, 480x270 frame) every RING_STEP for the last RING_SECONDS
        self.rsp_t = None; self.prev_rsp = 0.0
        self.judge = []                                       # reads of the last judge screen: dict(t, result, label_score, my_pct, enemy_pct)
        self.judge_frame = None                               # (t, frame) of its first read with both %, kept as evidence
        self.miss = MissWatch(store, log, self.stamp, self.glyphs)   # IDLE only: evidence of a battle whose rule screen was missed (work/rule_miss.py)
        self.n_mark = 0; self.t_replay = -1e9                 # replay viewer: samples in a row with its mark, when it was last confirmed

    def stamp(self, t):
        return datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S') if self.source == 'live' else f'{os.path.basename(self.source)}_{t:07.1f}'

    # ------------------------------------------------------------ per frame
    def watch_replay(self, f, t):
        """the replay viewer (メモリープレイヤー) plays a past match with all its screens: nothing of it is recorded.
        A frame with its mark is skipped whatever the state (a match in progress loses one sample to a false one; live
        matches score <= 0.38, THR 0.6). REPLAY_CONFIRM samples in a row make it a replay: then IDLE / WAIT_RESULT also
        skip the frames of the next REPLAY_HOLD s (its judge screen and team pose carry no mark), and WAIT_HUD / INGAME
        look at the HUD only. No state is changed: a match waiting for its result is stored by RESULT_WAIT as usual.
        -> True when this frame is skipped"""
        mark = replay_mark(f)
        self.n_mark = self.n_mark + 1 if mark else 0
        if self.n_mark >= REPLAY_CONFIRM:
            if t - self.t_replay > REPLAY_HOLD:
                self.log(f'[{t:8.1f}] replay viewer (メモリープレイヤー) on screen: ignoring the match it plays ({self.state})')
            self.t_replay = t
        if not (mark or self.state in ('IDLE', 'WAIT_RESULT') and t - self.t_replay <= REPLAY_HOLD): return False
        if self.scr in SETTLE: self.screen_gone(self.scr)       # a scoreboard / panel being counted: what it showed is not lost
        self.scr = 'replay'; self.n_scr = 0
        if self.state == 'WAIT_RESULT' and t - self.t_state > RESULT_WAIT:
            self.log(f'[{t:8.1f}] no result screen, storing match without it'); self.t_gave_up = t; self.finish(None, t)
        return True

    def process(self, f, t):
        if self.watch_replay(f, t): return
        screens = SCREENS[self.state]
        if t - self.t_replay <= REPLAY_HOLD: screens = tuple(s for s in screens if s in ('map', 'hud'))   # WAIT_HUD / INGAME just after a replay
        scr = classify(f, screens)
        if scr is None and self.m and self.state in ('WAIT_HUD', 'INGAME') and self.m.get('analysis') != 'turf':
            vis, rem, _ = hud.timer_hud(f, self.glyphs)       # no paint points top right: the timer box tells the HUD
            if vis and self.state == 'INGAME' and self.m.get('nonturf') and rem is not None and abs(rem - (self.m['dur'] - (t - self.m['t0']))) > 3:
                vis = False                                   # a time that does not fit the match: the map or a jump over the box
            if vis and (self.m.get('nonturf') or self.m.get('analysis') or self.state == 'WAIT_HUD' and rem is not None and rem > 180): scr = 'hud'
        if scr == 'map': self.t_map = t
        elif scr == 'hud' and t - self.t_map <= MAP_AFTER: scr = None   # the map closing: the HUD only half back
        if scr == 'judge' and self.state == 'INGAME' and self.m.get('nonturf'):
            self.state = 'WAIT_RESULT'; self.t_state = t; self.log(f'[{t:8.1f}] judge screen: match over (elapsed {t - self.m["t0"]:.0f}s) -> waiting for result')   # ノックアウト: before the time is up
        if scr != self.scr and self.scr in SETTLE: self.screen_gone(self.scr)
        self.n_scr = self.n_scr + 1 if scr == self.scr else 1; self.scr = scr
        if self.n_scr == 1: self.t_scr = t                     # when this screen appeared
        if scr in SETTLE: self.settle(scr, f, t)
        elif scr in STABLE and self.n_scr == STABLE[scr]:     # a screen has just become stable: analyse it once
            if scr == 'rule': self.on_rule(f, t)
            elif scr == 'schedule': self.on_schedule(t)
        if scr in ('judge', 'medals'): self.t_after = t
        if scr == 'judge': self.on_judge(f, t)
        if scr == 'rule' and self.state == 'WAIT_HUD' and not self.m.get('cards_at') and t - self.m['t_rule0'] >= RULE_CARDS_AT - 1e-6:
            self.retake_cards(f, t)
        if self.state == 'IDLE': self.miss.idle(f, t, scr)             # diagnostics only: never starts or stores a match
        elif self.miss.t0 is not None: self.miss.reset()
        s = self.state
        if s == 'WAIT_HUD':
            if scr == 'hud':
                rem, clock, sc = hud.read_timer(f, self.glyphs)
                if rem is not None and (self.m.get('nonturf') or rem > 180 or self.m.get('analysis') not in (None, 'turf')):
                    self.start_nonturf(f, t, rem, clock)          # not ナワバリ (by its name, or its timer above 3:00)
                    return
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
            after = self.t_after if self.t_after is not None and self.t_after >= self.t_state else None   # this match's judge / 表彰 screen
            if t - self.t_state > RESULT_WAIT:
                self.log(f'[{t:8.1f}] no result screen, storing match without it'); self.t_gave_up = t; self.finish(None, t)
            elif after is not None and t - after > AFTER_SCREENS_WAIT and scr != 'result':   # not while a scoreboard is being counted
                self.log(f'[{t:8.1f}] no result screen {t - after:.0f}s after the judge / 表彰 screen, storing match without it')
                self.t_gave_up = t; self.finish(None, t)

    def settle(self, scr, f, t):
        """a sample of the 表彰 / result screen: analysed once, at its STABLE-th sample if that one is still (as before),
        else at the last still one (the screen leaving: a moving frame reads wrongly), else as it is"""
        box = f[STILL_BOX[0]:STILL_BOX[1]:4, STILL_BOX[2]:STILL_BOX[3]:4].astype(np.int16)
        if self.n_scr == 1: self.still = None; self.scr_done = False
        still = self.n_scr > 1 and float(np.abs(box - self.scr_box).mean()) <= STILL_MAX
        self.scr_box = box
        if self.scr_done: return
        if still: self.still = (t, f.copy())
        if self.n_scr >= STABLE[scr]:
            self.scr_done = True
            if not still and self.still: self.log(f'[{t:8.1f}] {scr} screen moving at its {self.n_scr}th sample: taking its still sample at {self.still[0]:.1f}')
            self.analyse(scr, *((t, f) if still or not self.still else self.still))

    def screen_gone(self, scr):
        """the 表彰 / result screen went before its STABLE count: what it really showed is its last still sample (two
        samples 0.1 s apart that do not differ). The scoreboard only for a match being recorded: in IDLE a short one
        would be a match of its own without a timeline"""
        if not self.scr_done and self.still and (scr == 'medals' or self.state in ('INGAME', 'WAIT_RESULT')):
            t0 = self.still[0]
            self.log(f'[{t0:8.1f}] {scr} screen gone after {self.n_scr} samples, before {STABLE[scr]}: taking its last still sample')
            self.analyse(scr, *self.still)
        self.still = None; self.scr_done = True

    def analyse(self, scr, t, f):
        if scr == 'medals': self.on_medals(f, t)
        else: self.on_result(f, t)

    # ------------------------------------------------------------ screens
    def on_rule(self, f, t):
        if self.state == 'INGAME':
            self.log(f'[{t:8.1f}] rule screen during a match: previous match aborted, starting over')
        elif self.state == 'WAIT_RESULT':
            self.log(f'[{t:8.1f}] rule screen before the result: storing the previous match without it'); self.finish(None, t)
        self.start_match(f, t)

    def on_schedule(self, t):
        """「スケジュールが更新されました」: the scoreboard is skipped, so the match is stored now with its judge screen
        and panel (otherwise only the next rule screen or RESULT_WAIT would store it, and stopping the recorder before
        that lost it)"""
        if self.state in ('INGAME', 'WAIT_RESULT'):
            self.log(f'[{t:8.1f}] schedule changed: no result screen will come, storing the match without it'); self.finish(None, t)

    def on_medals(self, f, t):
        meds = parse_medals(f, self.lib); self.store.save_libraries()
        path = self.store.save_image(self.stamp(t), 'medals', f)
        pn = read_panel(f, self.glyphs, self.lib)                 # the same screen's own row: kept for a match whose scoreboard is skipped
        self.medals_pending = dict(t=t, medals=meds, image=path, panel=pn)
        self.log(f'[{t:8.1f}] MEDALS ' + (', '.join(f'{md["name"] or md["sig_id"]} ({md["rank"]} {md["score"]})' for md in meds) or 'none'))
        self.log(f'    panel: {pn["weapon"]} p={pn["points"]} ka={pn["kills_assists"]} d={pn["deaths"]} sp={pn["specials"]} (glyphs {pn["glyph_score"]:.2f}) {pn["stage"]}')

    def on_judge(self, f, t):
        """every judge-screen frame votes: the label for win / lose, and the % when both sides read cleanly (a squid
        or a sticker flying over a digit makes a side unreadable on some frames), or per side the count / ノックアウト!
        and the team points (ガチルール, work/counts.py). Decided in judge_summary."""
        if self.judge and t - self.judge[-1]['t'] > JUDGE_GAP: self.judge = []; self.judge_frame = None
        res, lsc = read_label(f); j = read_judge(f, self.glyphs) or {}
        c = read_judge_counts(f, self.glyphs) if not j else None
        self.judge.append(dict(t=t, result=res, label_score=lsc, my_pct=j.get('my_pct'), enemy_pct=j.get('enemy_pct'), counts=c))
        if (j or c and c['my']['count'] is not None and c['enemy']['count'] is not None) and self.judge_frame is None: self.judge_frame = (t, f.copy())

    def judge_summary(self):
        """-> dict(t, result, my_pct, enemy_pct, votes, pct_votes, + the COUNT_FIELDS) from the judge reads, or None.
        % = the pair read most often, a side's count (with its ノックアウト!) and its points = the value read most often;
        each kept when at least 2 frames agree. result = the label most often seen"""
        J = self.judge
        labels = collections.Counter(r['result'] for r in J if r['result'] and r['label_score'] >= JUDGE_LABEL_MIN)
        if not labels: return None
        result, votes = labels.most_common(1)[0]
        pairs = collections.Counter((r['my_pct'], r['enemy_pct']) for r in J if r['my_pct'] is not None)
        (my, en), pv = pairs.most_common(1)[0] if pairs else ((None, None), 0)
        if pv < 2: my = en = None
        def voted(side, keys):
            c = collections.Counter(tuple(r['counts'][side][k] for k in keys) for r in J if r['counts'] and r['counts'][side][keys[0]] is not None)
            v, n = c.most_common(1)[0] if c else (None, 0)
            return v if n >= 2 else (None,) * len(keys)
        side = {s: (*voted(s, ('count', 'ko')), *voted(s, ('points',))) for s in ('my', 'enemy')}
        counts = count_fields({'left': dict(count=side['my'][0], ko=side['my'][1]), 'right': dict(count=side['enemy'][0], ko=side['enemy'][1])},
                              side['my'][2], side['enemy'][2])
        return dict(t=J[0]['t'], result=result, my_pct=my, enemy_pct=en, votes=f'{votes}/{len(J)}', pct_votes=f'{pv}/{sum(pairs.values())}', **counts)

    def belongs(self, t_screen, t):
        """a judge / medal screen seen at t_screen is this match's when it came after its rule screen (or, without one,
        at most 400 s before the end); a skipped result screen can leave it minutes before the match is stored"""
        t_rule = self.m.get('t_rule') if self.m else None
        return t_screen > t_rule if t_rule is not None else t - t_screen < 400

    def on_result(self, f, t):
        if self.state in ('INGAME', 'WAIT_RESULT'):
            self.finish(f, t)
        elif self.state == 'IDLE' and self.t_gave_up is not None and self.t_gave_up == self.t_last_store and t - self.t_gave_up <= RESULT_WAIT:
            # the scoreboard of the match just stored without it after all (no rule screen since): not a match of its own.
            # Logged so a too short AFTER_SCREENS_WAIT shows up
            self.log(f'[{t:8.1f}] result screen {t - self.t_gave_up:.0f}s after the match was stored without it: not stored again')
        elif self.state == 'IDLE' and t - self.t_last_store > 120:      # result without a timeline: the recorder started mid-match
            self.m = dict(t_rule=None, card_tpl=None, start_patches=[], samples=[], kf=[], bubbles=[], t0=t, notes='no rule screen')
            self.finish(f, t)

    def start_nonturf(self, f, t, rem, clock):
        """WAIT_HUD of a rule other than ナワバリ: its length is where its timer starts (5:00 for the ガチ rules; a few reads
        so one misread does not count), slot icons at that time, t0 at the first second after it"""
        m = self.m
        if not m.get('nonturf'):
            m['n_long'] = m.get('n_long', 0) + 1
            if m['n_long'] < 3: return
            if m.get('analysis') == 'turf': self.log(f'[{t:8.1f}] rule name says ナワバリバトル but the timer starts at {clock}: going by the timer')
            m.update(nonturf=True, dur=300 if m.get('analysis') in ('track', 'zones') else 60 * math.ceil(rem / 60))   # an unknown rule: its first read, to the minute
            if m['analysis'] in (None, 'turf'): m['analysis'] = None   # unnamed: the track is looked for each second
            self.log(f'[{t:8.1f}] timer at {clock}: {m.get("title") or "not ナワバリ"}, a {m["dur"] // 60}:00 match')
        dur = m['dur']
        if rem == dur and len(m['start_patches']) < 3 and (not m['start_patches'] or t - m['start_patches'][-1][0] >= 0.4):
            m['start_patches'].append((t, [hud.slot_img(f, i, 28).copy() for i in range(8)]))
        if rem < dur:
            m['t0'] = t - (dur - rem)                             # rem is shown during [dur-rem, dur+1-rem) after start
            self.state = 'INGAME'; self.t_state = t; self.log(f'[{t:8.1f}] INGAME  (t0={m["t0"]:.1f})')

    def start_match(self, f, t):
        ts = self.stamp(t)
        path = self.store.save_image(ts, 'rule', f)
        tid, title, sc = self.lib.identify(title_signature(f), 'title', thr=TITLE_THR); self.store.save_libraries()
        analysis = None if title is None else RULE_ANALYSIS.get(title, 'other')
        self.m = dict(ts=ts, t_rule=t, t_rule0=self.t_scr, rule_image=path, card_tpl=card_templates(read_cards(f)), start_patches=[], samples=[], kf=[], bubbles=[], t0=None, notes=None,
                      title_id=tid, title=title, analysis=analysis)
        self.state = 'WAIT_HUD'; self.t_state = t; self.ring.clear(); self.rsp_t = None; self.t_gave_up = None
        self.log(f'[{t:8.1f}] RULE SCREEN {title or tid or "(no rule name)"} ({analysis or "rule unknown: the timer decides"}) -> waiting for HUD')

    def retake_cards(self, f, t):
        """the cards (and the saved rule screen) again once they have all faded in: start_match took them ~0.2 s into the
        screen, when the lower ones are still missing or see-through"""
        m = self.m; m['card_tpl'] = card_templates(read_cards(f)); m['cards_at'] = t
        m['rule_image'] = self.store.save_image(m['ts'], 'rule', f)
        self.log(f'[{t:8.1f}] player cards taken {t - m["t_rule0"]:.1f}s into the rule screen')

    # ------------------------------------------------------------ in match
    def sample(self, f, t, vis):
        m = self.m
        rem, clock, _ = hud.read_timer(f, self.glyphs) if vis else (None, None, 0)
        dur = m.get('dur', 180)
        # a match can be aborted (connection error) and a new one started without a rule screen: timer back at the start
        if vis and rem == dur and t - m['t0'] > 30:
            self.log(f'[{t:8.1f}] timer back at {dur // 60}:00: previous match aborted, waiting for the new start (cards unknown)')
            self.m = dict(m, card_tpl=None, start_patches=[], samples=[], kf=[], bubbles=[], kf_cands=[], kf_rows=[], pts_sec=None, obj_sec=None, last_vis=None, t0=None, notes='restarted without rule screen')
            self.state = 'WAIT_HUD'; self.t_state = t; return
        row = dict(t=t, vis=vis, rem=rem, clock=clock)
        if vis:
            row['slots'] = hud.slot_states(f)
            row['g_or'], row['g_wh'] = hud.gauge_state(f); row['g_lv'] = hud.gauge_level(f)
            sec = int(t - m['t0'])                                    # paint points: first clean read of each second (~5 ms; rolling digits fail and retry next sample)
            if not m.get('nonturf') and m.get('pts_sec') != sec:
                pts, _ = hud.read_points(f, self.glyphs)
                if pts is not None: row['pts'] = pts; m['pts_sec'] = sec
            if m.get('nonturf'):
                if rem is None and hud.overtime(f): row['ot'] = True; m['past_zero'] = True
                if rem == 0: m['past_zero'] = True
                if m.get('obj_sec') != sec:                       # once per second: the ヤグラ / ホコ track, or the エリア counts
                    an = m.get('analysis')                        # (the next sample of the second tries again until the icon /
                    if an == 'track' or an is None and objective.present(f):          # both counts are read)
                        row['obj'] = objective.read(f)
                        if row['obj']['pos'] is not None: m['obj_sec'] = sec
                    elif an == 'zones' or an is None and area.present(f, self.glyphs):
                        row['zone'] = area.read(f, self.glyphs)
                        if filled(row['zone'])[0] == 2: m['obj_sec'] = sec
            self.killfeed(f, t)
        bub = hud.crop(f, hud.BUBBLE)
        row['bub'] = tm(bub, self.tpl_yar) if dark_share(bub, 60) > 0.3 else 0.0
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
        if vis: m['last_vis'] = t
        self.evidence(f, t, row['rsp'])
        elapsed = t - m['t0']
        last_vis = t if m.get('last_vis') is None else m['last_vis']   # the last sample with the HUD (none yet: now)
        if not m.get('nonturf'): over = (rem == 0 and t - last_vis > 2) or (elapsed > 150 and t - last_vis > 8)
        else: over = t - last_vis > (END_GRACE if m.get('past_zero') else 8) and elapsed > dur - 30   # overtime may follow 0:00
        if over or t - last_vis > 60:
            self.state = 'WAIT_RESULT'; self.t_state = t; self.log(f'[{t:8.1f}] match over (elapsed {elapsed:.0f}s) -> waiting for result')

    def evidence(self, f, t, rsp):
        """keep small frames; when the 'respawn in N s' text (own death) came and went without any bubble, save
        the frames around it so the miss can be examined later (samples/misses/)"""
        if not self.ring or t - self.ring[-1][0] >= RING_STEP - 0.05: self.ring.append((t, cv2.resize(f, (480, 270), interpolation=cv2.INTER_AREA)))
        while self.ring and t - self.ring[0][0] > RING_SECONDS: self.ring.popleft()
        if rsp > 0.9 and self.prev_rsp <= 0.9 and (self.rsp_t is None or t - self.rsp_t > 6): self.rsp_t = t
        self.prev_rsp = rsp
        if self.rsp_t is not None and t - self.rsp_t > 8:
            t_r = self.rsp_t; self.rsp_t = None
            if not any(t_r - 4 <= b['t'] <= t_r + 8 for b in self.m['bubbles']):
                frames = [fr for tt, fr in self.ring if t_r - 5 <= tt <= t_r + 8]             # every 0.5 s
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
            if dark_share(band, 60) < 0.6: continue
            if tm(band, self.tpl_yar) > 0.6: continue                   # own 'やられた!' can share the stack
            cols = np.where(white_mask(band, 190).sum(axis=0) > 0)[0]
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
        lib = self.store.weapon_icons(); d = lib.template_dirs
        self.icons = load_main_weapons(captured_dir=d)                # 56 px composites for the result screen
        self.icons_big = load_main_weapons(size=256, captured_dir=d)  # RGBA for HUD icon linking
        self.icons_version = lib.version

    def harvest_icons(self, f, res, ts):
        """keep confidently matched result-row icons as samples of our own weapon templates (weapon_icons.py), so the
        wiki icons get replaced as weapons show up; an icon matching no weapon goes to the unknown group it fits, or a new
        one (row['weapon_unknown']), to be named on the web page. So does an icon only a wiki icon names, with too little
        confidence to be a sample (ホットブラスター艶 0.926, ソイチューバー 0.93): it waits in a group with the wiki's name as
        the guess, else such a weapon would never get a template. Live only: a recording's H.264 crops can pass `lossless`
        but are noisy enough to start groups of known weapons. Reloads the icon sets when a template changed."""
        if self.source != 'live': return
        lib = self.store.weapon_icons(); added = []; v = lib.version
        for row, y in zip(res['rows'], RESULT_ROWS.values()):
            stem = f'{ts}_{row["row"]}'
            guess = row['weapon'] if (row['weapon'] and row['weapon'] not in self.icons.captured
                                      and (row['weapon_score'] or 0) < HARVEST_MIN_SCORE) else None   # a wiki name to confirm
            if row['weapon'] and not guess:
                if not (harvestable(row) and lib.wants(row['weapon'], stem)): continue
                c = rcrop(f, WEAPON, y)
                if not lossless(c): continue
                lib.add_sample(row['weapon'], c, stem, wiki=self.wiki_icons.get(row['weapon'])); added.append(row['weapon'])
            elif guess or (row['weapon_score'] or 0) >= 0.6:          # an icon, but none we know (score 0.6: not an empty row)
                c = rcrop(f, WEAPON, y)
                if not lossless(c): continue
                gid = fit_group(c, lib)
                if gid:
                    lib.add_sample(group_name(gid), c, stem)
                    if guess and not lib.guess(gid): lib.guesses[gid] = guess; lib.dirty.add(group_name(gid))
                else: gid = lib.new_group(c, stem, guess)
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
            # unknown banner texts are added only once the screen is sane: a frame of the panel still sliding in passes
            # looks_like_result but its banner bands cut through two lines (2026-11-10_00-38-55 left two such signatures)
            res = parse(f, self.icons, self.glyphs, self.lib, add_unknown=False)
            if not result_sane(res):
                self.log(f'[{t:8.1f}] result screen did not parse sanely (self row / weapons / points) - discarded')
                if not m.get('nonturf') and (m.get('t0') is None or not m['samples']):   # nothing else to keep (other rules: the judge / panel may be)
                    self.m = None; return
                res = None; f = None
            else:
                for k, v in read_banners(f, self.lib).items():                # only fills what parse left unread: the new texts
                    if res.get(k) is None: res[k] = v
                self.store.save_libraries()
                res['counts'] = read_scoreboard_counts(f, self.glyphs)   # ガチルール; all None on a ナワバリ scoreboard
        m['ts'] = ts
        if f is not None:
            if not self.dry: self.harvest_icons(f, res, ts)
            result_image = self.store.save_image(ts, 'result', f)
            for row, y in zip(res['rows'], RESULT_ROWS.values()):
                row['name_sig'] = signature(rcrop(f, NAME, y))          # raw look of the name, matched against killfeed rows below (not stored, not identified)
        medals = []; medal_image = None; panel = None
        if self.medals_pending and self.belongs(self.medals_pending['t'], t):
            medals = self.medals_pending['medals']; medal_image = self.medals_pending['image']; panel = self.medals_pending['panel']
        self.medals_pending = None
        judge = self.judge_summary() if self.judge and self.belongs(self.judge[0]['t'], t) else None
        judge_frame = self.judge_frame; self.judge = []; self.judge_frame = None
        if m.get('nonturf') and not res and not judge and not panel:
            self.log(f'[{t:8.1f}] no judge screen, result panel or result screen: match not stored'); self.m = None; return
        match, players, events, timeline = self.build_record(res, t, result_image, None if res else panel)
        match['medal_image'] = medal_image
        if judge: self.use_judge(match, judge, judge_frame, ts)
        if panel and res: self.check_panel(panel, res)
        elif panel and players:
            match['notes'] = '; '.join(x for x in (match['notes'], 'own row and stage from the result panel') if x)
        counts = f' counts {"/".join(str(match[k]) for k in COUNT_FIELDS)}' if any(match[k] is not None for k in COUNT_FIELDS) else ''
        self.log(f'[{t:8.1f}] MATCH {match["result"]} {match["stage"]} {match["my_pct"]}-{match["enemy_pct"]}{counts}  players={len(players)} events={len(events)} medals={len(medals)}')
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
        self.store.save_json(ts, '', dict(match=match, players=players, events=events, medals=medals, timeline=timeline, judge=judge,
                                          panel={k: v for k, v in panel.items() if k != 'weapon_sig'} if panel else None))
        if self.debug: self.store.save_json(ts, '_samples', m['samples'])
        self.m = None

    def check_panel(self, panel, res):
        """with the scoreboard: compare the panel's own row with it (log) and teach the library the panel's weapon icon"""
        me = next((r for r in res['rows'] if r['self']), None)
        if not me: return
        want = (me['weapon'], *(to_int(me[k]) for k in ('points', 'kills', 'deaths', 'specials')), res['stage'], res['mode'], res['rule'])
        got = (panel['weapon'] or me['weapon'], *(panel[k] for k in ('points', 'kills_assists', 'deaths', 'specials')), panel['stage'], panel['mode'], panel['rule'])
        self.log('    panel check: ' + ('same as the result screen' if got == want else f'MISMATCH, panel {got} / result {want}'))
        if me['weapon'] and (me['weapon_score'] or 0) >= HARVEST_MIN_SCORE and learn_weapon(self.lib, panel['weapon_sig'], me['weapon']):
            self.store.save_libraries(); self.log(f'    panel weapon icon learnt: {me["weapon"]}')

    def use_judge(self, match, judge, frame, ts):
        """without a result screen the judge screen gives win / lose and the % (or the counts); with one, the two are
        compared (log), a count the scoreboard did not read is taken from the judge, and a disagreement keeps the judge
        frame for a look"""
        keys = ('result', 'my_pct', 'enemy_pct') + COUNT_FIELDS
        got = tuple(judge[k] for k in keys)
        self.log(f'    judge screen: {got[0]} {got[1]}-{got[2]} counts {"/".join(map(str, got[3:]))} (label votes {judge["votes"]}, % votes {judge["pct_votes"]})')
        if match['result'] is None:
            match.update({k: judge[k] for k in keys})
            what = 'counts' if judge['my_count'] is not None or judge['enemy_count'] is not None else '%'
            match['notes'] = '; '.join(x for x in (match['notes'], f'no result screen: result and {what} from the judge screen') if x)
            if frame: self.store.save_image(ts, 'judge', frame[1])
            return
        filled = [k for k in COUNT_FIELDS if match[k] is None and judge[k] is not None]
        match.update({k: judge[k] for k in filled})
        if filled: self.log(f'    from the judge screen (not read on the result screen): {", ".join(filled)}')
        if got[:3] != tuple(match[k] for k in keys[:3]) or any(judge[k] is not None and judge[k] != match[k] for k in COUNT_FIELDS):
            self.log(f'    judge check: MISMATCH, result screen says {match["result"]} {match["my_pct"]}-{match["enemy_pct"]} counts {"/".join(str(match[k]) for k in COUNT_FIELDS)}')
            if frame: self.log(f'      -> {self.store.save_image(ts, "judge", frame[1])}')
        else:
            self.log('    judge check: same as the result screen')

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

    def build_record(self, res, t_end, result_image, panel=None):
        """panel (only without a scoreboard): the own row from the result panel; its slot is found by the panel's
        weapon among the ally HUD icons at 3:00, so it needs a learnt weapon icon and the match start"""
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
        elif panel and panel['weapon'] and (m['start_patches'] or m.get('nonturf')):
            self_slot = 0; link = None                            # no HUD seen at the start: the slot order is arbitrary (as without a match start above)
            if m['start_patches']:
                scores = {s: max(hud.slot_weapon_scores_patch(p[s], {panel['weapon']}, self.icons_big).get(panel['weapon'], 0.0) for _, p in m['start_patches'])
                          for s in range(4)}
                self_slot = max(scores, key=lambda s: scores[s] - 0.05 * abs(hud_deaths.get(s, 0) - (panel['deaths'] or 0)))   # death counts break ties, as in assign()
                link = round(scores[self_slot], 3)
            players.append(dict(slot=self_slot, team='ally', is_self=1, weapon=panel['weapon'], weapon_score=None, weapon_conf=None,
                                points=panel['points'], kills_assists=panel['kills_assists'], deaths=panel['deaths'], specials=panel['specials'],
                                result_row=None, link_score=link))
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
        elif self_slot is not None:                               # own row from the result panel: kills without their target
            for k in m['kf']: ev(k['t'], 'kill', slot=self_slot, source='killfeed')
        if res or self_slot is not None:
            for b in m['bubbles']:                                # own deaths with killer: bubble card -> rule card -> slot (best frame, scored in sample())
                best = b['best']
                ev(b['t'], 'killed_by', slot=self_slot, target=best[1] if best and best[0] > BUB_KILLER else None, source='bubble', conf=round(best[0], 2) if best else None)
        events.sort(key=lambda e: e['t_ms'])
        started = (datetime.datetime.now() - datetime.timedelta(seconds=t_end - t0)) if self.source == 'live' else video_time(self.source, t0)
        banner = res or panel or {}                               # mode / rule / stage: the scoreboard's banner, else the panel's (same banner)
        cf = dict.fromkeys(COUNT_FIELDS)                          # ガチルール: count / ノックアウト! (header, left = my team) and the WIN! / LOSE... rows' points
        if res and res.get('counts'):
            c = res['counts']; mine, theirs = ('win_points', 'lose_points') if res['self_result'] != 'lose' else ('lose_points', 'win_points')
            cf = count_fields(c, c[mine], c[theirs])
        rule = banner.get('rule') or m.get('title')                # the scoreboard's banner, else the rule screen's name
        # only ナワバリ has the % bar; the others show counts / ノックアウト! there. A count read on the scoreboard says so too:
        # with no rule screen and a rule name nobody had named yet, the count bar was stored as a % (first Xマッチ, 2026-11-12: 99 - 55 as 999.0 - 559.0)
        turf = not m.get('nonturf') and rule in (None, 'ナワバリバトル') and cf['my_count'] is None and cf['enemy_count'] is None
        raw = strip(res) if res else dict(panel={k: v for k, v in panel.items() if k != 'weapon_sig'}) if panel else None
        if m.get('title_id'): raw = dict(raw or {}, title_id=m['title_id'])   # lets a later name of the rule screen fill rule
        match = dict(started_at=started.isoformat(timespec='seconds'), ended_at=None, mode=banner.get('mode'), rule=rule,
                     stage=banner.get('stage'), result=res['self_result'] if res else None,
                     my_pct=pct(res, True) if turf else None, enemy_pct=pct(res, False) if turf else None, duration_s=round(max((r['t'] for r in S if r['vis']), default=t0) - t0, 1) if S else None,
                     source='live' if self.source == 'live' else os.path.basename(self.source), rule_image=m.get('rule_image'), result_image=result_image,
                     raw_json=json.dumps(raw, ensure_ascii=False) if raw else None,   # the *_id let a later label fill stage / mode / rule
                     notes=m.get('notes'), **cf)
        secs = {int(r['t'] - t0) for r in S if r['vis']}
        keep = {k for k, an in (('obj', 'track'), ('zone', 'zones'))          # a rule not named yet: the track / area seen most of the match
                if m.get('analysis') == an or sum(k in r for r in S) >= OBJ_MIN_SHARE * len(secs)}
        return match, players, events, timeline_rows(S, t0, m.get('dur', 180) + (OVERTIME_MAX if m.get('nonturf') else 0), keep)


def timeline_rows(S, t0, max_s=180, keep=('obj', 'zone')):
    """per second since the timer start, from HUD-visible samples: points = first clean read in that second (a read
    that breaks the non-decreasing count against both neighbours is dropped), gauge = median fill 0..1, ready = the
    ring was white in any sample; ヤグラ / ホコ: the track's read of that second (obj_pos, obj_holder) and each team's
    best (best_series); ガチエリア: both counts (best_series: they only grow), whose box is lit (obj_holder) and both
    penalties (penalty_series);
    overtime = 「延長中!」 in any sample. Seconds without a visible HUD (map open, transitions) get no row."""
    secs = {}
    for r in S:
        if not r['vis'] or 'g_lv' not in r: continue
        k = int(r['t'] - t0)
        if not 0 <= k <= max_s: continue
        d = secs.setdefault(k, dict(lv=[], ready=False, pts=None, obj=None, zone=None, ot=False))
        d['lv'].append(r['g_lv']); d['ready'] = d['ready'] or r['g_wh'] >= hud.READY_WHITE
        if d['pts'] is None and 'pts' in r: d['pts'] = r['pts']
        for key in keep:                                          # the sample of the second that read the most (a named rule
            if key in r and (d[key] is None or filled(r[key]) > filled(d[key])): d[key] = r[key]   # reads every sample)
        d['ot'] = d['ot'] or r.get('ot', False)
    ks = [k for k in sorted(secs) if secs[k]['pts'] is not None]
    for i, k in enumerate(ks):                                    # single misreads: outside [previous, next] while previous <= next
        prev = secs[ks[i - 1]]['pts'] if i else 0; nxt = secs[ks[i + 1]]['pts'] if i + 1 < len(ks) else None
        v = secs[k]['pts']
        if v < prev or (nxt is not None and prev <= nxt < v): secs[k]['pts_bad'] = True
    ks = sorted(secs)
    best = {key: best_series([secs[k][src][key] if secs[k][src] else None for k in ks])
            for src, key in (('obj', 'my_best'), ('obj', 'enemy_best'), ('zone', 'my_count'), ('zone', 'enemy_count'))}
    pen = {key: penalty_series([secs[k]['zone'].get(key) if secs[k]['zone'] else None for k in ks],
                               [secs[k]['zone'] is not None and secs[k]['zone'][count] is not None for k in ks])
           for key, count in (('my_penalty', 'my_count'), ('enemy_penalty', 'enemy_count'))}
    holder = lambda d: d['obj']['holder'] if d['obj'] else d['zone']['holder'] if d['zone'] else None
    return [dict(t_s=k, points=None if d.get('pts_bad') else d['pts'], gauge=round(float(np.median(d['lv'])), 3), ready=int(d['ready']),
                 obj_pos=d['obj']['pos'] if d['obj'] else None, obj_holder=holder(d), my_best=best['my_best'][i], enemy_best=best['enemy_best'][i],
                 my_count=None if best['my_count'][i] is None else int(best['my_count'][i]),
                 enemy_count=None if best['enemy_count'][i] is None else int(best['enemy_count'][i]),
                 my_penalty=pen['my_penalty'][i], enemy_penalty=pen['enemy_penalty'][i], overtime=int(d['ot']))
            for i, (k, d) in enumerate((k, secs[k]) for k in ks)]


def filled(read):
    """how good a track / area read is: the icon position / both counts read first, then anything else read"""
    return (sum(read.get(k) is not None for k in ('pos', 'my_count', 'enemy_count')), sum(v is not None for v in read.values()))


def best_series(vals, win=3):
    """a team's best on the track can only grow: the median of the last `win` reads (one misread - something over a dot -
    does not count; a real step shows a second later), then the running maximum. None where nothing was read (yet)"""
    have = [i for i, v in enumerate(vals) if v is not None]
    out = [None] * len(vals); top = None
    for n, i in enumerate(have):
        m = float(np.median([vals[j] for j in have[max(0, n - win + 1):n + 1]])); top = m if top is None else max(top, m)
        out[i] = round(top, 1)
    return out


def penalty_series(vals, counted, gap=3):
    """a team's ガチエリア penalty per second from the 「+N」 reads: up to `gap` unread seconds before the next read keep
    the last value (something over the pill); longer, or with no read after, it is 0 (no pill: nothing to pay) where that
    team's count was read, else None. Then the median with both neighbours drops a single misread"""
    n = len(vals); out = list(vals); last = None; i = 0
    while i < n:
        if vals[i] is not None: last = vals[i]; i += 1; continue
        j = i
        while j < n and vals[j] is None: j += 1
        for k in range(i, j):
            out[k] = last if last is not None and j < n and j - i <= gap else 0 if counted[k] else None
        i = j
    sm = list(out)
    for i in range(n):
        w = [out[k] for k in (i - 1, i, i + 1) if 0 <= k < n and out[k] is not None]
        if out[i] is not None and len(w) == 3: sm[i] = int(np.median(w))
    return sm


def count_fields(c, my_points, enemy_points):
    """matches columns from both sides' counts (c['left'] = my team, c['right'] = the enemy, dict(count, ko) each):
    knockout 1 when a side shows ノックアウト!, 0 when both show a count, None when unknown"""
    l, r = c['left'], c['right']
    ko = 1 if l['ko'] or r['ko'] else 0 if l['count'] is not None and r['count'] is not None else None
    return dict(my_count=l['count'], enemy_count=r['count'], knockout=ko, my_team_points=my_points, enemy_team_points=enemy_points)


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
