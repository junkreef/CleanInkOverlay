"""Result screen banner reading (mode / rule / stage signatures).
    uv run pytest
"""
import os, sys
import numpy as np
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if os.path.join(ROOT, 'work') not in sys.path: sys.path.insert(0, os.path.join(ROOT, 'work'))
from result_parser import banner_signature, BANNER


def frame_with(*boxes):
    """a black 1080p frame with white boxes (x, y, w, h) on it"""
    f = np.zeros((1080, 1920, 3), np.uint8)
    for x, y, w, h in boxes: f[y:y + h, x:x + w] = 255
    return f


def test_a_speck_in_the_banner_is_no_text():
    b = BANNER['stage']; x, y = b['x'], b['y']
    assert banner_signature(frame_with(), 'stage') is None
    assert banner_signature(np.full((1080, 1920, 3), 128, np.uint8), 'mode') is None         # no dark tag: an empty band, no crash
    assert banner_signature(frame_with((x + 60, y + 8, 5, 5)), 'stage') is None              # 25 px of white, 5 px wide
    words = [(x + i * 22, y + 2, 16, 18) for i in range(5)]                                   # five "glyphs", ~100 px wide
    sig = banner_signature(frame_with(*words), 'stage')
    assert sig is not None and sig.max() > 0.9
