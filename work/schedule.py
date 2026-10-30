"""「スケジュールが更新されました」: the notice of a schedule change after a match (1080p).

When the schedule changes during a match, the game skips the scoreboard: after the 表彰 panel and the おカネ / ランク
screen it shows this notice on a black splash in the middle (~0.9 s, where the scoreboard would come next), then
saves and goes back to the lobby. Seeing it means the scoreboard will not come, so the recorder stores the match
at once instead of waiting RESULT_WAIT for it (2026-10-28_22-51-57.mp4, 744.3-745.2 s).

The white text sits at y 528-575, x 776-1143 and is told apart by a template of its white mask.

    python work/schedule.py FRAME.png [...]          # print the score
    python work/schedule.py --build FRAME.png        # cut the template from a frame showing the notice
"""
import cv2, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from result_parser import white_mask, dark_share

TPL_PATH = os.path.join(os.path.dirname(__file__), 'templates', 'schedule_updated.png')
AREA = (500, 600, 740, 1180)             # y0, y1, x0, x1: search area around the text (y 528-575, x 776-1143)
CUT = (524, 580, 772, 1148)              # the template's box
DARK_MIN = 0.6                           # share of the area that is the black splash (the notice: 0.81)
THR = 0.7                                # template score
_tpl = []


def template():
    if not _tpl:
        t = cv2.imread(TPL_PATH, 0)
        if t is not None: _tpl.append(t)
    return _tpl[0] if _tpl else None


def score(f):
    """template score of the notice, 0.0 without the black splash (cheap exit for every other frame)"""
    y0, y1, x0, x1 = AREA; box = f[y0:y1, x0:x1]; tpl = template()
    if tpl is None or dark_share(box, 50) < DARK_MIN: return 0.0
    return float(cv2.matchTemplate(white_mask(box, 200) * 255, tpl, cv2.TM_CCOEFF_NORMED).max())


def looks_like_schedule_update(f):
    return score(f) >= THR


def build(path):
    y0, y1, x0, x1 = CUT
    cv2.imwrite(TPL_PATH, white_mask(cv2.imread(path)[y0:y1, x0:x1], 200) * 255); print(TPL_PATH)


if __name__ == '__main__':
    if sys.argv[1] == '--build': build(sys.argv[2]); sys.exit()
    for p in sys.argv[1:]:
        print(os.path.basename(p), round(score(cv2.imread(p)), 3))
