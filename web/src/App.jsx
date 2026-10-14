import React, { useEffect, useState } from 'react'
import { api, post, subscribe } from './api.js'
import MatchList from './components/MatchList.jsx'
import MatchDetail from './components/MatchDetail.jsx'
import Stats from './components/Stats.jsx'
import Signatures from './components/Signatures.jsx'

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

export default function App() {
  const [r, setR] = useState(route())
  const [summary, setSummary] = useState(null)
  const [conn, setConn] = useState(false)
  const [recorder, setRecorder] = useState(null)
  const [toast, setToast] = useState(null)

  useEffect(() => {
    const onHash = () => setR(route())
    addEventListener('hashchange', onHash)
    return () => removeEventListener('hashchange', onHash)
  }, [])

  const refreshSummary = () => api('/api/summary').then(setSummary).catch(() => {})
  useEffect(() => { refreshSummary() }, [r.tab])

  useEffect(() => subscribe((msg) => {
    if (msg.type === 'connected') { setConn(true); api('/api/recorder').then(setRecorder).catch(() => {}) }
    if (msg.type === 'disconnected') setConn(false)
    if (msg.type === 'hello') setRecorder(msg.recorder)
    if (msg.type === 'recorder') setRecorder(msg)
    if (msg.type === 'match_saved') { setToast(`試合 #${msg.id} を記録しました`); refreshSummary(); setTimeout(() => setToast(null), 6000) }
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
        <h1><a href="#/matches">CleanInkOverlay</a></h1>
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
          <button className="secondary small" title="配信オーバーレイの「セッション戦績」を今から数え直す" onClick={() => post('/api/overlay/session', {}).then((r) => { setToast(`配信セッションを ${r.session_start.slice(11, 16)} から開始`); setTimeout(() => setToast(null), 4000) })}>セッション開始</button>
          <span className={`dot ${conn ? 'on' : 'off'}`} title={conn ? '接続中' : '切断'} />
          <RecorderPanel recorder={recorder} onChange={setRecorder} />
        </div>
      </header>
      {toast && <div className="toast">{toast}</div>}
      <main>
        {r.tab === 'matches' && (r.id ? <MatchDetail id={r.id} /> : <MatchList />)}
        {r.tab === 'stats' && <Stats />}
        {r.tab === 'signatures' && <Signatures />}
      </main>
    </div>
  )
}
