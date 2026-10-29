"""Settings that may differ per installation, read from config.toml next to pyproject.toml.

The file is optional and not in git: copy config.example.toml (every setting with its default) and change what you need.
A missing file or key means the default; a bad value stops with a message naming the key.

    from app import config
    config.image_keep_days()      # [images] keep_days
    config.adobe_fonts_kit()      # [overlay] adobe_fonts_kit
"""
import os, tomllib

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
PATH = os.path.join(ROOT, 'config.toml')
DEFAULTS = {'images': {'keep_days': 7}, 'overlay': {'adobe_fonts_kit': ''}}


def load(path=PATH):
    """the settings: DEFAULTS overlaid with the file's values (only known sections / keys)"""
    out = {sec: dict(vals) for sec, vals in DEFAULTS.items()}
    if os.path.exists(path):
        with open(path, 'rb') as fh:
            try: data = tomllib.load(fh)
            except tomllib.TOMLDecodeError as e: raise SystemExit(f'{path}: {e}')
        for sec, vals in data.items():
            if sec not in DEFAULTS or not isinstance(vals, dict): raise SystemExit(f'{path}: unknown section [{sec}]')
            for k, v in vals.items():
                if k not in DEFAULTS[sec]: raise SystemExit(f'{path}: unknown setting {sec}.{k}')
                out[sec][k] = v
    return out


def image_keep_days(path=PATH):
    """days to keep screen PNGs and bubble / miss evidence JPGs (Store.prune_images, run at backend startup)"""
    v = load(path)['images']['keep_days']
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
        raise SystemExit(f'{path}: images.keep_days must be a number of days > 0, not {v!r}')
    return v


def adobe_fonts_kit(path=PATH):
    """Adobe Fonts web project ID for the overlay's number font ('' = none, the overlay uses Rubik)"""
    v = load(path)['overlay']['adobe_fonts_kit']
    if not isinstance(v, str) or not (v == '' or v.isascii() and v.isalnum()):
        raise SystemExit(f'{path}: overlay.adobe_fonts_kit must be a web project ID like "abc1def", not {v!r}')
    return v
