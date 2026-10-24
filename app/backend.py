"""Component 3 - web backend: REST + WebSocket for the frontend, and (optionally) the live recorder as a thread.

    uv run python -m app.backend                     # http://127.0.0.1:8000  (serves web/dist when it has been built)
    uv run python -m app.backend --live [--device N] # also start the recorder on the OBS Virtual Camera
    options: --db PATH  --port N  --host H  --dry
    settings: config.toml (optional; config.example.toml lists them), e.g. how many days of screen images to keep

REST  (all JSON)
  GET  /api/summary                       counts, last match id, unlabelled signature count
  GET  /api/matches?limit=&offset=        newest first, with my row
  GET  /api/matches/{id}                  match + players + events + medals
  DELETE /api/matches/{id}
  GET  /api/stats?since=&mode=            the stat tables (overview / weapon / stage / enemy weapon / medal / timeline / daily)
                                          + newest results; since = 'all' (default), 'today', 'session', '7d', ISO time
  GET  /api/signatures/unlabelled         stage / medal signatures without a label (+ where they were seen)
  POST /api/signatures/label {id,label};   POST /api/signatures/prune   drop unlabelled signatures no saved screen shows
  GET  /api/weapon_icons/unknown          weapon icons matching no template, one group per look (+ samples, where seen)
  POST /api/weapon_icons/label {id,name}  name a group: its samples join the weapon's template, its matches get the weapon
  GET  /api/weapons                       main weapon names (to pick from when naming an icon)
  GET  /api/recorder                      recorder thread status + last log lines
  POST /api/recorder/start {device?,dry?} start the live recorder (device = DirectShow index, default: OBS Virtual Camera)
  POST /api/recorder/stop                 stop it;   GET /api/recorder/devices   list capture devices
  GET  /files/{path}                      images under samples/ (and the icon samples under data/icon_samples/)
  GET  /api/overlay?since=                stream overlay data: session totals + recent matches (since = ISO time, 'today', 'all';
                                          default = the session start, which is the backend launch or the last POST below)
  POST /api/overlay/session {start?}      (re)start the overlay session: start = ISO time, or omitted/null = now
  GET  /overlay                           the OBS browser-source page (web/overlay.html; 1920x1080, game goes top-left at 1280x720)
WS    /ws                                 {"type": "match_saved", "id": N} / {"type": "signatures_changed", ..} /
                                          {"type": "weapon_icons_changed", ..} / {"type": "recorder", ...}
Pushes come from the store's in-process events (recorder in the same process) and, as a fallback for a
recorder running elsewhere, from a 1 s watch on the newest match id.
"""
import argparse, asyncio, os, sys, json, time
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path: sys.path.insert(0, ROOT)
from app import config
from app.store import Store
from app.recorder import RecorderRunner

WEB_DIST = os.path.join(ROOT, 'web', 'dist')
state = {'store': None, 'runner': None, 'clients': set(), 'queue': None, 'loop': None, 'last_id': 0, 'db_path': None, 'live': False, 'device': None, 'dry': False, 'session_start': None}


def store() -> Store:
    if state['store'] is None:
        state['store'] = Store(db_path=state['db_path'])
    return state['store']


# ------------------------------------------------------------------ push
def push(msg):
    """called from any thread"""
    loop, q = state['loop'], state['queue']
    if loop and q: loop.call_soon_threadsafe(q.put_nowait, msg)


async def broadcaster():
    q = state['queue']
    while True:
        msg = await q.get(); dead = []
        for ws in list(state['clients']):
            try: await ws.send_json(msg)
            except Exception: dead.append(ws)
        for ws in dead: state['clients'].discard(ws)


async def db_watch():
    """fallback for a recorder in another process: announce new match ids"""
    while True:
        await asyncio.sleep(1.0)
        try:
            last = await asyncio.to_thread(store().last_match_id)
            if last > state['last_id']:
                for mid in range(state['last_id'] + 1, last + 1): push({'type': 'match_saved', 'id': mid, 'via': 'watch'})
                state['last_id'] = last
        except Exception as e:
            print('db watch:', repr(e), flush=True)


async def prune_images():
    """keep samples/ from growing: drop screen / evidence images older than config.toml's images.keep_days (default 7;
    Store.prune_images)"""
    try:
        days = config.image_keep_days()
        gone = await asyncio.to_thread(store().prune_images, days)
        if gone: print(f'pruned {len(gone)} images older than {days} days', flush=True)
    except Exception as e:
        print('prune images:', repr(e), flush=True)


@asynccontextmanager
async def lifespan(app):
    state['loop'] = asyncio.get_running_loop(); state['queue'] = asyncio.Queue()
    s = store(); state['last_id'] = s.last_match_id(); state['session_start'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    s.events.subscribe('match_saved', lambda p: (state.__setitem__('last_id', max(state['last_id'], p['id'])), push({'type': 'match_saved', 'id': p['id']})))
    s.events.subscribe('match_deleted', lambda p: push({'type': 'match_deleted', 'id': p['id']}))
    s.events.subscribe('signatures_changed', lambda p: push({'type': 'signatures_changed', **p}))
    s.events.subscribe('weapon_icons_changed', lambda p: push({'type': 'weapon_icons_changed', **p}))
    asyncio.create_task(broadcaster()); asyncio.create_task(db_watch())
    asyncio.create_task(prune_images())
    state['runner'] = RecorderRunner(s, device=state['device'], dry=state['dry'], on_change=lambda st: push({'type': 'recorder', **st}))
    if state['live']: state['runner'].start()
    yield
    if state['runner']: state['runner'].shutdown()


app = FastAPI(title='CleanInkOverlay', lifespan=lifespan)


# ------------------------------------------------------------------ REST
@app.get('/api/summary')
def api_summary():
    return store().summary()


@app.get('/api/matches')
def api_matches(limit: int = 50, offset: int = 0):
    return store().list_matches(limit, offset)


@app.get('/api/matches/{mid}')
def api_match(mid: int):
    m = store().get_match(mid)
    if m is None: raise HTTPException(404, 'no such match')
    return m


@app.delete('/api/matches/{mid}')
def api_delete_match(mid: int):
    if store().get_match(mid) is None: raise HTTPException(404, 'no such match')
    store().delete_match(mid); return {'ok': True}


@app.get('/api/stats')
def api_stats(since: str | None = None, mode: str | None = None):
    """since: omitted / 'all' = every match, else as the overlay's (ISO time, 'today', 'session', 'Nd')"""
    return store().stats(None if since in (None, '', 'all') else resolve_since(since), mode or None)


@app.get('/api/signatures/unlabelled')
def api_signatures(kind: str | None = None):
    s = store(); out = s.unlabelled_signatures(kind)
    for it in out: it['seen'] = s.signature_examples(it['id'])
    return out


class SigLabel(BaseModel):
    id: str
    label: str


@app.post('/api/signatures/label')
def api_signature_label(body: SigLabel):
    try: store().label_signature(body.id, body.label.strip())
    except KeyError: raise HTTPException(404, 'no such signature')
    return {'ok': True}


@app.post('/api/signatures/prune')
def api_signature_prune():
    gone = store().prune_signatures(); return {'deleted': len(gone), 'ids': gone}


@app.get('/api/weapon_icons/unknown')
def api_weapon_icons_unknown():
    return store().unknown_weapon_icons()


class IconLabel(BaseModel):
    id: str
    name: str


@app.post('/api/weapon_icons/label')
def api_weapon_icon_label(body: IconLabel):
    try: store().label_weapon_icon(body.id, body.name.strip())
    except KeyError: raise HTTPException(404, 'no such icon group')
    except ValueError: raise HTTPException(400, 'bad weapon name')
    return {'ok': True}


@app.get('/api/weapons')
def api_weapons():
    return store().weapon_names()


@app.get('/api/recorder')
def api_recorder():
    r = state['runner']
    return r.status() if r else {'running': False, 'state': None, 'log': []}


class RecorderStart(BaseModel):
    device: int | None = None
    dry: bool | None = None


@app.post('/api/recorder/start')
def api_recorder_start(body: RecorderStart):
    r = state['runner']
    if r.running: return r.status()
    r.start(device=body.device, dry=body.dry); time.sleep(0.5)      # long enough for an immediate failure (no device) to show
    return r.status()


@app.post('/api/recorder/stop')
def api_recorder_stop():
    r = state['runner']; r.shutdown(); return r.status()


@app.get('/api/recorder/devices')
def api_recorder_devices():
    from app.recorder import list_devices
    return list_devices()


# ------------------------------------------------------------------ stream overlay (OBS browser source)
OVERLAY_HTML = os.path.join(ROOT, 'web', 'overlay.html')


def resolve_since(since: str | None):
    """query value -> ISO local time or None (= all matches)"""
    if since is None or since in ('', 'session'): return state['session_start']
    if since == 'all': return None
    if since == 'today': return time.strftime('%Y-%m-%dT00:00:00')
    if since[:-1].isdigit() and since.endswith('d'):                  # '7d' = today and the 6 days before it
        return time.strftime('%Y-%m-%dT00:00:00', time.localtime(time.time() - (int(since[:-1]) - 1) * 86400))
    return since


@app.get('/api/overlay')
def api_overlay(since: str | None = None, limit: int = 8):
    out = store().overlay(resolve_since(since), limit)
    r = state['runner']
    out['recorder'] = {'running': r.running, 'state': r.status()['state']} if r else {'running': False, 'state': None}
    out['session']['since'] = resolve_since(since); out['session_start'] = state['session_start']
    return out


class SessionStart(BaseModel):
    start: str | None = None


@app.post('/api/overlay/session')
def api_overlay_session(body: SessionStart):
    state['session_start'] = body.start or time.strftime('%Y-%m-%dT%H:%M:%S')
    push({'type': 'session', 'start': state['session_start']})
    return {'session_start': state['session_start']}


@app.get('/overlay')
def overlay_page():
    if not os.path.exists(OVERLAY_HTML): raise HTTPException(404, 'web/overlay.html is missing')
    return FileResponse(OVERLAY_HTML, media_type='text/html')


@app.get('/files/{path:path}')
def api_file(path: str):
    p = store().file_path(path)
    if p is None: raise HTTPException(404, 'no such file')
    return FileResponse(p)


# ------------------------------------------------------------------ WebSocket
@app.websocket('/ws')
async def ws_endpoint(ws: WebSocket):
    await ws.accept(); state['clients'].add(ws)
    try:
        await ws.send_json({'type': 'hello', 'last_id': state['last_id'], 'recorder': state['runner'].status() if state['runner'] else None})
        while True:
            await ws.receive_text()                         # clients may send pings; nothing to parse
    except WebSocketDisconnect:
        pass
    finally:
        state['clients'].discard(ws)


# ------------------------------------------------------------------ frontend
if os.path.isdir(WEB_DIST):
    app.mount('/', StaticFiles(directory=WEB_DIST, html=True), name='web')
else:
    @app.get('/')
    def no_frontend():
        return JSONResponse({'message': 'frontend not built: cd web && npm install && npm run build', 'api': '/docs'})


def main():
    import uvicorn
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--host', default='127.0.0.1'); ap.add_argument('--port', type=int, default=8000)
    ap.add_argument('--db'); ap.add_argument('--live', action='store_true'); ap.add_argument('--device', type=int); ap.add_argument('--dry', action='store_true')
    a = ap.parse_args()
    state.update(db_path=os.path.abspath(a.db) if a.db else None, live=a.live, device=a.device, dry=a.dry)
    uvicorn.run(app, host=a.host, port=a.port, log_level='info')


if __name__ == '__main__':
    main()
