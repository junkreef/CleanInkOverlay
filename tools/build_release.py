"""Build the release package: a folder (and its zip) that runs on a Windows PC with nothing installed.

    python tools/build_release.py [--skip-web] [--no-zip] [--expect-version v0.1.0]

    dist/CleanInkOverlay/                        what the zip unpacks to
        CleanInkOverlay.bat, ...                 packaging/ (launchers, the user's read-me)
        app/ work/ assets/ web/ ...              the tracked files a run needs (PROGRAM / NOT_SHIPPED below)
        web/dist/, web/licenses/                 the built web UI and the licences of the packages inside its JavaScript
        runtime/python/                          Python's embeddable package from python.org + the locked dependencies
        THIRD_PARTY_NOTICES.txt                  what is bundled, under which licence
    dist/CleanInkOverlay-v<version>-win64.zip

Needed on the build machine only: git, uv, Node.js (npm); any Python >= 3.11 runs this script. Nothing is installed
on the user's side: the launcher runs runtime\\python\\python.exe -m app.launch. tools/smoke_release.py starts the
result the way a user would. The GitHub workflow (.github/workflows/build.yml) runs both for every push and attaches
the zip to a draft release for a v* tag.

Only tracked files are copied (git ls-files), so local-only material - the wiki icons, samples/, the DB - cannot end
up in a package. The Python version is the one in .python-version, the same the tests run on.
"""
import argparse, hashlib, json, os, shutil, subprocess, sys, tomllib, urllib.request, zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
NAME = 'CleanInkOverlay'
# the embeddable package of each Python we have built with: https://www.python.org/ftp/python/<version>/
# (before adding one: unpack it and check that python.exe carries a valid signature of the Python Software Foundation,
#  PowerShell: Get-AuthenticodeSignature python.exe)
PYTHON_SHA256 = {
    '3.14.7': 'd297e5ff019966817ad8502465176139f2d3d840fa4ed84b13bed399a6ab1f15',
}
PROGRAM = ('app/', 'work/', 'assets/', 'web/overlay.html', 'LICENSE', 'pyproject.toml', 'config.example.toml')
NOT_SHIPPED = ('work/frames/',          # test screens (160 MB)
               'assets/real_icons/')    # reference crops for the developer tools
# opencv-python comes with FFmpeg as a DLL that OpenCV loads to read video files (app.recorder --video needs exactly
# this decoder). It is LGPL, so the package has to say what it is, under which licence, and where it and its source come
# from (notices()). The facts below are OpenCV's own, for the DLL with this checksum:
#   opencv/opencv 3rdparty/ffmpeg/ffmpeg.cmake            the opencv_3rdparty commit of the binaries + their MD5
#   that commit's ffmpeg/download_src.sh                   the tags it was built from
#   the configuration line inside the DLL                  no --enable-gpl, no --enable-nonfree: LGPL 2.1 or later
# After an opencv-python upgrade the checksum differs and the build stops: read those three again and update this.
FFMPEG_PLUGIN = {
    'file': 'cv2/opencv_videoio_ffmpeg500_64.dll',
    'md5': 'a821a1135251859655090c795af05789',
    'parts': 'FFmpeg n7.1, libvpx v1.16.0 and aom v3.14.1',
    'commit': '06dc20cad65dc7fcf784f70c95d46750520889a7',
    'branch': 'ffmpeg/5.x_20260602',
}
PACKAGING = os.path.join(ROOT, 'packaging')
MAX_PATH_IN_ZIP = 150                   # Explorer cannot unpack past 260 characters: leave ~100 for where the user puts it


def run(cmd, **kw):
    print('>', ' '.join(cmd), flush=True)
    return subprocess.run(cmd, check=True, **kw)


def uv():
    exe = shutil.which('uv')
    return [exe] if exe else [sys.executable, '-m', 'uv']


def python_version():
    with open(os.path.join(ROOT, '.python-version'), encoding='ascii') as fh: return fh.read().strip()


def project_version():
    with open(os.path.join(ROOT, 'pyproject.toml'), 'rb') as fh: return tomllib.load(fh)['project']['version']


def tracked_files():
    out = subprocess.run(['git', 'ls-files', '-z'], cwd=ROOT, check=True, capture_output=True).stdout.decode('utf-8')
    return [p for p in out.split('\0') if p]


def copy_program(dst):
    files = [p for p in tracked_files() if p.startswith(PROGRAM) and not p.startswith(NOT_SHIPPED)]
    for p in files:
        d = os.path.join(dst, p); os.makedirs(os.path.dirname(d), exist_ok=True); shutil.copyfile(os.path.join(ROOT, p), d)
    for f in os.listdir(PACKAGING):
        if f.endswith('.txt'):                                # for Notepad: CRLF, and a BOM so that older ones take it as UTF-8
            with open(os.path.join(PACKAGING, f), encoding='utf-8') as fh: text = fh.read()
            with open(os.path.join(dst, f), 'w', encoding='utf-8-sig', newline='\r\n') as fh: fh.write(text)
        else:                                                 # batch files: cmd mis-parses them with bare LF line ends
            with open(os.path.join(PACKAGING, f), 'rb') as fh: data = fh.read()
            with open(os.path.join(dst, f), 'wb') as fh: fh.write(data.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n'))
    print(f'program: {len(files)} tracked files + packaging/')


def build_web(dst, skip):
    """web/dist, and web/licenses/<package>.txt for every package the JavaScript bundle is made of (React and what it
    depends on: the bundle itself only carries a one-line banner, the MIT licence wants its text passed on).
    Returns [(package, version, licence)]."""
    web = os.path.join(ROOT, 'web'); npm = shutil.which('npm') or sys.exit('npm (Node.js) is needed to build the web UI')
    if not skip:
        run([npm, 'ci', '--no-audit', '--no-fund'], cwd=web); run([npm, 'run', 'build'], cwd=web)
    if not os.path.exists(os.path.join(web, 'dist', 'index.html')): sys.exit('web/dist is missing: build it (drop --skip-web)')
    shutil.copytree(os.path.join(web, 'dist'), os.path.join(dst, 'web', 'dist'))
    listed = subprocess.run([npm, 'ls', '--omit=dev', '--all', '--parseable'], cwd=web, capture_output=True, text=True, check=True).stdout
    out = []; lic_dir = os.path.join(dst, 'web', 'licenses'); os.makedirs(lic_dir)
    for d in sorted({p.strip() for p in listed.split('\n') if 'node_modules' in p}):
        with open(os.path.join(d, 'package.json'), encoding='utf-8') as fh: meta = json.load(fh)
        texts = [f for f in sorted(os.listdir(d)) if f.upper().startswith(('LICENSE', 'LICENCE'))]
        if not texts: sys.exit(f'{d}: no licence file for a package that is part of the web UI')
        shutil.copyfile(os.path.join(d, texts[0]), os.path.join(lic_dir, meta['name'].replace('/', '_') + '.txt'))
        out.append((meta['name'], meta['version'], str(meta.get('license', '?'))))
    if not out: sys.exit('npm ls listed no packages: run npm ci in web/ (drop --skip-web)')
    return out


def fetch_python(version, cache):
    """the embeddable package (cached under dist/cache), checked against PYTHON_SHA256"""
    name = f'python-{version}-embed-amd64.zip'; p = os.path.join(cache, name)
    if not os.path.exists(p):
        url = f'https://www.python.org/ftp/python/{version}/{name}'
        print('downloading', url, flush=True)
        with urllib.request.urlopen(url) as r, open(p + '.part', 'wb') as fh: shutil.copyfileobj(r, fh)
        os.replace(p + '.part', p)
    with open(p, 'rb') as fh: digest = hashlib.sha256(fh.read()).hexdigest()
    want = PYTHON_SHA256.get(version)
    if want is None: sys.exit(f'{name}: no checksum in PYTHON_SHA256 for {version}; this file has sha256 {digest} - check it, then add it')
    if digest != want: sys.exit(f'{name}: sha256 {digest}, expected {want}')
    return p


def build_runtime(dst, cache):
    """runtime/python: the interpreter, then the dependencies of uv.lock (no dev group) in Lib/site-packages"""
    version = python_version(); py = os.path.join(dst, 'runtime', 'python'); os.makedirs(py)
    with zipfile.ZipFile(fetch_python(version, cache)) as z: z.extractall(py)
    pth = [f for f in os.listdir(py) if f.endswith('._pth')]
    if len(pth) != 1: sys.exit(f'expected one ._pth file in the embeddable package, found {pth}')
    # the ._pth file is the whole sys.path (no PYTHONPATH, no user site-packages, no registry): the standard library,
    # the dependencies, and the program folder two levels up
    with open(os.path.join(py, pth[0]), 'w', encoding='ascii', newline='\r\n') as fh:
        fh.write(f'{pth[0][:-len("._pth")]}.zip\n.\nLib\\site-packages\n..\\..\n')
    req = os.path.join(cache, 'requirements.txt'); site = os.path.join(py, 'Lib', 'site-packages')
    run([*uv(), 'export', '--frozen', '--no-dev', '--no-emit-project', '--no-hashes', '--no-header', '--format', 'requirements-txt', '-o', req],
        cwd=ROOT, stdout=subprocess.DEVNULL)
    run([*uv(), 'pip', 'install', '--quiet', '--target', site, '--python-version', version, '--python-platform', 'x86_64-pc-windows-msvc',
         '--only-binary', ':all:', '--no-deps', '-r', req], cwd=ROOT)
    shutil.rmtree(os.path.join(site, 'bin'), ignore_errors=True)      # console scripts with the build machine's paths in them
    return version


def notices(dst, py_version, web_packages):
    """THIRD_PARTY_NOTICES.txt from the installed packages' metadata (their licence files stay in *.dist-info)"""
    site = os.path.join(dst, 'runtime', 'python', 'Lib', 'site-packages'); rows = []
    for d in sorted(os.listdir(site), key=str.lower):
        meta = os.path.join(site, d, 'METADATA')
        if not d.endswith('.dist-info') or not os.path.exists(meta): continue
        head = {}; classifiers = []
        for line in open(meta, encoding='utf-8', errors='replace'):
            if not line.strip(): break
            k, _, v = line.partition(':'); v = v.strip()
            if k == 'Classifier' and v.startswith('License ::'): classifiers.append(v.split('::')[-1].strip())
            elif k in ('Name', 'Version', 'License-Expression', 'License', 'Home-page') and k not in head: head[k] = v
        lic = head.get('License-Expression') or ', '.join(classifiers) or head.get('License', '').split('\n')[0][:60] or 'see its dist-info folder'
        rows.append((head.get('Name', d), head.get('Version', '?'), lic))
    with open(os.path.join(dst, 'THIRD_PARTY_NOTICES.txt'), 'w', encoding='utf-8', newline='\r\n') as fh:
        fh.write(f'{NAME} is distributed under the MIT licence (LICENSE). This package also contains the software below,\n'
                 'each under its own licence.\n\n'
                 f'Python {py_version} (runtime\\python) - Python Software Foundation License, runtime\\python\\LICENSE.txt\n\n'
                 'Python packages (runtime\\python\\Lib\\site-packages; the licence texts are in each <name>-<version>.dist-info folder):\n\n')
        for name, ver, lic in rows: fh.write(f'  {name} {ver} - {lic}\n')
        f = FFMPEG_PLUGIN
        fh.write('\nFFmpeg\n\n'
                 f'  runtime\\python\\Lib\\site-packages\\{f["file"].replace("/", chr(92))} is {f["parts"]},\n'
                 '  built by the OpenCV project without GPL or non-free parts and passed on here unchanged, as it comes with\n'
                 '  opencv-python. It is licensed under the GNU Lesser General Public License, version 2.1 or later; the licence\n'
                 '  text is in cv2\\LICENSE-3RD-PARTY.txt. OpenCV loads the file at run time to read video files, and you may put\n'
                 '  your own build in its place. It was built against the OpenH264 v2.5.0 API headers only: no OpenH264 library\n'
                 '  is included (the plugin uses one if it is installed separately).\n'
                 f'  It comes from https://github.com/opencv/opencv_3rdparty, commit {f["commit"]}\n'
                 f'  (branch {f["branch"]}). In that repository, ffmpeg/download_src.sh fetches the source code it was built\n'
                 '  from and ffmpeg/build_via_docker.sh builds it.\n\n'
                 'opencv-python comes with further libraries inside: see cv2\\LICENSE-3RD-PARTY.txt.\n\n'
                 'JavaScript packages inside the web UI (web\\dist; the licence texts are in web\\licenses):\n\n')
        for name, ver, lic in web_packages: fh.write(f'  {name} {ver} - {lic}\n')
    print(f'notices: Python + {len(rows)} packages, {len(web_packages)} JavaScript packages')


def check(dst):
    """what would only show up on a user's PC: paths too long to unpack, files the program needs"""
    long = [p for p in (os.path.relpath(os.path.join(d, f), os.path.dirname(dst)) for d, _, fs in os.walk(dst) for f in fs) if len(p) > MAX_PATH_IN_ZIP]
    if long: sys.exit(f'{len(long)} paths longer than {MAX_PATH_IN_ZIP} characters, e.g. {max(long, key=len)}')
    for need in ('CleanInkOverlay.bat', 'app/launch.py', 'web/dist/index.html', 'web/overlay.html', 'assets/signatures.json', 'assets/weapons.json',
                 'runtime/python/python.exe', 'runtime/python/Lib/site-packages/cv2', 'runtime/python/Lib/site-packages/uvicorn'):
        if not os.path.exists(os.path.join(dst, need)): sys.exit(f'missing in the package: {need}')
    cv2_dir = os.path.join(dst, 'runtime', 'python', 'Lib', 'site-packages', 'cv2')
    plugins = [f for f in os.listdir(cv2_dir) if 'ffmpeg' in f.lower()]
    if plugins != [os.path.basename(FFMPEG_PLUGIN['file'])]: sys.exit(f'FFmpeg plugins in the package: {plugins}, FFMPEG_PLUGIN describes {FFMPEG_PLUGIN["file"]}')
    with open(os.path.join(cv2_dir, plugins[0]), 'rb') as fh: digest = hashlib.md5(fh.read()).hexdigest()
    if digest != FFMPEG_PLUGIN['md5']: sys.exit(f'{plugins[0]} has MD5 {digest}: not the build FFMPEG_PLUGIN (and so THIRD_PARTY_NOTICES.txt) describes')
    if not os.path.exists(os.path.join(dst, 'web', 'licenses', 'react.txt')): sys.exit('web/licenses/react.txt is missing')
    n = len([f for f in os.listdir(os.path.join(dst, 'assets', 'weapon_icons_captured')) if f.endswith('.png')])
    if n < 170: sys.exit(f'only {n} weapon icon templates in the package')


def make_zip(dst, path):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for d, _, files in os.walk(dst):
            for f in files:
                p = os.path.join(d, f); z.write(p, os.path.relpath(p, os.path.dirname(dst)).replace(os.sep, '/'))
    print(f'{path}: {os.path.getsize(path) / 2**20:.0f} MB')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--skip-web', action='store_true', help='use web/dist as it is instead of running npm')
    ap.add_argument('--no-zip', action='store_true'); ap.add_argument('--out', default=os.path.join(ROOT, 'dist'))
    ap.add_argument('--expect-version', help='fail unless pyproject.toml has this version (a leading v is ignored): the tag of a release')
    a = ap.parse_args()
    version = project_version()
    if a.expect_version and a.expect_version.lstrip('v') != version:
        sys.exit(f'pyproject.toml says version {version}, expected {a.expect_version}')
    if subprocess.run(['git', 'status', '--porcelain'], cwd=ROOT, capture_output=True, text=True).stdout.strip():
        print('WARNING: uncommitted changes - the package gets the files as they are on disk', flush=True)
    out = os.path.abspath(a.out); dst = os.path.join(out, NAME); cache = os.path.join(out, 'cache')
    shutil.rmtree(dst, ignore_errors=True); os.makedirs(dst); os.makedirs(cache, exist_ok=True)
    copy_program(dst)
    web_packages = build_web(dst, a.skip_web)
    notices(dst, build_runtime(dst, cache), web_packages)
    check(dst)
    size = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(dst) for f in fs)
    print(f'{dst}: {NAME} {version}, {size / 2**20:.0f} MB')
    if not a.no_zip: make_zip(dst, os.path.join(out, f'{NAME}-v{version}-win64.zip'))


if __name__ == '__main__':
    main()
