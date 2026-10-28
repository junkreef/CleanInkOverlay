"""Component 2 - the recorder: watches the capture input (OBS Virtual Camera) or a recording and feeds
matches into the store. The analysis engine is work/recorder.py (class Recorder); this module only owns
the frame loop, the CLI and the thread wrapper the web backend uses.

    uv run python -m app.recorder --live                    # OBS Virtual Camera (DirectShow), until Ctrl-C or --minutes
    uv run python -m app.recorder --video FILE [--from S --to S]
    options: --db PATH (default data/splatoon.db)  --dry (analyse, do not write)  --debug (keep per-sample JSON)
"""
import argparse, collections, os, sys, threading, time
import cv2
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
WORK = os.path.join(ROOT, 'work')
if WORK not in sys.path: sys.path.insert(0, WORK)
from app.store import Store
from recorder import Recorder as Engine                      # work/recorder.py


def run_video(store, path, t_from=0.0, t_to=None, dry=False, debug=False, log=print, stop=None):
    rec = Engine(path, store, dry=dry, log=log, debug=debug)
    cap = cv2.VideoCapture(path); fps = cap.get(cv2.CAP_PROP_FPS) or 60.0; step = max(1, int(round(fps / 10))); t_start = time.time()
    i = int(t_from * fps)
    if i: cap.set(cv2.CAP_PROP_POS_FRAMES, i)
    while not (stop and stop.is_set()):
        if t_to is not None and i / fps > t_to: break
        if i % step:
            if not cap.grab(): break
            i += 1; continue
        ok, f = cap.read()
        if not ok: break
        rec.process(f, i / fps); i += 1
    if rec.state in ('INGAME', 'WAIT_RESULT', 'NONTURF') and rec.m: rec.finish(None, i / fps)
    cap.release(); log(f'done {i} frames in {time.time() - t_start:.0f}s')
    return rec


def _com_init():
    """pygrabber uses COM: every thread that touches it (FastAPI worker, recorder thread) must initialise COM first"""
    try:
        import comtypes; comtypes.CoInitialize()
    except Exception: pass


def list_devices():
    """DirectShow video input devices (index, name); needs pygrabber"""
    try:
        _com_init()
        from pygrabber.dshow_graph import FilterGraph
        return [{'index': i, 'name': n} for i, n in enumerate(FilterGraph().get_input_devices())]
    except Exception as e:
        return []


def open_device(device=None):
    if device is None:
        from live_capture import find_device
        _com_init(); found = find_device()
        if found is None: raise RuntimeError('OBS Virtual Camera が見つかりません (OBS で仮想カメラを開始してください)')
        device = found[0]
    cap = cv2.VideoCapture(device, cv2.CAP_DSHOW); cap.set(3, 1920); cap.set(4, 1080)
    if not cap.isOpened(): raise RuntimeError(f'device {device} を開けません')
    return device, cap


def run_live(store, device=None, minutes=None, dry=False, debug=False, log=print, stop=None, on_engine=None):
    idx, cap = open_device(device)
    rec = Engine('live', store, dry=dry, log=log, debug=debug)
    if on_engine: on_engine(rec)
    log(f'recording from device {idx}')
    t_end = time.time() + minutes * 60 if minutes else None; nxt = time.time(); n = 0
    try:
        while not (stop and stop.is_set()) and (t_end is None or time.time() < t_end):
            ok, f = cap.read()
            if not ok: time.sleep(0.05); continue
            now = time.time()
            if now < nxt: continue
            nxt += 0.1; n += 1
            rec.process(f, now)
            if n % 600 == 0: log(f'... {rec.state} {time.strftime("%H:%M:%S")}')
    finally:
        cap.release(); log('capture closed')
    return rec


class RecorderRunner:
    """runs the live recorder on a background thread (used by the web backend); keeps the last log lines"""
    def __init__(self, store, device=None, dry=False, debug=False, log_lines=300, on_change=None):
        self.store, self.device, self.dry, self.debug = store, device, dry, debug
        self.thread = None; self.stop = threading.Event(); self.engine = None; self.on_change = on_change
        self.log_lines = collections.deque(maxlen=log_lines); self.error = None; self.started_at = None

    def log(self, *a):
        line = ' '.join(str(x) for x in a); self.log_lines.append(f'{time.strftime("%H:%M:%S")} {line}'); print(line, flush=True)

    def start(self, device=None, dry=None):
        if self.running: return
        if device is not None: self.device = device
        if dry is not None: self.dry = dry
        self.stop.clear(); self.error = None; self.started_at = time.time(); self.engine = None
        def body():
            try: run_live(self.store, self.device, None, self.dry, self.debug, self.log, self.stop, on_engine=lambda e: (setattr(self, 'engine', e), self.changed()))
            except Exception as e: self.error = str(e); self.log(f'recorder stopped: {e!r}')
            finally: self.changed()
        self.thread = threading.Thread(target=body, name='recorder', daemon=True); self.thread.start(); self.changed()

    def shutdown(self, timeout=5):
        self.stop.set()
        if self.thread: self.thread.join(timeout)
        self.changed()

    def changed(self):
        if self.on_change:
            try: self.on_change(self.status())
            except Exception: pass

    @property
    def running(self):
        return self.thread is not None and self.thread.is_alive()

    def status(self):
        return {'running': self.running, 'state': self.engine.state if self.engine else None, 'device': self.device, 'dry': self.dry,
                'error': self.error, 'started_at': self.started_at, 'log': list(self.log_lines)[-50:]}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--video'); ap.add_argument('--live', action='store_true'); ap.add_argument('--device', type=int)
    ap.add_argument('--db'); ap.add_argument('--dry', action='store_true'); ap.add_argument('--debug', action='store_true')
    ap.add_argument('--minutes', type=float, default=None); ap.add_argument('--from', dest='t_from', type=float, default=0.0); ap.add_argument('--to', dest='t_to', type=float)
    a = ap.parse_args()
    store = Store(db_path=os.path.abspath(a.db) if a.db else None)
    if a.video: run_video(store, a.video, a.t_from, a.t_to, a.dry, a.debug)
    elif a.live: run_live(store, a.device, a.minutes, a.dry, a.debug)
    else: ap.error('--video FILE or --live')


if __name__ == '__main__':
    main()
