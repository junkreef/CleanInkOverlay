"""Recorder: a past match watched in the replay viewer (メモリープレイヤー) is not recorded again. The viewer's mark top
left (work/replay.py) is pasted onto the usual test frames: work/frames/replay_mark*.png are just that corner of a
replay (2026-04-08_00-24-01.mp4 at 12.0 s, and 18.7 s in a fade to white), no full frame of it.
    uv run pytest tests/test_replay.py
"""
import os, sys
import cv2
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if os.path.join(ROOT, 'work') not in sys.path: sys.path.insert(0, os.path.join(ROOT, 'work'))
import recorder as R, replay
from test_recorder import FakeStore, VIDEO, RULE_FRAME, OTHER_FRAME, frame, nonturf_match

MARK, FADED = frame('replay_mark.png'), frame('replay_mark_faded.png')
HUD, JUDGE = frame('0060_ingame_early.png'), frame('judge_lose_266.5.png')


def marked(f, mark=MARK):
    g = f.copy(); y0, y1, x0, x1 = replay.REGION; g[y0:y1, x0:x1] = mark
    return g


class WatchStore(FakeStore):
    """FakeStore that also notes every image, bubble, evidence and library write"""
    def __init__(self):
        super().__init__(); self.writes = []
    def save_image(self, stamp, kind, frame): self.writes.append(('image', kind)); return f'{stamp}_{kind}.png'
    def save_bubble(self, name, sheet): self.writes.append(('bubble', name)); return name
    def save_evidence(self, name, sheet): self.writes.append(('evidence', name)); return name
    def save_libraries(self): self.writes.append(('libraries',))


def test_the_mark_and_live_frames():
    for f in (MARK, FADED):
        assert replay.score(marked(OTHER_FRAME, f)) >= replay.THR
        assert replay.score(marked(HUD, f)) >= replay.THR
    # the ガチエリア frames were taken from a replay too (the viewer's hints bottom right): they carry the mark
    for n in ('gachi_rule_area.png', 'gachi_hud_area_my.png', 'gachi_hud_area_enemy.png', 'gachi_hud_area_one_zone.png'):
        assert replay.replay_mark(frame(n)), n
    live = [n for n in os.listdir(os.path.join(ROOT, 'work', 'frames'))
            if n.endswith(('.png', '.jpg')) and not n.startswith(('gachi_hud_area', 'gachi_rule_area', 'replay_mark'))]
    scores = {n: replay.score(f) for n in live for f in [frame(n)] if f is not None and f.shape[:2] == (1080, 1920)}
    assert len(scores) > 40 and max(scores.values()) < replay.THR - 0.2, max(scores.items(), key=lambda kv: kv[1])
    assert replay.score(frame('0082_map_open.png')) < 0.0                 # the map's × shares the corner


def playback(phase, lead=0.0):
    """the screens of a replayed match, sampled at `phase` (1/60 s): rule screen 3 s, HUD 6 s (with the mark; the mark
    from `lead` s before the rule screen, 0 = the same frame), the judge screen 8 s and the lobby (no mark)"""
    t = 9.0 + phase / 60
    while t < 40.0:
        if t < 10.0: f = marked(OTHER_FRAME) if t >= 10.0 - lead else OTHER_FRAME
        elif t < 13.0: f = marked(RULE_FRAME)
        elif t < 19.0: f = marked(HUD)
        elif t < 27.0: f = JUDGE
        else: f = OTHER_FRAME
        yield f, t; t += 0.1


def test_a_replay_is_not_recorded_at_every_phase():
    for phase, lead in ((p, lead) for p in range(6) for lead in (0.0, 0.3)):   # the recording: mark 0.3 s before the rule screen
        store = WatchStore(); lines = []
        rec = R.Recorder(VIDEO, store, dry=False, log=lines.append)
        for f, t in playback(phase, lead): rec.process(f, t)
        assert rec.state == 'IDLE' and rec.m is None, phase
        assert not store.inserted and not store.json and not store.writes, (phase, store.writes)
        assert not rec.judge and rec.medals_pending is None, phase
        assert len(lines) == 1 and 'replay' in lines[0], (phase, lines)


def test_a_rule_screen_with_the_mark_starts_nothing_even_before_it_is_confirmed():
    store = WatchStore(); rec = R.Recorder(VIDEO, store, dry=True, log=lambda *a: None)
    for k in range(R.STABLE['rule']): rec.process(marked(RULE_FRAME), 5.0 + 0.1 * k)
    assert rec.state == 'IDLE' and not store.writes
    for k in range(R.STABLE['rule']): rec.process(RULE_FRAME, 60.0 + 0.1 * k)   # a live rule screen long after it
    assert rec.state == 'WAIT_HUD' and ('image', 'rule') in store.writes


def test_one_false_mark_in_a_match_costs_one_sample():
    """fewer than REPLAY_CONFIRM marked samples in a live match: they are skipped, nothing else changes (the judge
    screen right after is still read)"""
    store = FakeStore(); rec = R.Recorder(VIDEO, store, dry=True, log=lambda *a: None)
    rec.start_match(RULE_FRAME, 40.0); rec.m.update(t0=50.0); rec.state = 'INGAME'; rec.killfeed = lambda f, t: None
    for k in range(10): rec.process(marked(HUD) if k in (4, 5) else HUD, 60.0 + 0.1 * k)
    assert rec.state == 'INGAME' and len(rec.m['samples']) == 8 and rec.t_replay < 0
    rec.process(JUDGE, 61.0)
    assert rec.judge


def test_a_replay_after_a_match_does_not_join_it():
    """a match waiting for its result (scoreboard skipped), then a replay: the replay's rule screen starts nothing and
    its judge screen is not taken as the match's; the match is stored RESULT_WAIT after its HUD as without a replay"""
    rec, store = nonturf_match()
    rec.judge = [dict(t=719.0 + 0.1 * i, result='win', label_score=0.99, my_pct=None, enemy_pct=None, counts=None) for i in range(5)]
    for k in range(30): rec.process(marked(RULE_FRAME), 800.0 + 0.1 * k)
    for k in range(50): rec.process(marked(HUD), 803.0 + 0.1 * k)
    for k in range(80): rec.process(JUDGE, 808.0 + 0.1 * k)                  # no mark on the replay's judge screen
    assert rec.state == 'WAIT_RESULT' and not store.inserted and len(rec.judge) == 5
    rec.process(OTHER_FRAME, 720.0 + R.RESULT_WAIT + 1)
    assert rec.state == 'IDLE' and len(store.inserted) == 1 and store.inserted[0]['match']['result'] == 'win'
