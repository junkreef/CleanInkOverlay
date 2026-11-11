import React, { useEffect, useRef, useState } from 'react'
import { api, clockLabel, post, subscribe } from './api.js'
import MatchList from './components/MatchList.jsx'
import MatchDetail from './components/MatchDetail.jsx'
import Stats from './components/Stats.jsx'
import Signatures from './components/Signatures.jsx'
import SessionPicker from './components/SessionPicker.jsx'

const TABS = [['matches', '試合'], ['stats', '統計'], ['signatures', '未知のステージ・表彰']]

function route() {
  const h = location.hash.replace(/^#\/?/, '')
  const [tab, id] = h.split('/')
  return { tab: tab || 'matches', id: id ? Number(id) : null }
}

// recorder on/off, device choice, last log lines
function RecorderPanel({ recorder, onChange }) {
  const [open, setOpen] = useState(false)
  const [devices, setDevices] = useState([])
  const [device, setDevice] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { if (open) api('/api/recorder/devices').then(setDevices).catch(() => setDevices([])) }, [open])
  const start = async () => { setBusy(true); try { onChange(await post('/api/recorder/start', { device: device === '' ? null : Number(device) })) } finally { setBusy(false) } }
  const stop = async () => { setBusy(true); try { onChange(await post('/api/recorder/stop', {})) } finally { setBusy(false) } }
  const running = recorder?.running
  return (
    <div className="recorder">
      <button className={running ? 'danger' : ''} onClick={running ? stop : start} disabled={busy}>{running ? '■ 記録停止' : '● 記録開始'}</button>
      <span className={`rec ${running ? '' : 'off'}`} onClick={() => setOpen(!open)} title="ログを表示">
        {running ? `REC ${recorder.state || ''}` : recorder?.error ? `停止 (${recorder.error})` : '停止中'}
      </span>
      {open && (
        <div className="recpanel">
          <div className="toolbar">
            <label>デバイス
              <select value={device} onChange={(e) => setDevice(e.target.value)} disabled={running}>
                <option value="">自動 (OBS Virtual Camera)</option>
                {devices.map((d) => <option key={d.index} value={d.index}>{d.index}: {d.name}</option>)}
              </select>
            </label>
            <span className="muted">{recorder?.dry ? 'dry (DB 書き込みなし)' : ''}</span>
          </div>
          <pre>{(recorder?.log || []).slice(-25).join('\n') || 'ログなし'}</pre>
        </div>
      )}
    </div>
  )
}

// the start of the 配信セッション in the header; click opens the picker, Esc / outside click closes it
function SessionChip({ start, conn, matchCount, onApply }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  useEffect(() => {
    if (!open) return
    const down = (e) => { if (!ref.current?.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', down)
    return () => document.removeEventListener('mousedown', down)
  }, [open])
  return (
    <div className="session" ref={ref}>
      <span className={`sess ${conn ? '' : 'off'}`} onClick={() => setOpen(!open)} title={conn ? '配信セッションの開始時刻。クリックで変更' : '切断中'}>
        セッション {start ? `${clockLabel(start)}〜` : '-'}
      </span>
      {open && <SessionPicker start={start} conn={conn} matchCount={matchCount} onApply={onApply} onClose={() => setOpen(false)} />}
    </div>
  )
}

export default function App() {
  const [r, setR] = useState(route())
  const [summary, setSummary] = useState(null)
  const [conn, setConn] = useState(false)
  const [recorder, setRecorder] = useState(null)
  const [toast, setToast] = useState(null)
  const [sessionStart, setSessionStart] = useState(null)
  const session = useRef(null)                                  // the same, for the WebSocket handler
  const toastTimer = useRef(null)

  const flash = (text, ms = 4000, action = null) => {
    clearTimeout(toastTimer.current); setToast({ text, action })
    toastTimer.current = setTimeout(() => setToast(null), ms)
  }
  const showSession = (iso) => { session.current = iso; setSessionStart(iso) }
  const undoTo = (prev) => ({ label: '元に戻す', run: () => post('/api/overlay/session', { start: prev }).then((v) => { showSession(v.session_start); flash(`配信セッションを ${clockLabel(prev)} に戻しました`) }).catch((e) => flash(`変更できませんでした: ${e.message}`, 6000)) })
  const changeSession = async (iso) => {
    const prev = session.current
    const v = await post('/api/overlay/session', iso ? { start: iso } : {})
    showSession(v.session_start)
    flash(`配信セッションを ${clockLabel(v.session_start)} から数え直しました`, 8000, prev ? undoTo(prev) : null)
  }

  useEffect(() => {
    const onHash = () => setR(route())
    addEventListener('hashchange', onHash)
    return () => removeEventListener('hashchange', onHash)
  }, [])

  const refreshSummary = () => api('/api/summary').then(setSummary).catch(() => {})
  useEffect(() => { refreshSummary() }, [r.tab])

  useEffect(() => subscribe((msg) => {
    if (msg.type === 'connected') {
      setConn(true); api('/api/recorder').then(setRecorder).catch(() => {})
      api('/api/overlay?limit=1').then((d) => {                 // a reconnect with another start: the backend restarted (the start is not stored)
        const prev = session.current; showSession(d.session_start)
        if (prev && prev !== d.session_start) flash(`バックエンドが再起動したためセッションは ${clockLabel(d.session_start)} からになっています`, 8000, undoTo(prev))
      }).catch(() => {})
    }
    if (msg.type === 'disconnected') setConn(false)
    if (msg.type === 'hello') setRecorder(msg.recorder)
    if (msg.type === 'recorder') setRecorder(msg)
    if (msg.type === 'session') showSession(msg.start)
    if (msg.type === 'match_saved') { flash(`試合 #${msg.id} を記録しました`, 6000); refreshSummary() }
    if (msg.type === 'signatures_changed') refreshSummary()
  }), [])

  // while recording, refresh the status (state / log) every few seconds
  useEffect(() => {
    if (!recorder?.running) return
    const t = setInterval(() => api('/api/recorder').then(setRecorder).catch(() => {}), 3000)
    return () => clearInterval(t)
  }, [recorder?.running])

  return (
    <div className="app">
      <header>
        <h1 title={summary?.version ? `バージョン ${summary.version}` : undefined}><a href="#/matches">CleanInkOverlay</a></h1>
        <nav>
          {TABS.map(([k, label]) => (
            <a key={k} href={`#/${k}`} className={r.tab === k ? 'active' : ''}>
              {label}
              {k === 'signatures' && (summary?.unlabelled_signatures || summary?.unknown_weapon_icons) ? <span className="badge">{(summary.unlabelled_signatures || 0) + (summary.unknown_weapon_icons || 0)}</span> : null}
            </a>
          ))}
        </nav>
        <div className="status">
          {summary && <span>{summary.matches} 試合 / {summary.wins} 勝</span>}
          <a className="overlay-link" href="/overlay" target="_blank" rel="noopener" title="OBS のブラウザソースに貼る URL (1920x1080)">配信UI</a>
          <SessionChip start={sessionStart} conn={conn} matchCount={summary?.matches} onApply={changeSession} />
          <span className={`dot ${conn ? 'on' : 'off'}`} title={conn ? '接続中' : '切断'} />
          <RecorderPanel recorder={recorder} onChange={setRecorder} />
        </div>
      </header>
      {toast && <div className="toast">{toast.text}{toast.action && <button onClick={toast.action.run}>{toast.action.label}</button>}</div>}
      <main>
        {r.tab === 'matches' && (r.id ? <MatchDetail id={r.id} /> : <MatchList />)}
        {r.tab === 'stats' && <Stats sessionStart={sessionStart} />}
        {r.tab === 'signatures' && <Signatures />}
      </main>
    </div>
  )
}
