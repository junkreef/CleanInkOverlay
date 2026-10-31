"""Rule screen (試合開始時の 8 枚のプレイヤーカード): card order = HUD order, card images, the rule name.

Left column = ally (HUD slots 0-3, top to bottom), right column = enemy (slots 4-7). The card images are
matched against the death bubble during the match to find who killed the player.
The rule name stands in the middle, in big white letters on a black ink splat under a 「ルール」 tag (two lines,
e.g. ナワバリ / バトル, ガチ / ヤグラ; the one-line catchphrase under it is left out). title_signature() reads it like
the result banner (signature kind 'title', named once in the Web UI); the recorder picks the analysis by that name.
In a フェスマッチ each card has its player's rank and team above it (「ふつうのナイト派」), so the cards stand further
apart (FEST_CARD_TOPS). card_tops() tells the two layouts by that text.
"""
import cv2, numpy as np, os, sys

CARD_TOPS = [285, 435, 585, 735]; CARD_X = {'ally': 10, 'enemy': 1450}; CARD_W, CARD_H = 460, 135
FEST_CARD_TOPS = [195, 395, 595, 795]   # killer bubbles score best here (of ±8 px, 4 bubbles of 2026-10-31: 0.91-0.96), x as usual
FEST_TEAM = ((158, 194, 20, 225), (158, 194, 1635, 1885))   # y0, y1, x0, x1: the first text of each column, above the top cards
FEST_TEAM_MIN = 0.06              # share of white px on the black outline: 0.13-0.19 on 3 フェスマッチ screens, <= 0.03 on 310 others
ID_BAND = (118, 142, 12, 75)      # '#nnnn'
STAGE_TEXT = (990, 1050, 1500, 1900)
TITLE = (380, 625, 740, 1180)     # y0, y1, x0, x1: both lines of the rule name (y 387-610 measured), centred around x 960
TITLE_SCALE = 0.25                # signature = the masked canvas at quarter resolution (61x110)
TITLE_MIN_PX = 400                # fewer white px = no rule name there (a two-line name has several thousand)


def card_tops(f):
    """the top of each row of cards: FEST_CARD_TOPS when the text above the cards is there on both sides"""
    for y0, y1, x0, x1 in FEST_TEAM:
        reg = f[y0:y1, x0:x1]
        m = (reg.min(axis=2) > 200) & (reg.max(axis=2).astype(int) - reg.min(axis=2).astype(int) < 40)
        m &= cv2.dilate((reg.max(axis=2) < 70).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
        if m.mean() < FEST_TEAM_MIN: return CARD_TOPS
    return FEST_CARD_TOPS


def card_rect(f, team, i, tops):
    t, x0 = tops[i], CARD_X[team]
    return f[t:t + CARD_H, x0:x0 + CARD_W]


def read_cards(f):
    """-> list of 8 dicts in HUD slot order: team, slot, card (BGR crop), id_crop"""
    out = []; tops = card_tops(f)
    for team in ('ally', 'enemy'):
        for i in range(4):
            c = card_rect(f, team, i, tops)
            out.append(dict(team=team, slot=len(out), card=c.copy(),
                            id_crop=c[ID_BAND[0]:ID_BAND[1], ID_BAND[2]:ID_BAND[3]].copy()))
    return out


def title_signature(f):
    """the rule name on the rule screen -> fixed-size float vector (None when there is none). White, unsaturated px
    next to dark ones (the letters sit on the black splat, so a bright stage behind it does not count), specks dropped,
    on a fixed canvas: the same name always gives the same vector; identified with signatures.Library (kind 'title')"""
    y0, y1, x0, x1 = TITLE; reg = f[y0:y1, x0:x1]
    m = ((reg.min(axis=2) > 190) & ((reg.max(axis=2).astype(int) - reg.min(axis=2).astype(int)) < 40)).astype(np.uint8)
    m &= cv2.dilate((reg.max(axis=2) < 60).astype(np.uint8), np.ones((13, 13), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    for i in range(1, n):
        if stats[i][4] < 30: m[lab == i] = 0
    if m.sum() < TITLE_MIN_PX: return None
    return cv2.resize(m * 255, None, fx=TITLE_SCALE, fy=TITLE_SCALE, interpolation=cv2.INTER_AREA).astype(np.float32).ravel() / 255
