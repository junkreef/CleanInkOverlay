"""Start-up for the release package (the zip from GitHub Releases; its CleanInkOverlay.bat runs this with the bundled
Python). A git checkout leaves these steps to the developer; a release user has no command line, so they happen here:

- the data folder is %LOCALAPPDATA%\\CleanInkOverlay (CLEANINK_HOME overrides it), never the program folder: a new
  version is unpacked anywhere and finds the same records (app.paths)
- an existing DB is migrated to this version's schema, after a backup next to it (app.db.upgrade)
- everything printed also goes to <data folder>\\logs\\<start time>.log (the newest LOGS_KEPT are kept)
- the browser opens once the server answers; a second start only opens the browser

    runtime\\python\\python.exe -X utf8 -m app.launch [--live] [--device N] [--port N] [--no-browser]

Options this module does not know go to app.backend. Messages are for the user, so they are Japanese.
"""
import argparse, json, os, shutil, socket, sys, threading, time, traceback, urllib.request, webbrowser

APP = 'CleanInkOverlay'
LOGS_KEPT = 20


def data_home(env=None):
    env = os.environ if env is None else env
    if env.get('CLEANINK_HOME'): return os.path.abspath(env['CLEANINK_HOME'])
    return os.path.join(env.get('LOCALAPPDATA') or os.path.join(os.path.expanduser('~'), 'AppData', 'Local'), APP)


class Tee:
    """a stream that also writes to the log file"""
    def __init__(self, stream, fh):
        self.stream, self.fh = stream, fh

    def write(self, text):
        if self.stream is not None:
            try: self.stream.write(text)
            except Exception: pass
        try: self.fh.write(text)
        except Exception: pass
        return len(text)

    def flush(self):
        for f in (self.stream, self.fh):
            try: f.flush()
            except Exception: pass

    def isatty(self):
        return False

    def __getattr__(self, name):
        return getattr(self.stream, name)


def start_log(home, now=None):
    """send stdout / stderr to a new log file as well; returns its path"""
    d = os.path.join(home, 'logs'); os.makedirs(d, exist_ok=True)
    for old in sorted(f for f in os.listdir(d) if f.endswith('.log'))[:-(LOGS_KEPT - 1)]:
        try: os.remove(os.path.join(d, old))
        except OSError: pass
    p = os.path.join(d, time.strftime('%Y-%m-%d_%H-%M-%S', time.localtime(now)) + '.log')
    fh = open(p, 'a', encoding='utf-8', buffering=1)
    sys.stdout, sys.stderr = Tee(sys.stdout, fh), Tee(sys.stderr, fh)
    return p


def probe(port, host='127.0.0.1'):
    """who answers on the port: 'free' (nobody), 'ours' (a running CleanInkOverlay), 'other'"""
    try:
        socket.create_connection((host, port), timeout=1).close()
    except OSError:
        return 'free'
    try:
        with urllib.request.urlopen(f'http://{host}:{port}/api/summary', timeout=3) as r:
            return 'ours' if 'unlabelled_signatures' in json.load(r) else 'other'
    except Exception:
        return 'other'


def open_when_up(url, port, timeout=60):
    t_end = time.time() + timeout
    while time.time() < t_end:
        if probe(port) == 'ours': webbrowser.open(url); return True
        time.sleep(0.3)
    return False


def migrate(db_path, log=print):
    """bring the DB to this version's schema; False (with a message) when that cannot be done"""
    from app.db import upgrade, current_revision, head_revision, known_revisions
    cur = current_revision(db_path)
    if cur is not None and cur not in known_revisions():      # nothing is touched, not even a backup
        log(f'記録データ ({db_path}) は、このバージョンより新しい {APP} で作られています '
            f'(データ {cur} / このバージョン {head_revision()})。')
        log('最新版をダウンロードして使ってください。')
        return False
    upgrade(db_path, log=log)
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--port', type=int, default=8000); ap.add_argument('--no-browser', action='store_true')
    a, rest = ap.parse_known_args(argv)
    home = data_home(); os.environ['CLEANINK_HOME'] = home; os.makedirs(home, exist_ok=True)
    log_path = start_log(home)
    from app import paths                                     # reads CLEANINK_HOME, so only now
    url = f'http://127.0.0.1:{a.port}'
    print(f'{APP} {paths.version()}')
    print(f'  画面        {url}')
    print(f'  データ      {home}')
    print(f'  ログ        {log_path}', flush=True)
    try:
        who = probe(a.port)
        if who == 'ours':
            print('すでに起動しています。ブラウザで開きます。', flush=True)
            if not a.no_browser: webbrowser.open(url)
            return 0
        if who == 'other':
            print(f'ポート {a.port} をほかのアプリが使っているので起動できません。そのアプリを終了してから、もう一度起動してください。', flush=True)
            return 1
        example = os.path.join(paths.ROOT, 'config.example.toml')
        if os.path.exists(example): shutil.copyfile(example, os.path.join(home, 'config.example.toml'))   # settings: copy to config.toml
        from app.db import DEFAULT_DB
        if not migrate(DEFAULT_DB): return 1
        if not a.no_browser: threading.Thread(target=open_when_up, args=(url, a.port), daemon=True).start()
        print('このウィンドウを閉じると終了します。', flush=True)
        from app import backend
        backend.main(['--port', str(a.port), *rest])
        return 0
    except SystemExit as e:                                   # a bad config.toml value, a bad option, uvicorn giving up
        if e.code not in (None, 0):
            if isinstance(e.code, str): print(e.code)
            print(f'起動できませんでした。ログ: {log_path}', flush=True)
        return 0 if e.code in (None, 0) else 1
    except Exception:
        traceback.print_exc()
        print(f'エラーで終了しました。ログ: {log_path}', flush=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
