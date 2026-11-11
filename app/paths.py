"""Where things live: the program and the user's data are two folders that may be the same one.

    ROOT        the program: app/, work/, assets/, web/dist. A release (the zip from GitHub Releases) never writes here,
                so a new version can simply replace the folder.
    DATA_ROOT   what belongs to the user, laid out like the repo: data/splatoon.db, data/icon_samples/, samples/,
                config.toml, and what the user's own labelling adds to the shipped assets (assets/signatures.json,
                assets/weapon_icons_captured/).

In a git checkout both are the repo root, as they always were. The environment variable CLEANINK_HOME moves DATA_ROOT;
the release launcher (app.launch) sets it to %LOCALAPPDATA%\\CleanInkOverlay unless it is set already, so the records
survive deleting or replacing the program folder. It is read once, when this module is imported.
"""
import os, tomllib

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
DATA_ROOT = os.path.abspath(os.environ.get('CLEANINK_HOME') or ROOT)
SPLIT = os.path.normcase(DATA_ROOT) != os.path.normcase(ROOT)     # the program folder is read-only, the data is elsewhere
ASSETS = os.path.join(ROOT, 'assets')


def version():
    """the version in pyproject.toml (shipped with a release too); '?' when the file is missing"""
    try:
        with open(os.path.join(ROOT, 'pyproject.toml'), 'rb') as fh: return tomllib.load(fh)['project']['version']
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return '?'
