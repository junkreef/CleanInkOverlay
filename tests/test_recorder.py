"""Recorder: matches of rules other than ナワバリ (ガチホコ etc., timer from 5:00): the rule name, the start, the
in-match readers of these rules (overtime, the ヤグラ / ホコ track), storing without a scoreboard.
    uv run pytest
"""
import os, sys
import cv2
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if os.path.join(ROOT, 'work') not in sys.path: sys.path.insert(0, os.path.join(ROOT, 'work'))
import recorder as R, hud, objective
from result_parser import Glyphs
from rule_screen import title_signature
from signatures import Library
from weapon_icons import IconLibrary

RULE_FRAME = cv2.imread(os.path.join(ROOT, 'work', 'frames', '0041_match_start_rule.png'))
OTHER_FRAME = cv2.imread(os.path.join(ROOT, 'work', 'frames', '0004_lobby_matchinfo.png'))   # classify(): no screen of interest
VIDEO = '2026-10-28_22-51-57.mp4'                                                             # name only: video_time() reads the start from it
frame = lambda name: cv2.imread(os.path.join(ROOT, 'work', 'frames', name))


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
    """a recorder with a 5:00 match whose HUD has just gone: rule screen at 50 s, timer 4:59 read at 68 s, over at 720 s"""
    store = FakeStore(); rec = R.Recorder(VIDEO, store, dry=dry, log=lambda *a: None)
    rec.start_match(RULE_FRAME, 50.0)
    rec.m.update(nonturf=True, dur=300, t0=67.0); rec.state = 'WAIT_RESULT'; rec.t_state = 720.0
    return rec, store


PANEL = dict(weapon='プロモデラーMG', weapon_sig=None, points=1810, kills_assists=12, deaths=6, specials=6, glyph_score=0.72,
             stage='スメーシーワールド', mode='バンカラマッチ(チャレンジ)', rule=None)


def test_without_scoreboard_the_judge_and_panel_are_stored():
    rec, store = nonturf_match()
    counts = {'my': dict(count=68, ko=False, points=340), 'enemy': dict(count=40, ko=False, points=200)}
    rec.judge = [dict(t=719.0 + 0.1 * i, result='win', label_score=0.99, my_pct=None, enemy_pct=None, counts=counts) for i in range(20)]
    rec.medals_pending = dict(t=735.0, medals=[], image='m.png', panel=PANEL)
    rec.process(OTHER_FRAME, 1000.0)
    assert rec.state == 'WAIT_RESULT' and not store.inserted             # still within RESULT_WAIT of the end of the HUD
    rec.process(OTHER_FRAME, 720.0 + R.RESULT_WAIT + 1)
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
    rec.process(OTHER_FRAME, 720.0 + R.RESULT_WAIT + 1)                  # no judge / panel / scoreboard: nothing to store
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


# ---------------------------------------------------------------- the rule name, the start, the readers of these rules
def test_the_rule_name_tells_the_rules_apart():
    names = ('0041_match_start_rule.png', 'gachi_rule_hoko.png', 'gachi_rule_yagura.png', 'gachi_rule_area.png')
    lib = Library(os.path.join(ROOT, 'no_such_file.json'))
    ids = [lib.identify(title_signature(frame(n)), 'title', thr=R.TITLE_THR)[0] for n in names + names[:1]]
    assert len(set(ids[:4])) == 4 and ids[4] == ids[0] and all(i.startswith('t_') for i in ids)   # ガチホコバトル vs ナワバリバトル: 0.63
    assert title_signature(OTHER_FRAME) is None


def test_a_5_minute_start_goes_ingame_with_its_length():
    store = FakeStore(); rec = R.Recorder(VIDEO, store, dry=True, log=lambda *a: None)
    store.sig.label('t_cf10ed6f', None)                                  # ナワバリ's rule screen as an unnamed rule: the timer decides
    rec.start_match(RULE_FRAME, 40.0)
    assert rec.m['title_id'] == 't_cf10ed6f' and rec.m['title'] is None and rec.m['analysis'] is None
    f = frame('gachi_hud_yagura_neutral.png')
    for i, rem in enumerate((300, 300, 300, 299)): rec.start_nonturf(f, 58.0 + 0.3 * i, rem, None)
    assert rec.state == 'INGAME' and rec.m['dur'] == 300 and rec.m['nonturf'] and abs(rec.m['t0'] - 57.9) < 1e-6 and len(rec.m['start_patches']) == 1
    rec = R.Recorder(VIDEO, store, dry=True, log=lambda *a: None)
    rec.start_match(frame('gachi_rule_yagura.png'), 40.0); assert rec.m['analysis'] == 'track'   # named ガチヤグラ, recorder joined late
    for i in range(3): rec.start_nonturf(f, 60.0 + i, 209 - i, None)
    assert rec.state == 'INGAME' and rec.m['dur'] == 300 and rec.m['t0'] == 62.0 - 93


def test_hud_of_rules_without_paint_points():
    g = Glyphs()
    assert hud.timer_hud(frame('gachi_hud_yagura_neutral.png'), g) == (True, 209, '3:29') and not hud.hud_visible(frame('gachi_hud_yagura_neutral.png'))
    assert hud.timer_hud(frame('gachi_hud_overtime.png'), g) == (True, None, None) and hud.overtime(frame('gachi_hud_overtime.png'))
    assert hud.timer_hud(frame('gachi_hud_asari_overtime.png'), g) == (True, None, None)    # アサリ: the box around the letters gone black
    for n in ('gachi_hud_asari.png', 'gachi_hud_yagura_ally.png', '0060_ingame_early.png', '0082_map_open.png', '0236_finish.png', '0041_match_start_rule.png'):
        assert not hud.overtime(frame(n)), n
    assert hud.timer_hud(frame('0082_map_open.png'), g)[0] is False


def test_the_objective_track():
    want = {'gachi_hud_yagura_neutral.png': (0.3, None, 36.6, 0.0), 'gachi_hud_yagura_ally.png': (39.9, 'my', 39.9, 0.0),
            'gachi_hud_yagura_enemy.png': (-30.7, 'enemy', 39.8, 30.7), 'gachi_hud_hoko_dropped.png': (22.2, None, 67.9, 4.9),
            'gachi_hud_overtime.png': (78.1, 'my', 78.1, 80.0)}            # ホコ: my best +67.9 at 68 counts (judge screen)
    for n, w in want.items():
        r = objective.read(frame(n))
        assert (r['pos'], r['holder'], r['my_best'], r['enemy_best']) == w, n
        assert objective.present(frame(n)), n
    assert objective.read(frame('gachi_hud_hoko_ally.png'))['holder'] == 'enemy'    # ally orange: the blue icon is the enemy's
    assert not objective.present(frame('0060_ingame_early.png')) and not objective.present(frame('0176_ingame_lastmin.png'))


def test_a_best_only_grows_and_one_misread_does_not_count():
    assert R.best_series([0, 10, None, 12, 90, 13, 14, 12, 15]) == [0.0, 5.0, None, 10.0, 12.0, 13.0, 14.0, 14.0, 14.0]
    assert R.best_series([None, None]) == [None, None]


def test_a_turf_match_does_not_take_the_timer_box_for_its_hud():
    """ナワバリ keeps its own HUD test (paint points top right): a frame whose timer box reads but has no paint points
    is no HUD there"""
    store = FakeStore(); rec = R.Recorder(VIDEO, store, dry=True, log=lambda *a: None)
    rec.start_match(RULE_FRAME, 40.0); rec.m['t0'] = 50.0; rec.state = 'INGAME'
    rec.process(frame('gachi_hud_yagura_neutral.png'), 60.0)
    assert rec.scr is None and rec.state == 'INGAME' and rec.m['samples'][-1]['vis'] is False


def test_the_area_counts():
    """ガチエリア / ガチアサリ: 「のこり」 of both boxes as counts (100 - のこり), and whose box is lit (holds every zone /
    attacks, counting down)"""
    import area
    g = Glyphs()
    want = {'gachi_hud_area_my.png': (23, 0, 'my'), 'gachi_hud_area_enemy.png': (98, 36, 'enemy'), 'gachi_hud_area_one_zone.png': (23, 12, None),
            'gachi_hud_asari.png': (32, 0, None)}
    for n, w in want.items():
        r = area.read(frame(n), g)
        assert (r['my_count'], r['enemy_count'], r['holder']) == w, n
        assert area.present(frame(n), g), n
    for n in ('gachi_hud_yagura_neutral.png', 'gachi_hud_hoko_ally.png', 'gachi_hud_overtime.png', '0060_ingame_early.png', '0176_ingame_lastmin.png'):
        assert not area.present(frame(n), g), n
    assert R.RULE_ANALYSIS['ガチエリア'] == R.RULE_ANALYSIS['ガチアサリ'] == 'zones'
    pens = {n: (r['my_penalty'], r['enemy_penalty']) for n in want for r in [area.read(frame(n), g)]}
    assert pens == {'gachi_hud_area_my.png': (None, None), 'gachi_hud_area_enemy.png': (56, 23), 'gachi_hud_area_one_zone.png': (None, 10),
                    'gachi_hud_asari.png': (10, None)}


def test_penalty_series():
    """short gaps before the next read keep the value, a gone pill is 0 where the count was read, a lone misread is dropped"""
    vals = [None, 74, 74, None, None, 74, 72, 14, 69, 67, None, None, None, None, None]
    counted = [True] * 13 + [False, False]
    assert R.penalty_series(vals, counted) == [0, 74, 74, 74, 74, 74, 72, 69, 67, 67, 0, 0, 0, None, None]


def test_the_named_rule_titles_pick_the_analysis():
    """assets/signatures.json names the rule screens of ガチホコバトル / ガチヤグラ / ガチエリア"""
    for name, title, analysis in (('gachi_rule_hoko.png', 'ガチホコバトル', 'track'), ('gachi_rule_yagura.png', 'ガチヤグラ', 'track'), ('gachi_rule_area.png', 'ガチエリア', 'zones')):
        rec = R.Recorder(VIDEO, FakeStore(), dry=True, log=lambda *a: None)
        rec.start_match(frame(name), 40.0)
        assert (rec.m['title'], rec.m['analysis']) == (title, analysis), name


def test_a_schedule_change_stores_it_at_once():
    """「スケジュールが更新されました」 (where the scoreboard would come): stored after 3 samples, not RESULT_WAIT later"""
    notice = frame('schedule_updated.png')
    assert R.classify(notice) == 'schedule' and R.classify(OTHER_FRAME) is None
    rec, store = nonturf_match()
    rec.medals_pending = dict(t=735.0, medals=[], image='m.png', panel=PANEL)
    for k in range(3): rec.process(notice, 744.3 + 0.1 * k)
    assert rec.state == 'IDLE' and len(store.inserted) == 1
    assert store.inserted[0]['players'][0]['weapon'] == 'プロモデラーMG'
    rec.process(notice, 744.6)                                           # the rest of the notice: nothing more to store
    assert len(store.inserted) == 1 and rec.state == 'IDLE'


def test_each_state_checks_only_its_screens():
    hud_f, result_f, notice = frame('0060_ingame_early.png'), frame('0268_result_scoreboard.png'), frame('schedule_updated.png')
    assert (R.classify(hud_f), R.classify(result_f), R.classify(notice)) == ('hud', 'result', 'schedule')
    assert R.classify(hud_f, R.SCREENS['IDLE']) is None and R.classify(hud_f, R.SCREENS['WAIT_RESULT']) is None
    assert R.classify(result_f, R.SCREENS['WAIT_HUD']) is None and R.classify(notice, R.SCREENS['IDLE']) is None
    assert R.classify(hud_f, R.SCREENS['INGAME']) == 'hud' and R.classify(result_f, R.SCREENS['WAIT_RESULT']) == 'result'
    assert set(R.SCREENS) == {'IDLE', 'WAIT_HUD', 'INGAME', 'WAIT_RESULT'} and all(set(v) <= set(R.ALL_SCREENS) for v in R.SCREENS.values())


def test_a_flash_over_the_full_gauge_is_no_special():
    """another screen flashing over the full gauge reads as white -> orange like a use, but the ring is full again
    right after; a real use drains and stays down (ガチアサリ 2026-10-29: 9 uses read, 7 on the scoreboard)"""
    row = lambda t, o, w: dict(t=t, vis=True, g_or=o, g_wh=w)
    used = [row(t / 10, 0.0, 0.3) for t in range(10)] + [row(1.0 + t / 10, 0.37 - t * 0.02, 0.0) for t in range(15)]
    flash = [row(t / 10, 0.0, 0.3) for t in range(10)] + [row(1.0, 0.0, 0.0), row(1.1, 0.4, 0.0), row(1.2, 0.35, 0.0)] + [row(1.3 + t / 10, 0.0, 0.3) for t in range(10)]
    assert hud.special_uses(used) == [1.0]
    assert hud.special_uses(flash) == []


def test_the_cards_are_taken_once_they_have_faded_in_at_every_phase():
    """60 fps in, 1 frame in 6 analysed: where the rule screen starts within those 6 frames shifts every sample, so
    each of the 6 phases is fed. The cards fade in over ~0.5 s; whatever the phase, they are taken again
    RULE_CARDS_AT to RULE_CARDS_AT + 0.1 s after the screen appeared (start_match comes ~0.2 s in, too early)"""
    appear = 1.0
    for phase in range(6):
        rec = R.Recorder(VIDEO, FakeStore(), dry=True, log=lambda *a: None)
        for k in range(30):
            t = phase / 60 + k * 0.1
            rec.process(RULE_FRAME if t >= appear else OTHER_FRAME, t)
        assert rec.state == 'WAIT_HUD' and rec.m['card_tpl'], phase
        assert R.RULE_CARDS_AT <= rec.m['cards_at'] - appear < R.RULE_CARDS_AT + 0.1 + 1e-6, (phase, rec.m['cards_at'])


def test_the_map_hides_the_hud_at_every_phase():
    """the × top left tells the map; its samples and those of the next MAP_AFTER s (the HUD half back as it closes) are
    no HUD. A 0.25 s look at the map is seen at each of the 6 sampling phases"""
    hud_f, map_f = frame('0060_ingame_early.png'), frame('0082_map_open.png')
    assert hud.map_open(map_f) and not hud.map_open(hud_f) and not hud.map_open(OTHER_FRAME)
    assert R.classify(map_f, R.SCREENS['INGAME']) == 'map'
    t_open, t_close = 5.0, 5.25
    for phase in range(6):
        rec = R.Recorder(VIDEO, FakeStore(), dry=True, log=lambda *a: None)
        rec.m = dict(ts='x', t_rule=0.0, card_tpl=None, start_patches=[], samples=[], kf=[], bubbles=[], t0=0.0, notes=None, analysis='turf'); rec.state = 'INGAME'
        seen = []; rec.killfeed = lambda f, t: seen.append(t)
        for k in range(40, 70):
            t = phase / 60 + k * 0.1
            rec.process(map_f if t_open <= t < t_close else hud_f, t)
        S = rec.m['samples']; on_map = [r['t'] for r in S if t_open <= r['t'] < t_close]; last = on_map[-1]
        assert on_map and not any(r['vis'] for r in S if t_open <= r['t'] <= last + 0.15), phase
        assert all(r['vis'] for r in S if r['t'] < t_open or r['t'] > last + 0.25), phase
        assert not set(on_map) & set(seen), phase                     # nor the killfeed: 「スタート地点」 at the bottom reads as a kill
