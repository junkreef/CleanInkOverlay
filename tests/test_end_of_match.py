"""Recorder: the screens after a match. A scoreboard / 表彰 screen shown shorter than its STABLE count (a player pressing
つづける!) is taken from its last still sample, never from a frame of the panel sliding; without a scoreboard the match is
stored AFTER_SCREENS_WAIT after the judge / 表彰 screen went instead of RESULT_WAIT after the HUD. 60 fps in, 1 frame in 6
analysed: every case is fed at the 6 sampling phases.
    uv run pytest tests/test_end_of_match.py
"""
import copy, hashlib, os, sys
import numpy as np, pytest
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if os.path.join(ROOT, 'work') not in sys.path: sys.path.insert(0, os.path.join(ROOT, 'work'))
import recorder as R
from test_recorder import FakeStore, frame, sliding_in, RULE_FRAME, OTHER_FRAME, VIDEO

BOARD = frame('0268_result_scoreboard.png')          # ナワバリ, win; parses sanely
MEDALS = frame(os.path.join('medals', 'v1m1_260.0.png'))
JUDGE = frame('judge_lose_266.5.png')
END = 250.0                                         # the HUD went here (WAIT_RESULT since)
B0 = END + 2.0                                      # when the scoreboard appears in the tests of it
SLIDE = (-120, -27, -4)                             # px off its place, one 60 fps frame each: the panel sliding in (all pass
                                                    # looks_like_result; -4 even parses sanely, the same as the settled screen)


PARSED = {}


@pytest.fixture(autouse=True)
def parse_once(monkeypatch):
    """the real result parser, once per distinct frame (~0.5-1.5 s each; the same frames come at every phase)"""
    parse, seen = R.parse, PARSED
    def cached(f, *a, **k):
        key = hashlib.md5(f.tobytes()).hexdigest()
        if key not in seen: seen[key] = parse(f, *a, **k)
        return copy.deepcopy(seen[key])
    monkeypatch.setattr(R, 'parse', cached)


@pytest.fixture(autouse=True)
def short_waits(monkeypatch):
    """the time limits shortened (60 s / 300 s of samples cost minutes): what is tested is where they count from"""
    monkeypatch.setattr(R, 'AFTER_SCREENS_WAIT', 3.0); monkeypatch.setattr(R, 'RESULT_WAIT', 30.0)


def turf_match():
    """a recorder with a ナワバリ match in WAIT_RESULT since END, and its store; the log kept in rec.lines"""
    store = FakeStore(); lines = []
    rec = R.Recorder(VIDEO, store, log=lambda *a: lines.append(' '.join(map(str, a)))); rec.lines = lines
    rec.start_match(RULE_FRAME, 50.0); rec.m['t0'] = 67.0
    rec.state = 'WAIT_RESULT'; rec.t_state = END
    return rec, store


def run(rec, screen_at, phase, t1, t0=END + 0.05):
    """feed the samples of phase `phase` (frame k of every 6) in [t0, t1)"""
    k = int(np.ceil((t0 - phase / 60) / 0.1 - 1e-9))
    while (t := phase / 60 + k * 0.1) < t1:
        rec.process(screen_at(t), t); k += 1


def scoreboard(appear, shown, slide=SLIDE):
    """the scoreboard sliding in at `appear` (one 60 fps frame per offset), settled for `shown` s, sliding out the same
    way (the 2026-10-11_22-14-08 scoreboard: 1-2 moving frames pass the check on the way in, 1 on the way out)"""
    n = len(slide); m = int(round(shown * 60))
    def at(t):
        j = int(round((t - appear) * 60))                              # frame number since it appeared
        if 0 <= j < n: return sliding_in(BOARD, slide[j])
        if n <= j < n + m: return BOARD
        if n + m <= j < 2 * n + m: return sliding_in(BOARD, -slide[2 * n + m - 1 - j])
        return OTHER_FRAME
    return at


def stored_board(store):
    (rec,) = store.inserted
    m, players = rec['match'], rec['players']
    return m['result_image'] is not None, m['result'], m['my_pct'], m['enemy_pct'], sorted((p['points'], p['deaths']) for p in players)


def test_a_long_scoreboard_is_taken_at_its_10th_sample_as_before():
    want = None
    for phase in range(6):
        rec, store = turf_match()
        run(rec, scoreboard(B0, 3.0), phase, B0 + 5.0)
        assert rec.state == 'IDLE' and len(store.inserted) == 1, phase
        assert B0 + 0.9 - 1e-6 <= rec.t_last_store < B0 + 1.0, (phase, rec.t_last_store)   # first sample of it + 0.9 s
        got = stored_board(store); want = want or got
        assert got[0] and got == want and len(got[4]) == 8, phase
        assert not any('still sample' in ln for ln in rec.lines), phase
    assert want[1] == 'win'


def test_a_scoreboard_skipped_before_its_count_is_taken_at_every_phase():
    """shown 0.25 s settled (2 samples or 3 at any phase): taken when it goes, from its last still sample, and read the
    same as the screen shown for seconds"""
    rec, store = turf_match(); run(rec, scoreboard(B0, 3.0), 0, B0 + 5.0); want = stored_board(store)
    for shown in (0.25, 0.6):
        for phase in range(6):
            rec, store = turf_match()
            run(rec, scoreboard(B0, shown), phase, B0 + 2.0)
            assert rec.state == 'IDLE' and len(store.inserted) == 1, (shown, phase)
            assert stored_board(store) == want, (shown, phase)
            assert any('taking its last still sample' in ln for ln in rec.lines), (shown, phase)


def test_a_scoreboard_leaving_at_its_10th_sample_is_taken_from_the_sample_before():
    """2026-11-10_00-38-55: shown ~1 s, the 10th sample caught the panel leaving (27 px off) and the screen was discarded.
    Here 55 frames pass the check (3 sliding in, 0.85 s settled, the first one sliding out): at the phase that samples
    frames 0, 6, ..., 54 the 10th sample is the one leaving, the other phases see the screen go after 9 samples. Every
    phase stores the settled read"""
    rec, store = turf_match(); run(rec, scoreboard(B0, 3.0), 0, B0 + 5.0); want = stored_board(store)
    moving = 0
    for phase in range(6):
        rec, store = turf_match()
        run(rec, scoreboard(B0, 0.85, slide=(-120, -60, -27)), phase, B0 + 2.0)
        assert len(store.inserted) == 1 and stored_board(store) == want, phase
        moving += any('moving at its 10th sample' in ln for ln in rec.lines)
    assert moving                                                      # the case did come up


def test_a_panel_that_never_settles_is_not_taken():
    """only moving frames (every sample a different offset): nothing read from them; the match is stored later without
    a scoreboard (here by AFTER_SCREENS_WAIT after the judge screen)"""
    offsets = [-120, -60, -27, -10, -4, 4, 10, 27, 60, -27, -10, -4, 4, 10]
    def at(t):
        if END + 1.0 <= t < END + 2.0: return JUDGE
        k = int(round((t - B0) * 60)) // 6                           # a new offset every sample
        return sliding_in(BOARD, offsets[k]) if 0 <= k < len(offsets) else OTHER_FRAME
    for phase in range(6):
        rec, store = turf_match()
        run(rec, at, phase, END + 2.0 + R.AFTER_SCREENS_WAIT + 0.2)
        assert rec.state == 'IDLE' and len(store.inserted) == 1, phase
        assert stored_board(store)[0] is False and not store.inserted[0]['players'], phase   # no scoreboard, no panel
        assert not any('still sample' in ln for ln in rec.lines), phase


def test_without_a_scoreboard_the_match_is_stored_after_the_last_screen_at_every_phase():
    """the 表彰 screen shown longer than the wait (a player can sit on it): stored AFTER_SCREENS_WAIT after it went, not
    RESULT_WAIT after the HUD, nothing before. With the judge screen only, counted from the judge screen"""
    W = R.AFTER_SCREENS_WAIT; gone = END + 10.0
    for phase in range(6):
        rec, store = turf_match()
        run(rec, lambda t: JUDGE if END + 1.0 <= t < END + 2.0 else MEDALS if END + 3.0 <= t < gone else OTHER_FRAME, phase, gone + W - 0.1)
        assert rec.state == 'WAIT_RESULT' and not store.inserted, phase
        run(rec, lambda t: OTHER_FRAME, phase, gone + W + 0.2, t0=gone + W - 0.1)
        assert rec.state == 'IDLE' and len(store.inserted) == 1, phase
        assert gone + W - 0.1 < rec.t_last_store <= gone + W + 0.1, (phase, rec.t_last_store)
        m = store.inserted[0]['match']
        assert m['result_image'] is None and m['medal_image'] and m['result'] == 'lose' and 'from the judge screen' in m['notes'], phase
        rec, store = turf_match()
        run(rec, lambda t: JUDGE if END + 1.0 <= t < END + 2.0 else OTHER_FRAME, phase, END + 2.0 + W + 0.2)
        assert rec.state == 'IDLE' and END + 2.0 + W - 0.1 < rec.t_last_store <= END + 2.0 + W + 0.1, (phase, rec.t_last_store)
    rec, store = turf_match()                                          # nothing after the HUD: RESULT_WAIT as before
    run(rec, lambda t: OTHER_FRAME, 0, END + R.RESULT_WAIT - 0.5)
    assert rec.state == 'WAIT_RESULT'
    run(rec, lambda t: OTHER_FRAME, 0, END + R.RESULT_WAIT + 0.5, t0=END + R.RESULT_WAIT - 0.5)
    assert rec.state == 'IDLE' and len(store.inserted) == 1


def test_a_scoreboard_after_the_match_was_stored_without_it_is_not_a_match_of_its_own():
    rec, store = turf_match(); W = R.AFTER_SCREENS_WAIT
    run(rec, lambda t: JUDGE if END + 1.0 <= t < END + 2.0 else OTHER_FRAME, 0, END + 2.0 + W + 0.2)
    assert len(store.inserted) == 1 and rec.state == 'IDLE'
    t1 = END + 2.0 + W + 2.0
    run(rec, scoreboard(t1, 3.0), 0, t1 + 4.0, t0=END + 2.0 + W + 0.2)
    assert len(store.inserted) == 1 and any('after the match was stored without it' in ln for ln in rec.lines)
