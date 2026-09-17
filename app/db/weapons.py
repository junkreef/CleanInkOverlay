"""Weapon master (name -> class) from the wiki icon sections, for grouping stats."""
import json, os, sys
from .models import Weapon

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
WORK = os.path.join(ROOT, 'work')
CLASSES = ['シューター', 'ローラー', 'チャージャー', 'スロッシャー', 'スピナー', 'マニューバー', 'シェルター', 'ブラスター', 'フデ', 'ストリンガー', 'ワイパー']
SECTION_STARTS = {'スプラッシュボム': 'サブ', 'ウルトラショット': 'スペシャル', 'ガチホコ': 'その他'}


def load_weapon_master(session):
    """wiki ブキ section is one flat list: class icon, then its weapons; subs / specials / misc follow the mains.
    Upserts into `weapons`; returns the number of rows written."""
    if WORK not in sys.path: sys.path.insert(0, WORK)
    from weapon_match import icon_name
    sec = os.path.join(ROOT, 'assets', 'weapon_icons_sections.json')
    if not os.path.exists(sec): return 0
    names = [icon_name(x) for x in json.load(open(sec, encoding='utf-8'))['ブキ'] if '_フチ' not in x]
    cls = None; n = 0
    for name in names:
        if name in SECTION_STARTS: cls = SECTION_STARTS[name]
        if name in CLASSES: cls = name; continue          # the class icon itself is not a weapon
        session.merge(Weapon(name=name, class_=cls)); n += 1
    session.commit()
    return n
