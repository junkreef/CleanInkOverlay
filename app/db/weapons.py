"""Weapon master (name -> class) from assets/weapons.json, for grouping stats."""
import json, os
from .models import Weapon

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
WEAPONS = os.path.join(ROOT, 'assets', 'weapons.json')


def load_weapon_master(session):
    """assets/weapons.json is {class: [weapon, ...]}: the main weapon classes in the game's order, then サブ / スペシャル /
    その他. Upserts into `weapons`; returns the number of rows written."""
    if not os.path.exists(WEAPONS): return 0
    n = 0
    for cls, names in json.load(open(WEAPONS, encoding='utf-8')).items():
        for name in names:
            session.merge(Weapon(name=name, class_=cls)); n += 1
    session.commit()
    return n
