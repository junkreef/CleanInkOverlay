"""Read the OBS Virtual Camera, keep a rolling buffer of raw frames, dump them as PNG on a hotkey.

    python work/live_capture.py                # 30 s buffer at 10 fps, hotkey F9
    python work/live_capture.py --seconds 60 --fps 10 --key f9 --out samples/live

Frames arrive uncompressed (NV12 -> BGR), so near-black detail such as the 4Kスコープ scope tube survives.
Press the hotkey when the result screen is up: every buffered frame is written to <out>/<timestamp>/.
Press Ctrl+C in the console to stop.
"""
import argparse, collections, os, sys, threading, time
import cv2, numpy as np

try:
    from pygrabber.dshow_graph import FilterGraph
except ImportError:
    FilterGraph = None


def find_device(name_part='OBS Virtual Camera'):
    if FilterGraph is None:
        return None
    for i, n in enumerate(FilterGraph().get_input_devices()):
        if name_part.lower() in n.lower():
            return i, n
    return None


def write_frames(d, frames):
    os.makedirs(d, exist_ok=True)
    for t, img in frames:
        cv2.imwrite(os.path.join(d, f'{t:.3f}.png'), img)
    print(f'saved {len(frames)} frames -> {d}', flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--device', type=int, default=None, help='DirectShow index (default: find "OBS Virtual Camera")')
    ap.add_argument('--seconds', type=float, default=30)
    ap.add_argument('--fps', type=float, default=10, help='buffer sample rate (camera is read at full rate)')
    ap.add_argument('--key', default='f9')
    ap.add_argument('--out', default='samples/live')
    ap.add_argument('--test-dump-after', type=float, default=0, help='debug: dump once after N seconds')
    a = ap.parse_args()

    idx = a.device
    if idx is None:
        found = find_device()
        if not found:
            sys.exit('OBS Virtual Camera not found: start it in OBS (仮想カメラ開始) or pass --device N')
        idx, name = found
        print(f'device {idx}: {name}')
    cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920); cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    if not cap.isOpened():
        sys.exit('could not open device')

    buf = collections.deque(maxlen=int(a.seconds * a.fps))
    lock = threading.Lock()
    dump_req = threading.Event()

    try:
        import keyboard
        keyboard.add_hotkey(a.key, dump_req.set)
        print(f'hotkey {a.key.upper()}: dump last {a.seconds:.0f} s ({buf.maxlen} frames) to {a.out}/')
    except Exception as e:  # keyboard module needs no admin on Windows, but be safe
        print('hotkey unavailable:', e, '- press Enter in this console instead')
        threading.Thread(target=lambda: [dump_req.set() for _ in iter(sys.stdin.readline, '')], daemon=True).start()

    period = 1.0 / a.fps
    next_t = time.time(); n = 0; t0 = time.time(); last_log = t0; test_done = a.test_dump_after <= 0
    try:
        while True:
            ok, f = cap.read()
            if not ok:
                print('read failed'); time.sleep(0.1); continue
            n += 1
            now = time.time()
            if now >= next_t:
                with lock:
                    buf.append((now, f.copy()))
                next_t += period
            if not test_done and now - t0 >= a.test_dump_after:
                test_done = True; dump_req.set()
            if dump_req.is_set():
                dump_req.clear()
                with lock:
                    frames = list(buf)
                d = os.path.join(a.out, time.strftime('%Y-%m-%d_%H-%M-%S'))
                threading.Thread(target=write_frames, args=(d, frames), daemon=True).start()  # keep reading while PNGs are written
            if now - last_log >= 5:
                last_log = now; print(f'{n} frames, {n / (now - t0):.1f} fps read, buffer {len(buf)}/{buf.maxlen}', flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        cap.release()


if __name__ == '__main__':
    main()
