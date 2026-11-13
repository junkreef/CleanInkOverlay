"""Diagnostics of a missed rule screen (work/rule_miss.py): a battle that starts while the recorder is IDLE leaves one log
line and its frames; a normal start, a recorder started mid-match, the HUD back after the map leave nothing. Never a match.
    uv run pytest tests/test_rule_miss.py
"""
import os, sys
import cv2, numpy as np
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if os.path.join(ROOT, 'work') not in sys.path: sys.path.insert(0, os.path.join(ROOT, 'work'))
import recorder as R, rule_miss as M, hud
from scan_screens import looks_like_rule, rule_checks
from signatures import Library
from weapon_icons import IconLibrary

frame = lambda name: cv2.imread(os.path.join(ROOT, 'work', 'frames', name))
RULE = frame('0041_match_start_rule.png'); LOBBY = frame('0004_lobby_matchinfo.png'); HUD = frame('0060_ingame_early.png')
INTRO = frame('0048_match_intro_players.png')


def without_ids(f, n=3):
    """the rule screen with the '#nnnn' of n cards gone: the tag and description pass, the cards do not (5 of 8)"""
    f = f.copy()
    for t in (285, 435, 585)[:n]: f[t + 118:t + 142, 22:85] = 40
    return f


class Store:
    def __init__(self):
        self.sig = Library(os.path.join(ROOT, 'assets', 'signatures.json'))
        self.icons = IconLibrary(os.path.join(ROOT, 'assets', 'weapon_icons_captured'), os.path.join(ROOT, 'data', 'icon_samples'))
        self.images = []; self.evidence = []; self.inserted = []
    def signatures(self): return self.sig
    def weapon_icons(self): return self.icons
    def save_libraries(self): pass
    def save_image(self, stamp, kind, f): self.images.append((stamp, kind, f.shape)); return f'{stamp}_{kind}.png'
    def save_bubble(self, name, sheet): return name
    def save_evidence(self, name, sheet): self.evidence.append((name, sheet.shape)); return name + '.jpg'
    def save_json(self, stamp, name, obj): pass
    def insert_match(self, *a): self.inserted.append(a); return 1


def feed(rec, timeline, phase, step=0.1):
    """timeline: [(t_from, t_to, frame or fn(t))]; samples at phase/60 + k*step (coarse 0.5 s steps where nothing happens)"""
    t = phase / 60
    for t0, t1, fr in timeline:
        dt = 0.5 if fr is LOBBY else step
        while t < t1:
            if t >= t0: rec.process(fr(t) if callable(fr) else fr, t)
            t += dt


def recorder(monkeypatch, read):
    """read(t) -> what the timer says at t: (rem, clock) or None (unreadable)"""
    store = Store(); lines = []
    rec = R.Recorder('2026-10-28_22-51-57.mp4', store, dry=True, log=lines.append)
    clock = {'t': 0.0}
    orig = rec.process
    def process(f, t): clock['t'] = t; orig(f, t)
    rec.process = process
    def fake(f, glyphs):
        r = read(clock['t']) if f is HUD else None
        return (r[0], r[1], 1.0) if r else (None, None, 0.0)
    monkeypatch.setattr(M.hud, 'read_timer', fake)
    return rec, store, lines


def start_at(t_go, dur=180):
    """the timer of a battle shown from t_go: at its start value for 3 s, then counting down"""
    return lambda t: (dur - max(0, int(t - t_go - 3)), f'{(dur - max(0, int(t - t_go - 3))) // 60}:{(dur - max(0, int(t - t_go - 3))) % 60:02d}')


def test_rule_checks_say_what_looks_like_rule_says():
    for f in (RULE, LOBBY, HUD, INTRO, frame('gachi_rule_area.png'), frame('fest_rule.png'), without_ids(RULE)):
        c = rule_checks(f)
        assert (c['tag'] and c['desc'] and c['ids']) == looks_like_rule(f)
    c = rule_checks(without_ids(RULE))
    assert c['tag'] and c['desc'] and not c['ids'] and sum(x >= 100 for x in c['id_contrast']) == 5


def test_a_battle_started_in_idle_leaves_evidence_at_every_phase(monkeypatch):
    """lobby, a rule screen that fails one check (cards), the intro, then the HUD at 3:00 from 60 s: one log line and the
    frames, within 0.2 s of the HUD at each of the 6 sampling phases; no match is started or stored"""
    for phase in range(6):
        rec, store, lines = recorder(monkeypatch, start_at(60.0))
        feed(rec, [(0, 45, LOBBY), (45, 50, without_ids(RULE)), (50, 60, INTRO), (60, 70, HUD)], phase)
        miss = [l for l in lines if 'RULE SCREEN MISSED' in l]
        assert len(miss) == 1, (phase, lines)
        t = float(miss[0][1:9])
        assert 60.0 < t <= 60.0 + 0.2 + 1e-6, (phase, t)                  # the second read of 3:00
        assert 'at 3:00' in miss[0] and 'failed: ids' in miss[0] and 'frame 1920x1080' in miss[0], miss[0]
        assert 'closest' in miss[0] and 'ids 5/8' in miss[0], miss[0]
        (name, shape), = store.evidence
        assert name.endswith('_rule_missed') and shape[1] == 1920 and shape[0] % 180 == 0 and shape[0] >= 1800   # >= 60 tiles of 320x180, 6 across
        kinds = [k for _, k, _ in store.images]
        assert kinds[0] == 'hud' and kinds[1].startswith('closest-1') and len(kinds) == 2, kinds   # the rule screen ~10-15 s before
        assert all(shape == (1080, 1920, 3) for _, _, shape in store.images)
        assert rec.state == 'IDLE' and rec.m is None and not store.inserted


def test_a_timer_box_that_reads_only_later_at_every_phase(monkeypatch):
    """the intro shows the dark timer box for a few s before the digits read (2026-10-29_22-02-57 at 422-427 s: the first
    version of the watcher had given up reading by then and missed that start)"""
    go = start_at(68.0, 300)
    for phase in range(6):
        rec, store, lines = recorder(monkeypatch, lambda t: go(t) if t >= 68.0 else None)
        feed(rec, [(0, 60, LOBBY), (60, 72, HUD)], phase)
        miss = [l for l in lines if 'MISSED' in l]
        assert len(miss) == 1 and 68.0 < float(miss[0][1:9]) <= 68.0 + M.SLOW_READ + 0.1 + 1e-6, (phase, miss)


def test_a_5_minute_rule_too(monkeypatch):
    rec, store, lines = recorder(monkeypatch, start_at(60.0, 300))
    feed(rec, [(0, 60, LOBBY), (60, 65, HUD)], 3)
    assert sum('RULE SCREEN MISSED' in l and 'at 5:00' in l for l in lines) == 1
    assert len(store.images) == 1                                          # no rule check passed in the lobby: no closest frame


def test_a_normal_start_leaves_nothing_at_every_phase(monkeypatch):
    for phase in range(6):
        rec, store, lines = recorder(monkeypatch, start_at(60.0))
        feed(rec, [(0, 45, LOBBY), (45, 50, RULE), (50, 60, INTRO), (60, 62.5, HUD)], phase)
        assert rec.state == 'WAIT_HUD' and not any('MISSED' in l for l in lines), (phase, lines)
        assert not store.evidence and [k for _, k, _ in store.images] == ['rule', 'rule'], phase   # the rule screen, taken twice (cards)


def test_no_evidence_when_the_battle_did_not_just_start(monkeypatch):
    # the recorder started mid-match: the first timer read is mid-match
    rec, store, lines = recorder(monkeypatch, lambda t: (120 - int(t), f'{(120 - int(t)) // 60}:{(120 - int(t)) % 60:02d}'))
    feed(rec, [(0, 40, HUD)], 0)
    assert not any('MISSED' in l for l in lines)
    # the recorder started a few s before the timer: its rule screen may have come before the recorder did
    rec, store, lines = recorder(monkeypatch, start_at(10.0))
    feed(rec, [(0, 10, LOBBY), (10, 20, HUD)], 0)
    assert not any('MISSED' in l for l in lines)
    # the timer box with digits that do not read (the result screen has a dark box there too): nothing
    rec, store, lines = recorder(monkeypatch, lambda t: None)
    feed(rec, [(0, 40, LOBBY), (40, 60, HUD)], 0)
    assert not any('MISSED' in l for l in lines) and not store.evidence and not store.images


def test_the_hud_back_after_the_map_is_no_new_battle(monkeypatch):
    """a battle missed at 60 s, then the map hides the timer for 20 s mid-match: one diagnostic, not two"""
    rec, store, lines = recorder(monkeypatch, start_at(60.0))
    feed(rec, [(0, 60, LOBBY), (60, 90, HUD), (90, 110, frame('0082_map_open.png')), (110, 120, HUD)], 2)
    assert sum('MISSED' in l for l in lines) == 1


def test_saves_are_limited(monkeypatch):
    """a missed battle every ~4 min for an hour (someone else's gameplay on the capture, or a PC that never sees the rule
    screen): a log line each time, frames at most MAX_SAVES times and never within SAVE_GAP s"""
    starts = [60.0 + 240 * i for i in range(15)]
    def read(t):
        go = max((s for s in starts if s <= t), default=None)
        return start_at(go)(t) if go is not None and t - go < 6 else None
    rec, store, lines = recorder(monkeypatch, read)
    hud_until = lambda t: HUD if any(s <= t < s + 6 for s in starts) else LOBBY
    t = 0.0
    while t < starts[-1] + 10:
        f = hud_until(t); rec.process(f, t); t += 0.1 if f is HUD else 1.0
    miss = [l for l in lines if 'MISSED' in l]
    assert len(miss) == len(starts)
    saved = [l for l in miss if 'not saved' not in l]
    assert len(saved) == M.MAX_SAVES and len(store.evidence) == M.MAX_SAVES
    ts = [float(l[1:9]) for l in saved]
    assert all(b - a >= M.SAVE_GAP for a, b in zip(ts, ts[1:]))


def test_an_error_in_the_diagnostics_does_not_stop_the_recorder(monkeypatch):
    rec, store, lines = recorder(monkeypatch, start_at(60.0))
    def full(*a): raise OSError('disk full')
    store.save_evidence = full
    feed(rec, [(0, 60, LOBBY), (60, 62, HUD), (62, 70, LOBBY), (70, 75, RULE)], 0)
    assert sum('turned off' in l for l in lines) == 1 and rec.state == 'WAIT_HUD'   # the next rule screen still starts a match


def test_detail_tells_a_720p_picture_scaled_up():
    up = lambda f, k: cv2.resize(cv2.resize(f, (1280, 720), interpolation=cv2.INTER_AREA), (1920, 1080), interpolation=k)
    for f in (RULE, HUD, LOBBY):
        assert M.detail(f) > 0.73
        for k in (cv2.INTER_LINEAR, cv2.INTER_CUBIC, cv2.INTER_LANCZOS4):
            assert M.detail(up(f, k)) < 0.72
