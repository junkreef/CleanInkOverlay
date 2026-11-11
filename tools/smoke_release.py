"""Start a built release package the way a user would, on a PC that has nothing: unpacked into a folder with a
Japanese name and a space (a user's Downloads folder under a Japanese account name), through CleanInkOverlay.bat,
with an environment that knows no Python, git or Node, and an empty user profile. Fails loudly when a page or an API
does not answer, when the package's recorder cannot read the repo's test screens (tools/smoke_frames.py), when the
data does not land in the data folder, or when the program folder gets written to.

    python tools/smoke_release.py [dist/CleanInkOverlay-v<version>-win64.zip | dist/CleanInkOverlay] [--port 8765]

Default: the zip of the version in pyproject.toml. It does not open a capture device or the browser.
"""
import argparse, json, os, shutil, subprocess, sys, tempfile, time, tomllib, urllib.request, zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
NAME = 'CleanInkOverlay'


def get(port, path, timeout=5):
    with urllib.request.urlopen(f'http://127.0.0.1:{port}{path}', timeout=timeout) as r: return r.read()


def snapshot(folder):
    """every file under the folder except Python's own caches -> (size, mtime)"""
    out = {}
    for d, dirs, files in os.walk(folder):
        dirs[:] = [s for s in dirs if s != '__pycache__' and not (s == 'gen' and os.path.basename(d) == 'comtypes')]
        for f in files:
            p = os.path.join(d, f); st = os.stat(p); out[os.path.relpath(p, folder)] = (st.st_size, st.st_mtime_ns)
    return out


def ascii_text(path):
    """a console capture for printing anywhere: cmd's own messages come in the console code page"""
    with open(path, 'rb') as fh: return fh.read().decode('utf-8', 'replace').encode('ascii', 'backslashreplace').decode('ascii')


def main():
    with open(os.path.join(ROOT, 'pyproject.toml'), 'rb') as fh: version = tomllib.load(fh)['project']['version']
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('package', nargs='?', default=os.path.join(ROOT, 'dist', f'{NAME}-v{version}-win64.zip')); ap.add_argument('--port', type=int, default=8765)
    a = ap.parse_args(); src = os.path.abspath(a.package)
    profile = os.path.join(tempfile.mkdtemp(prefix='cleanink-smoke-'), 'ユーザー 名'); downloads = os.path.join(profile, 'ダウンロード', 'new folder')
    home = os.path.join(profile, 'AppData', 'Local', NAME); os.makedirs(downloads); os.makedirs(os.path.dirname(home))
    if os.path.isdir(src): shutil.copytree(src, os.path.join(downloads, NAME))
    else:
        with zipfile.ZipFile(src) as z: z.extractall(downloads)
    folder = os.path.join(downloads, NAME); python = os.path.join(folder, 'runtime', 'python', 'python.exe')
    windir = os.environ.get('SystemRoot', r'C:\Windows')
    env = {'SystemRoot': windir, 'SystemDrive': os.environ.get('SystemDrive', 'C:'), 'ComSpec': os.path.join(windir, 'System32', 'cmd.exe'),
           'PATH': os.path.join(windir, 'System32'), 'PATHEXT': '.COM;.EXE;.BAT;.CMD', 'TEMP': profile, 'TMP': profile,
           'LOCALAPPDATA': os.path.dirname(home), 'APPDATA': os.path.join(profile, 'AppData', 'Roaming'), 'USERPROFILE': profile}
    before = snapshot(folder); console = os.path.join(profile, 'console.txt'); ok = False; proc = None
    try:
        with open(console, 'wb') as log:
            proc = subprocess.Popen([env['ComSpec'], '/c', os.path.join(folder, 'CleanInkOverlay.bat'), '--no-browser', '--port', str(a.port)],
                                    env=env, cwd=profile, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
            t_end = time.time() + 120; summary = None
            while time.time() < t_end and proc.poll() is None:
                try: summary = json.loads(get(a.port, '/api/summary', timeout=2)); break
                except OSError: time.sleep(0.5)
            assert summary is not None, 'the server did not come up'
            assert summary['version'] == version and summary['matches'] == 0, summary
            assert summary['unlabelled_signatures'] == 0 and summary['unknown_weapon_icons'] == 0, summary
            assert b'<div id="root">' in get(a.port, '/'), 'the web UI is not served'
            assert b'adobe-fonts-kit' in get(a.port, '/overlay'), 'the overlay page is not served'
            weapons = json.loads(get(a.port, '/api/weapons')); assert len(weapons) == 174, len(weapons)
            stats = json.loads(get(a.port, '/api/stats')); assert stats['recent'] == [], stats
            devices = json.loads(get(a.port, '/api/recorder/devices', timeout=30)); assert isinstance(devices, list)
            recorder = json.loads(get(a.port, '/api/recorder')); assert recorder['running'] is False
            assert os.path.getsize(os.path.join(home, 'data', 'splatoon.db')) > 0, 'no DB in the data folder'
            assert os.path.exists(os.path.join(home, 'config.example.toml')) and os.listdir(os.path.join(home, 'logs'))
            # the recorder itself, on real screens (the server above has not started one)
            r = subprocess.run([python, '-X', 'utf8', os.path.join(ROOT, 'tools', 'smoke_frames.py'), os.path.join(ROOT, 'work', 'frames')],
                               env=dict(env, CLEANINK_HOME=os.path.join(profile, 'frames home')), cwd=profile, capture_output=True)
            assert r.returncode == 0, 'reading the test screens failed:\n' + (r.stdout + r.stderr).decode('utf-8', 'replace').encode('ascii', 'backslashreplace').decode('ascii')
            read = json.loads(r.stdout.decode('utf-8').strip().split('\n')[-1])
            changed = {p for p, v in snapshot(folder).items() if before.get(p) != v}
            assert not changed, f'the program folder was written to: {sorted(changed)[:10]}'
            print(f'ok: {NAME} {version} from {os.path.basename(src)}, unpacked under a Japanese folder name, answers on port {a.port}; '
                  f'{len(weapons)} weapons, {len(devices)} capture devices listed; test screens read ({read["screens"]}, '
                  f'{read["templates"]} icon templates); data in the data folder only')
            ok = True
    finally:
        if proc is not None:
            subprocess.run(['taskkill', '/F', '/T', '/PID', str(proc.pid)], capture_output=True); proc.wait(timeout=30)
        if not ok:
            print('---- console output ----\n' + ascii_text(console))
            for f in sorted(os.listdir(os.path.join(home, 'logs'))) if os.path.isdir(os.path.join(home, 'logs')) else []:
                print(f'---- {f} ----\n' + ascii_text(os.path.join(home, 'logs', f)))
        shutil.rmtree(os.path.dirname(profile), ignore_errors=True)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
