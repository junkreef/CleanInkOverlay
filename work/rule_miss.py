"""Diagnostics for a battle that starts while the recorder is IDLE: the rule screen before it was not recognised.

2026-11-13: on one of four PCs the overlay never left ロビー (IDLE) at the start of a battle, in every match, and the
author's own first two Xマッチ (2026-11-12, DB 703 / 704) were stored from their result screen only ('no rule screen').
Nobody had a frame of those rule screens. This watcher makes the next miss leave evidence by itself. It only looks and
writes evidence: it never starts, changes or stores a match.

While IDLE, every sample:
- a small frame every RING_STEP s for the last RING_SECONDS (the rule screen ends ~10-20 s before the timer starts)
- every CHECK_STEP s the three checks of looks_like_rule (scan_screens.rule_checks): the samples that pass one or two of
  them, and the full-size frame that came closest to a rule screen
- the HUD's timer: while its black box is there, the digits are read (every sample for RUN_READ s, then every SLOW_READ s)
  until two reads decide the run of the box
A battle has evidently begun while IDLE when the first two timer reads of a run are at a start value (3:00 / 5:00), no
timer read for NO_HUD s before and the watcher has been running that long: a recorder started mid-match, or a timer back
after the map / a splat, reads another time or comes sooner. Then one log line says so (frame size, black / white
levels, sample rate, how much detail finer than 720p the frame has, what the rule checks saw) and the small frames (one
contact sheet, samples/misses/), the HUD frame and the closest full-size frame (PNG, samples/matches/) are saved - at
most MAX_SAVES times per run of the recorder and not within SAVE_GAP s of the last save; the log line is written anyway.
Both folders are pruned with the other screens (Store.prune_images).
"""
import collections
import cv2, numpy as np
import hud
from scan_screens import rule_checks

RING_SECONDS = 30.0     # s of small frames kept: from the rule screen (2.0-6.5 s long) to the HUD's first 3:00 is ~10-20 s
RING_STEP = 0.5         # s between them
RING_SIZE = (320, 180)  # px: a contact sheet of 60 tiles, 6 across, is 1920 x 1800
NO_HUD = 30.0           # s without a readable timer (and of watching) before a timer at its start counts as a new battle
START = ((178, 180), (298, 300))   # the timer at its start: ナワバリ 3:00, the other rules 5:00 (shown for a few s before it runs)
RUN_GAP = 2.0           # s without the timer box that end a run of it (the map, a splat: the timer is read again after)
CHECK_STEP = 0.3        # s between two samples whose rule checks are taken (~1 ms each, ~0.3 ms per sample on average)
RUN_READ = 5.0          # s of a run of the box in which the timer is read every sample (2.2 ms a read); after that every SLOW_READ s
SLOW_READ = 0.5         # (the intro shows the box for a few s before the timer reads; the result screen has a dark box there too)
SAVE_GAP = 600.0        # s between two saves
MAX_SAVES = 3           # saves per run of the recorder (each ~2 full-size PNG + one ~0.5 MB sheet)
UPSCALE_W = 1280        # detail(): the round trip that tells a 720p source scaled up to 1080p


def timer_box(f):
    """the HUD's black timer box is there (the same test as hud.timer_hud / hud_visible, without reading the digits)"""
    tv = cv2.cvtColor(hud.crop(f, hud.TIMER), cv2.COLOR_BGR2HSV)[..., 2]
    return 0.55 < (tv < 60).mean() < 0.9


def roundtrip(g, w):
    """mean abs difference between a grey frame and the frame shrunk to w px wide and scaled back"""
    h, W = g.shape; s = cv2.resize(g, (w, round(h * w / W)), interpolation=cv2.INTER_AREA)
    return float(cv2.absdiff(g, cv2.resize(s, (W, h), interpolation=cv2.INTER_LINEAR)).mean())


def detail(f):
    """how much of the frame's detail is finer than 720p: the 1280 px round trip's loss over the 960 px one. A picture scaled
    up from 720p has no detail finer than its pixels and loses little at 1280 (0.58-0.71 over 30 test frames, bilinear /
    bicubic / Lanczos + sharpening), a native 1080p frame 0.74-0.77, 1600x900 scaled up / a slight blur 0.69-0.72. ~45 ms"""
    g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
    return roundtrip(g, UPSCALE_W) / max(roundtrip(g, 960), 1e-6)


def describe(c):
    d685, d755 = c['desc_dark']
    return (f'tag dark {c["tag_dark"]:.2f} white {c["tag_white"]:.2f}{"" if c["tag"] else " (FAIL)"}, desc {d685:.2f}/{d755:.2f}{"" if c["desc"] else " (FAIL)"}, '
            f'ids {sum(x >= 100 for x in c["id_contrast"])}/8 [{" ".join(str(int(x)) for x in c["id_contrast"])}]{"" if c["ids"] else " (FAIL)"}')


class MissWatch:
    def __init__(self, store, log, stamp, glyphs):
        self.store, self.log, self.stamp, self.glyphs = store, log, stamp, glyphs
        self.saves = 0; self.t_saved = -1e9; self.off = False
        self.reset()

    def reset(self):
        """leaving IDLE: a match started (its rule screen was seen) or is being recorded"""
        self.ring = collections.deque()           # (t, small frame)
        self.partial = collections.deque()        # (t, rule_checks) of samples passing 1 or 2 of the 3 checks
        self.best = None                          # (key, t, rule_checks, full frame): the closest to a rule screen
        self.t0 = None                            # first IDLE sample
        self.t_box = -1e9; self.t_run = None      # last sample with the timer box, start of its current run
        self.reads = []; self.decided = False     # readable timer values of the current run: (t, rem, clock)
        self.t_try = -1e9                         # last read
        self.t_read = -1e9                        # last readable timer before the current run
        self.n = collections.deque()              # sample times of the last 10 s (rate)
        self.t_checks = -1e9                      # last sample whose rule checks were taken

    def idle(self, f, t, scr=None):
        """one IDLE sample. A diagnostic must never stop the recorder: an error is logged once and the watcher turns off"""
        if self.off: return
        try: self._idle(f, t, scr)
        except Exception as e:
            self.off = True; self.log(f'[{t:8.1f}] rule-miss diagnostics turned off after an error: {e!r}')

    def _idle(self, f, t, scr):
        if self.t0 is None: self.t0 = t
        n = self.n; n.append(t)
        while n and t - n[0] > 10: n.popleft()
        if not self.ring or t - self.ring[-1][0] >= RING_STEP - 0.05: self.ring.append((t, cv2.resize(f, RING_SIZE, interpolation=cv2.INTER_LINEAR)))   # 0.5 ms (INTER_AREA: 6 ms)
        while self.ring and t - self.ring[0][0] > RING_SECONDS: self.ring.popleft()
        if t - self.t_checks >= CHECK_STEP - 0.05:                    # every 3rd sample: a rule screen lasts 2.0-6.5 s
            self.t_checks = t
            c = rule_checks(f); k = c['tag'] + c['desc'] + c['ids']
            if 0 < k < 3: self.partial.append((t, c))
            key = (k, sum(x >= 100 for x in c['id_contrast']), -abs(c['tag_dark'] - 0.84))
            if self.best and t - self.best[1] > RING_SECONDS: self.best = None
            if k and (self.best is None or key > self.best[0]): self.best = (key, t, c, f.copy())   # a copy only when closer
        while self.partial and t - self.partial[0][0] > RING_SECONDS: self.partial.popleft()
        if scr is not None or not timer_box(f): return              # scr: the screen classify() saw (result, judge...), never the HUD
        if t - self.t_box > RUN_GAP:                                  # a new run of the timer box
            if self.reads: self.t_read = self.reads[-1][0]
            self.t_run = t; self.reads = []; self.decided = False
        self.t_box = t
        if self.decided: return
        if not self.reads and t - self.t_run > RUN_READ and t - self.t_try < SLOW_READ - 0.05: return   # a box that does not read (the result screen
        self.t_try = t                                                # has one): a read every SLOW_READ s only
        rem, clock, _ = hud.read_timer(f, self.glyphs)
        if rem is not None: self.reads.append((t, rem, clock))
        if len(self.reads) >= 2:                                      # decided by its first two reads
            self.decided = True; first = self.reads[0][0]
            if (all(any(a <= r <= b for a, b in START) for _, r, _ in self.reads[:2])
                    and first - self.t_read >= NO_HUD and first - self.t0 >= NO_HUD):
                self.missed(f, t, self.reads[0][2])

    def missed(self, f, t, clock):
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY); lo, hi = np.percentile(g, (0.5, 99.5))
        rate = (len(self.n) - 1) / (self.n[-1] - self.n[0]) if len(self.n) > 1 and self.n[-1] > self.n[0] else 0.0
        fails = collections.Counter(k for _, c in self.partial for k in ('tag', 'desc', 'ids') if not c[k])
        msg = (f'[{t:8.1f}] RULE SCREEN MISSED? the battle timer at {clock} while IDLE: no rule screen was recognised before it. '
               f'frame {f.shape[1]}x{f.shape[0]}, grey 0.5-99.5% {lo:.0f}-{hi:.0f}, {rate:.1f} samples/s, detail ratio {detail(f):.2f} '
               f'(native 1080p 0.74-0.77, scaled up from 720p 0.58-0.71); last {RING_SECONDS:.0f} s: {len(self.partial)} samples passed 1-2 of the 3 rule checks'
               + (f' (failed: {", ".join(f"{k} {v}" for k, v in fails.most_common())})' if fails else ''))
        if self.best: msg += f'; closest {self.best[1] - t:+.1f} s: {describe(self.best[2])}'
        if self.saves >= MAX_SAVES or t - self.t_saved < SAVE_GAP:
            self.log(msg + ' (frames not saved: limit)'); return
        self.saves += 1; self.t_saved = t; ts = self.stamp(t) + '_rule_missed'
        tiles = [fr for _, fr in self.ring]
        while len(tiles) % 6: tiles.append(np.zeros_like(tiles[0]))
        paths = [self.store.save_evidence(ts, np.vstack([np.hstack(tiles[i:i + 6]) for i in range(0, len(tiles), 6)]))]
        paths.append(self.store.save_image(ts, 'hud', f))
        if self.best: paths.append(self.store.save_image(ts, f'closest{self.best[1] - t:+.1f}s', self.best[3]))
        self.log(msg + ' -> ' + ', '.join(paths))
