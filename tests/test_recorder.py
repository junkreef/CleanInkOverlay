"""Recorder: matches of rules without timeline support (NONTURF: ガチホコ etc., timer from 5:00).
    uv run pytest
"""
import os, sys
import cv2
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if os.path.join(ROOT, 'work') not in sys.path: sys.path.insert(0, os.path.join(ROOT, 'work'))
import recorder as R
from signatures import Library
from weapon_icons import IconLibrary

RULE_FRAME = cv2.imread(os.path.join(ROOT, 'work', 'frames', '0041_match_start_rule.png'))
OTHER_FRAME = cv2.imread(os.path.join(ROOT, 'work', 'frames', '0004_lobby_matchinfo.png'))   # classify(): no screen of interest
VIDEO = '2026-10-28_22-51-57.mp4'                                                             # name only: video_time() reads the start from it


class FakeStore:
    """the repo's libraries, read only; writes are kept in lists"""
    def __init__(self):
        self.sig = Library(os.path.join(ROOT, 'assets', 'signatures.json'))
        self.icons = IconLibrary(os.path.join(ROOT, 'assets', 'weapon_icons_captured'), os.path.join(ROOT, 'data', 'icon_samples'))
        self.inserted = []; self.json = []
    def signatures(self): return self.sig
    def weapon_icons(self): return self.icons
    def save_libraries(self): pass
    def save_image(self, stamp, kind, frame): return f'{stamp}_{kind}.png'
    def save_bubble(self, name, sheet): return name
    def save_evidence(self, name, sheet): return name
    def save_json(self, stamp, name, obj): self.json.append(obj)
    def insert_match(self, match, players, events, medals, timeline):
        self.inserted.append(dict(match=match, players=players, events=events, medals=medals)); return len(self.inserted)


def nonturf_match(dry=False):
    """a recorder whose match is NONTURF: rule screen at 50 s, timer 4:59 read at 68 s"""
    store = FakeStore(); rec = R.Recorder(VIDEO, store, dry=dry, log=lambda *a: None)
    rec.start_match(RULE_FRAME, 50.0)
    rec.m.update(nonturf=True, t0=67.0, notes='timer started at 4:59: not ナワバリ, no timeline'); rec.state = 'NONTURF'; rec.t_state = 68.0
    return rec, store


PANEL = dict(weapon='プロモデラーMG', weapon_sig=None, points=1810, kills_assists=12, deaths=6, specials=6, glyph_score=0.72,
             stage='スメーシーワールド', mode='バンカラマッチ(チャレンジ)', rule=None)


def test_without_scoreboard_the_judge_and_panel_are_stored():
    rec, store = nonturf_match()
    counts = {'my': dict(count=68, ko=False, points=340), 'enemy': dict(count=40, ko=False, points=200)}
    rec.judge = [dict(t=719.0 + 0.1 * i, result='win', label_score=0.99, my_pct=None, enemy_pct=None, counts=counts) for i in range(20)]
    rec.medals_pending = dict(t=735.0, medals=[], image='m.png', panel=PANEL)
    rec.process(OTHER_FRAME, 1000.0)
    assert rec.state == 'NONTURF' and not store.inserted                 # still within RESULT_WAIT of the medal screen
    rec.process(OTHER_FRAME, 735.0 + R.RESULT_WAIT + 1)
    assert rec.state == 'IDLE' and len(store.inserted) == 1
    m = store.inserted[0]['match']; (me,) = store.inserted[0]['players']
    assert (m['result'], m['my_pct'], m['enemy_pct'], m['stage'], m['mode']) == ('win', None, None, 'スメーシーワールド', 'バンカラマッチ(チャレンジ)')
    assert (m['my_count'], m['enemy_count'], m['knockout'], m['my_team_points'], m['enemy_team_points']) == (68, 40, 0, 340, 200)
    assert 'no result screen: result and counts from the judge screen' in m['notes'] and 'own row and stage from the result panel' in m['notes']
    assert (me['slot'], me['is_self'], me['link_score'], me['weapon'], me['specials']) == (0, 1, None, 'プロモデラーMG', 6)


def test_a_rule_screen_stores_it_too():
    rec, store = nonturf_match()
    rec.medals_pending = dict(t=735.0, medals=[], image='m.png', panel=PANEL)
    rec.on_rule(RULE_FRAME, 800.0)
    assert len(store.inserted) == 1 and rec.state == 'WAIT_HUD'


def test_nothing_after_the_start_is_not_stored():
    rec, store = nonturf_match()
    rec.process(OTHER_FRAME, 68.0 + R.NONTURF_WAIT + 1)
    assert rec.state == 'IDLE' and rec.m is None and not store.inserted
    rec, store = nonturf_match()
    rec.on_rule(RULE_FRAME, 300.0)                                       # aborted: the next match's rule screen, no judge / panel
    assert not store.inserted and rec.state == 'WAIT_HUD'


def scoreboard(rule):
    rows = [dict(row=f'{tm}{i}', team=tm, self=(tm == 'win' and i == 1), weapon='プロモデラーMG', weapon_score=0.9, weapon_conf=1.0,
                 points='1000', kills='05', deaths='03', specials='02') for tm in ('win', 'lose') for i in range(1, 5)]
    return dict(rows=rows, self_result='win', pct_left='91.0%', pct_right='9.0%', stage='スメーシーワールド', mode='バンカラマッチ(チャレンジ)', rule=rule)


def stored_pct(rec, store, monkeypatch, rule):
    monkeypatch.setattr(R, 'parse', lambda *a: scoreboard(rule))
    rec.on_result(OTHER_FRAME, 400.0)
    m = store.json[-1]['match']
    return m['my_pct'], m['enemy_pct']


def test_no_pct_but_for_turf(monkeypatch):
    rec, store = nonturf_match(dry=True)
    assert stored_pct(rec, store, monkeypatch, None) == (None, None)     # 'ノックアウト!' / '0カウント' were read as a % bar
    for rule, want in (('ガチホコバトル', (None, None)), ('ナワバリバトル', (91.0, 9.0)), (None, (91.0, 9.0))):
        store = FakeStore(); rec = R.Recorder(VIDEO, store, dry=True, log=lambda *a: None)
        assert stored_pct(rec, store, monkeypatch, rule) == want, rule  # no rule screen (IDLE): the scoreboard's rule decides


def test_judge_votes_per_side():
    """a side's count and points each need 2 frames that agree; a frame where one side is covered still votes for the other"""
    rec, _ = nonturf_match()
    side = lambda c, ko, p: dict(count=c, ko=ko, points=p)
    reads = [({'my': side(100, True, 500), 'enemy': side(0, False, 0)})] * 3 + \
            [({'my': side(100, True, None), 'enemy': side(None, None, None)})] * 4 + \
            [({'my': side(54, False, 273), 'enemy': side(54, False, 273)})]          # still counting up when the label came
    rec.judge = [dict(t=302.9 + 0.1 * i, result='win', label_score=0.99, my_pct=None, enemy_pct=None, counts=c) for i, c in enumerate(reads)]
    j = rec.judge_summary()
    assert (j['my_count'], j['enemy_count'], j['knockout'], j['my_team_points'], j['enemy_team_points']) == (100, 0, 1, 500, 0)
