import React, { useEffect, useMemo, useRef, useState } from 'react'
import { api, clockLabel } from '../api.js'

// ---- local-time helpers, minute granularity ----
const p2 = (n) => String(n).padStart(2, '0')
const toIso = (d) => `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())}T${p2(d.getHours())}:${p2(d.getMinutes())}:00`
const fmt = (d) => `${d.getFullYear()}/${p2(d.getMonth() + 1)}/${p2(d.getDate())} ${p2(d.getHours())}:${p2(d.getMinutes())}`
const md = (d) => `${d.getMonth() + 1}/${d.getDate()}`
const dayKey = (d) => `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())}`
const dayStart = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate())
const sameDay = (a, b) => dayKey(a) === dayKey(b)
const floorMin = (d) => { const x = new Date(d); x.setSeconds(0, 0); return x }
const withTime = (d, h, m) => { const x = new Date(d); x.setHours(h, m, 0, 0); return x }
const withDate = (d, y, mo, day) => { const x = new Date(d); x.setFullYear(y, mo, day); return x }
const relDay = (d, now) => { const n = Math.round((dayStart(now) - dayStart(d)) / 86400000); return n === 0 ? '今日' : n === 1 ? '昨日' : n === 2 ? '一昨日' : `${n} 日前` }
const WEEK = ['日', '月', '火', '水', '木', '金', '土']

// text -> Date (minute) or null. '09:00' '9:00' '0900' '10/30 23:10' '2026-10-30T23:10:00' '昨日 23:10' '今日 9:00'; full-width digits ok.
// a bare time keeps `base`'s date; 'M/D' that would be in the future means last year
function parseText(text, base) {
  const s = text.trim().replace(/[０-９]/g, (c) => String.fromCharCode(c.charCodeAt(0) - 0xfee0)).replace(/：/g, ':').replace(/／/g, '/').replace(/－/g, '-')
  const m = s.match(/^(?:(昨日|きのう|今日|きょう|(\d{4})[-/](\d{1,2})[-/](\d{1,2})|(\d{1,2})[-/](\d{1,2}))[\sT]+)?(?:(\d{1,2}):(\d{2})|(\d{2})(\d{2}))(?::\d{2})?$/)
  if (!m) return null
  const now = new Date()
  let d
  if (m[1] === '昨日' || m[1] === 'きのう') { d = dayStart(now); d.setDate(d.getDate() - 1) }
  else if (m[1] === '今日' || m[1] === 'きょう') d = dayStart(now)
  else if (m[2]) { d = new Date(+m[2], +m[3] - 1, +m[4]); if (d.getMonth() !== +m[3] - 1) return null }
  else if (m[5]) { d = new Date(now.getFullYear(), +m[5] - 1, +m[6]); if (d.getMonth() !== +m[5] - 1) return null }
  else d = new Date(base)
  const h = +(m[7] ?? m[9]), mi = +(m[8] ?? m[10])
  if (h > 23 || mi > 59) return null
  d.setHours(h, mi, 0, 0)
  if (m[5] && d > now) d.setFullYear(d.getFullYear() - 1)
  return d
}

// re-render now and then so the limit of what is in the future moves on
function useTick(ms = 30000) {
  const [, setTick] = useState(0)
  useEffect(() => { const t = setInterval(() => setTick((n) => n + 1), ms); return () => clearInterval(t) }, [ms])
}

// month grid, 6 rows; days after today disabled; `marks` = Set of dayKey with matches
function Calendar({ value, now, marks, onChange }) {
  const [view, setView] = useState(() => new Date(value.getFullYear(), value.getMonth(), 1))
  useEffect(() => { setView(new Date(value.getFullYear(), value.getMonth(), 1)) }, [value])
  const today = dayStart(now)
  const first = new Date(view); first.setDate(1 - first.getDay())
  const cells = Array.from({ length: 42 }, (_, i) => { const d = new Date(first); d.setDate(first.getDate() + i); return d })
  const atMonth = view.getFullYear() === now.getFullYear() && view.getMonth() === now.getMonth()
  const month = (n) => setView(new Date(view.getFullYear(), view.getMonth() + n, 1))
  const pick = (d) => onChange(withDate(value, d.getFullYear(), d.getMonth(), d.getDate()))
  const key = (e) => {
    const step = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }[e.key]
    if (step) { const d = new Date(value); d.setDate(d.getDate() + step); if (dayStart(d) <= today) onChange(d) }
    else if (e.key === 'PageUp') month(-1)
    else if (e.key === 'PageDown') { if (!atMonth) month(1) }
    else if (e.key === 'Home') pick(today)
    else return
    e.preventDefault()
  }
  return (
    <div className="cal">
      <div className="cal-head">
        <button tabIndex={-1} onClick={() => month(-1)} title="前の月">‹</button>
        <b>{view.getFullYear()}年{view.getMonth() + 1}月</b>
        <button tabIndex={-1} onClick={() => month(1)} disabled={atMonth} title="次の月">›</button>
        <button tabIndex={-1} className="cal-today" onClick={() => pick(today)}>今日</button>
      </div>
      <div className="cal-grid" tabIndex={0} onKeyDown={key} title="矢印で日、PageUp/PageDown で月、Home で今日">
        {WEEK.map((w) => <span key={w} className="wd">{w}</span>)}
        {cells.map((d) => {
          const k = dayKey(d), future = d > today
          const cls = ['cal-day', d.getMonth() !== view.getMonth() ? 'out' : '', sameDay(d, value) ? 'sel' : '', sameDay(d, today) ? 'today' : '', marks.has(k) ? 'has' : ''].join(' ')
          return <button key={k} tabIndex={-1} className={cls} disabled={future} onClick={() => pick(d)} title={marks.has(k) ? `${md(d)} 試合あり` : md(d)}>{d.getDate()}</button>
        })}
      </div>
    </div>
  )
}

// 24-hour face (outer 12-23, inner 0-11) then minutes in 5-minute steps; click only
function Clock({ value, now, mode, onMode, onChange }) {
  const h = value.getHours(), mi = value.getMinutes(), today = sameDay(value, now)
  const hourOk = (hh) => !today || hh <= now.getHours()
  const minOk = (mm) => !today || h < now.getHours() || mm <= now.getMinutes()
  const pos = (frac, r) => { const a = frac * 2 * Math.PI - Math.PI / 2; return [100 + r * Math.cos(a), 100 + r * Math.sin(a)] }
  const pickHour = (hh) => { const d = withTime(value, hh, mi); if (d > now) d.setMinutes(now.getMinutes()); onChange(d); onMode('minute') }
  const pickMin = (mm) => onChange(withTime(value, h, mm))
  const key = (e) => {
    const d = new Date(value)
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { const s = e.key === 'ArrowRight' ? 1 : -1; mode === 'hour' ? d.setHours((h + 24 + s) % 24) : d.setMinutes((mi + 60 + 5 * s) % 60) }
    else if (e.key === 'ArrowUp' || e.key === 'ArrowDown') d.setMinutes((mi + 60 + (e.key === 'ArrowUp' ? 1 : -1)) % 60)
    else if (e.key === ' ') { onMode(mode === 'hour' ? 'minute' : 'hour'); e.preventDefault(); return }
    else return
    e.preventDefault(); if (d <= now) onChange(d)
  }
  const [hx, hy] = mode === 'hour' ? pos((h % 12) / 12, h >= 12 ? 82 : 54) : pos(mi / 60, 82)
  const ticks = mode === 'hour'
    ? Array.from({ length: 24 }, (_, hh) => ({ v: hh, label: p2(hh), xy: pos((hh % 12) / 12, hh >= 12 ? 82 : 54), inner: hh < 12, sel: hh === h, ok: hourOk(hh), go: () => pickHour(hh) }))
    : Array.from({ length: 12 }, (_, i) => ({ v: i * 5, label: p2(i * 5), xy: pos(i / 12, 82), inner: false, sel: i * 5 === mi, ok: minOk(i * 5), go: () => pickMin(i * 5) }))
  return (
    <div className="clk" tabIndex={0} onKeyDown={key} title="←→ で時/分、↑↓ で 1 分、Space で時と分の切替">
      <div className="clk-digits">
        <button tabIndex={-1} className={mode === 'hour' ? 'on' : ''} onClick={() => onMode('hour')}>{p2(h)}</button><span>:</span>
        <button tabIndex={-1} className={mode === 'minute' ? 'on' : ''} onClick={() => onMode('minute')}>{p2(mi)}</button>
      </div>
      <svg viewBox="0 0 200 200">
        <circle className="face" cx="100" cy="100" r="98" />
        <line className="hand" x1="100" y1="100" x2={hx} y2={hy} />
        <circle className="pin" cx="100" cy="100" r="3" /><circle className="pin" cx={hx} cy={hy} r="4" />
        {ticks.map((t) => (
          <g key={t.v} className={`tick ${t.inner ? 'inner' : ''} ${t.sel ? 'sel' : ''} ${t.ok ? '' : 'off'}`} onClick={t.ok ? t.go : undefined}>
            <circle cx={t.xy[0]} cy={t.xy[1]} r={t.inner ? 12 : 13} /><text x={t.xy[0]} y={t.xy[1]}>{t.label}</text>
          </g>
        ))}
      </svg>
      <span className="clk-note">{mode === 'hour' ? '時を選択' : '分を選択（1 分単位は ↑↓ か入力欄）'}</span>
    </div>
  )
}

// start of the 配信セッション: text + calendar + clock + recent matches, all bound to one `value`; 「変更」 / Enter posts it
export default function SessionPicker({ start, conn, matchCount, onApply, onClose }) {
  useTick()
  const now = new Date()
  const [value, setValue] = useState(() => floorMin(new Date(start || Date.now())))
  const [text, setText] = useState(() => fmt(value))
  const [focus, setFocus] = useState(true)
  const [mode, setMode] = useState('hour')
  const [matches, setMatches] = useState([])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const input = useRef(null), change = useRef(null)
  useEffect(() => { input.current?.focus(); input.current?.select() }, [])
  useEffect(() => { api('/api/matches?limit=200').then(setMatches).catch(() => setMatches([])) }, [matchCount])
  const marks = useMemo(() => new Set(matches.map((m) => (m.started_at || '').slice(0, 10))), [matches])

  const set = (d) => { setValue(d); setText(fmt(d)) }
  const parsed = parseText(text, value)
  const empty = text.trim() === '', bad = !empty && !parsed
  const onText = (s) => { setText(s); const d = parseText(s, value); if (d) setValue(d) }
  const future = value > now
  const canApply = conn && !busy && !empty && !bad && !future
  const nudge = (d) => { if (d <= now) set(d) }
  const textKey = (e) => {
    const d = new Date(value)
    if (e.key === 'ArrowUp' || e.key === 'ArrowDown') { const s = e.key === 'ArrowUp' ? 1 : -1; e.shiftKey ? d.setHours(d.getHours() + s) : d.setMinutes(d.getMinutes() + s) }
    else if (e.key === 'PageUp' || e.key === 'PageDown') d.setDate(d.getDate() + (e.key === 'PageUp' ? 1 : -1))
    else return
    e.preventDefault(); nudge(d)
  }
  const apply = async () => {
    if (!canApply) return
    setBusy(true); setErr(null)
    try { await onApply(toIso(value)); onClose() } catch (e) { setErr(`変更できませんでした: ${e.message}`) } finally { setBusy(false) }
  }
  const rootKey = (e) => {
    if (e.key === 'Escape') { e.preventDefault(); onClose() }
    else if (e.key === 'Enter' && !e.target.closest('.sp-foot')) { e.preventDefault(); apply() }   // a day just clicked keeps the focus: Enter still applies
  }
  const showBad = bad && !focus
  const hint = !conn ? ['bad', 'バックエンドに接続していません']
    : showBad ? ['bad', '読み取れません（例: 09:00、10/30 23:10、昨日 23:10）']
    : future ? ['bad', '未来の時刻は指定できません']
    : empty || bad ? ['', '例: 09:00、10/30 23:10、昨日 23:10']
    : ['', <>{relDay(value, now)} {sameDay(value, now) ? '' : `${md(value)} `}<b>{p2(value.getHours())}:{p2(value.getMinutes())}</b> から数え直します</>]

  return (
    <div className="sp" onKeyDown={rootKey}>
      <div className="sp-head"><h3>配信セッションの開始時刻</h3><span className="cur">現在 {start ? clockLabel(start) : '-'}</span></div>
      <div className={`sp-text ${showBad ? 'bad' : ''}`}>
        <input ref={input} value={text} spellCheck={false} placeholder="2026/10/31 09:00" onChange={(e) => onText(e.target.value)} onKeyDown={textKey}
               onFocus={() => setFocus(true)} onBlur={() => { setFocus(false); if (parsed) setText(fmt(parsed)) }} />
      </div>
      <div className={`sp-hint ${hint[0]}`}>{hint[1]}</div>
      <div className="sp-body">
        <Calendar value={value} now={now} marks={marks} onChange={set} />
        <Clock value={value} now={now} mode={mode} onMode={setMode} onChange={set} />
      </div>
      {matches.length > 0 && (
        <div className="sp-picks">試合から:
          {matches.slice(0, 4).map((m) => (
            <button key={m.id} className={m.result || ''} onClick={() => set(floorMin(new Date(m.started_at)))} title={`#${m.id} の開始時刻にする`}>
              #{m.id} {clockLabel(m.started_at)}<i>{{ win: '勝', lose: '負' }[m.result] || ''}</i>
            </button>
          ))}
        </div>
      )}
      <div className="sp-foot">
        <button className="secondary small" onClick={() => { set(floorMin(new Date())); change.current?.focus() }}>今から</button>
        <span className="sp-err">{err}</span>
        <button className="secondary small" onClick={onClose}>閉じる</button>
        <button ref={change} className="small" disabled={!canApply} onClick={apply}>変更</button>
      </div>
    </div>
  )
}
