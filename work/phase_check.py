"""Run the recorder over a recording at every sampling phase and show what depends on it.

The input is 60 fps and the recorder analyses 1 frame in 6 (~10 fps), so where an event falls within those 6 frames
differs from one sample to the next: a reader that only works at some phases (the rule-screen cards taken while still
fading in, a bubble shown for one frame) gives different records depending on where sampling happened to start. The
video is decoded once and every frame goes to 6 recorders, recorder k analysing frames k, k+6, k+12, ... (dry, the
repo's libraries read only). Per match: the counts of each phase, the scoreboard's own row, and the phases that differ.

    python work/phase_check.py VIDEO [VIDEO ...] [--out DIR]     # DIR: each phase's records as JSON + log (optional)
"""
import argparse, collections, json, os, sys, time
import cv2, numpy as np
sys.path.insert(0, os.path.dirname(__file__))
import recorder as R
from signatures import Library
from weapon_icons import IconLibrary

ROOT = os.path.join(os.path.dirname(__file__), '..')
STEP = 6                                  # 60 fps in, ~10 fps analysed (app/recorder.py)


class DryStore:
    """the repo's libraries, read only; records kept in memory"""
    def __init__(self):
        self.sig = Library(os.path.join(ROOT, 'assets', 'signatures.json'))
        self.icons = IconLibrary(os.path.join(ROOT, 'assets', 'weapon_icons_captured'), os.path.join(ROOT, 'data', 'icon_samples'))
        self.records = []
    def signatures(self): return self.sig
    def weapon_icons(self): return self.icons
    def save_libraries(self): pass
    def save_image(self, stamp, kind, frame): return f'{stamp}_{kind}.png'
    def save_bubble(self, name, sheet): return name
    def save_evidence(self, name, sheet): return name
    def save_json(self, stamp, name, obj): self.records.append(obj) if not name else None
    def insert_match(self, *a): return 0


def run(video, out=None):
    """-> [records of phase 0, ..., records of phase STEP-1]"""
    name = os.path.splitext(os.path.basename(video))[0]; recs = []
    for k in range(STEP):
        lg = open(os.path.join(out, f'{name}_p{k}.log'), 'w', encoding='utf-8') if out else None
        st = DryStore(); recs.append((st, R.Recorder(video, st, dry=True, log=(lambda *a, lg=lg: print(*a, file=lg, flush=True)) if lg else (lambda *a: None))))
    cap = cv2.VideoCapture(video); fps = cap.get(cv2.CAP_PROP_FPS) or 60.0; i = 0
    while True:
        ok, f = cap.read()
        if not ok: break
        st, rec = recs[i % STEP]; rec.process(f, i / fps); i += 1
    for st, rec in recs:
        if rec.state in ('INGAME', 'WAIT_RESULT') and rec.m: rec.finish(None, i / fps)
    if out:
        for k, (st, rec) in enumerate(recs):
            json.dump(clean(st.records), open(os.path.join(out, f'{name}_p{k}.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
    return [st.records for st, rec in recs]


def clean(o):
    if isinstance(o, dict): return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)): return [clean(v) for v in o]
    if isinstance(o, np.generic): return o.item()
    if isinstance(o, np.ndarray): return None
    return o


def counts(rec):
    """own kills / deaths / killers named / specials, deaths of the others"""
    me = next((p for p in rec['players'] if p['is_self']), None); s = me['slot'] if me else None; c = collections.Counter()
    for e in rec['events']:
        if e['type'] == 'death': c['death' if e['slot'] == s else 'death_other'] += 1
        elif e['type'] == 'killed_by': c['killed_by'] += 1; c['killer_named'] += e['target_slot'] is not None
        else: c[e['type']] += 1
    return c, me


KEYS = ('kill', 'death', 'killed_by', 'killer_named', 'special', 'special_ready', 'death_other')


def report(video, phases):
    print(f'== {os.path.basename(video)}: matches per phase {[len(p) for p in phases]}')
    for mi in range(max(len(p) for p in phases)):
        rows = [counts(p[mi]) if mi < len(p) else None for p in phases]
        me = next((r[1] for r in rows if r and r[1]), None)
        rec0 = next(p[mi] for p in phases if mi < len(p))
        sb = f"scoreboard k+a {me['kills_assists']} d {me['deaths']} sp {me['specials']}" if me else 'no own row'
        print(f' match {mi} {rec0["match"]["rule"]} {rec0["match"]["result"]}: {sb}')
        for key in KEYS:
            vals = [r[0][key] if r else None for r in rows]
            flag = '' if len(set(vals)) == 1 else '   <- depends on the phase'
            print(f'   {key:13s} {vals}{flag}')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('videos', nargs='+'); ap.add_argument('--out')
    a = ap.parse_args()
    if a.out: os.makedirs(a.out, exist_ok=True)
    for v in a.videos:
        t = time.time(); report(v, run(v, a.out)); print(f'   ({time.time() - t:.0f} s)', flush=True)


if __name__ == '__main__':
    main()
