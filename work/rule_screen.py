"""Rule screen (試合開始時の 8 枚のプレイヤーカード): card order = HUD order, card images.

Left column = ally (HUD slots 0-3, top to bottom), right column = enemy (slots 4-7). The card images are
matched against the death bubble during the match to find who killed the player.
"""
import cv2, numpy as np, os, sys

CARD_TOPS = [285, 435, 585, 735]; CARD_X = {'ally': 10, 'enemy': 1450}; CARD_W, CARD_H = 460, 135
ID_BAND = (118, 142, 12, 75)      # '#nnnn'
STAGE_TEXT = (990, 1050, 1500, 1900)


def card_rect(f, team, i):
    t, x0 = CARD_TOPS[i], CARD_X[team]
    return f[t:t + CARD_H, x0:x0 + CARD_W]


def read_cards(f):
    """-> list of 8 dicts in HUD slot order: team, slot, card (BGR crop), id_crop"""
    out = []
    for team in ('ally', 'enemy'):
        for i in range(4):
            c = card_rect(f, team, i)
            out.append(dict(team=team, slot=len(out), card=c.copy(),
                            id_crop=c[ID_BAND[0]:ID_BAND[1], ID_BAND[2]:ID_BAND[3]].copy()))
    return out

