import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { api, subscribe } from '../api.js'

const PERIODS = [['all', '全期間'], ['30d', '30 日'], ['7d', '7 日'], ['today', '今日'], ['session', '配信セッション']]
const EVENT_LABEL = { kill: 'たおした', killed_by: 'やられた', death: 'デス' }
const RANK = { gold: '金', silver: '銀' }

const num = (v, digits) => v == null ? '-' : digits != null ? Number(v).toFixed(digits) : String(v)
const clock = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`

// the filter survives reloads (per browser); storage may be unavailable, then it just starts at 全期間
const loadFilter = () => { try { return JSON.parse(localStorage.getItem('stats.filter')) || {} } catch { return {} } }
const saveFilter = (f) => { try { localStorage.setItem('stats.filter', JSON.stringify(f)) } catch {} }

const ROWS = 10          // rows a card shows; the rest is in the 「すべて表示」 popup

// sort rows by {key, dir}: numbers / text (Japanese order), empty values always last
function sortRows(rows, sort) {
  if (!sort) return rows
  const { key, dir } = sort
  return [...rows].sort((a, b) => {
    const x = a[key], y = b[key]
    if (x == null || y == null) return (x == null) - (y == null)
    return (typeof x === 'number' ? x - y : String(x).localeCompare(String(y), 'ja')) * dir
  })
}

// a table whose headers sort it. cols: [{key, label, num?, digits?, bar?: 'pct' | 'max', render?(row), cls?(row)}]
// numbers sort high-first on the first click, text a-z; dim(row) greys out a row;
// pad = fill up to that many rows with blank ones, so cards with few rows keep the same height
function SortTable({ cols, rows, sort, onSort, dim, limit, pad }) {
  const sorted = useMemo(() => sortRows(rows, sort), [rows, sort])
  const max = useMemo(() => Object.fromEntries(cols.filter((c) => c.bar === 'max').map((c) => [c.key, Math.max(1, ...rows.map((r) => r[c.key] || 0))])), [cols, rows])
  const click = (c) => onSort(sort?.key === c.key ? { key: c.key, dir: -sort.dir } : { key: c.key, dir: c.num ? -1 : 1 })
  const shown = limit ? sorted.slice(0, limit) : sorted
  const blanks = Math.max(0, (pad || 0) - shown.length)
  return (
    <table className="list stat">
      <thead>
        <tr>{cols.map((c) => (
          <th key={c.key} className={`${c.num ? 'num' : ''} ${sort?.key === c.key ? 'sorted' : ''}`} onClick={() => click(c)} title="クリックで並べ替え">
            {c.label}<span className="arrow">{sort?.key === c.key ? (sort.dir > 0 ? '▲' : '▼') : ''}</span>
          </th>
        ))}</tr>
      </thead>
      <tbody>
        {shown.map((r, i) => (
          <tr key={i} className={dim?.(r) ? 'dim' : ''}>
            {cols.map((c) => {
              const v = r[c.key]
              const w = v == null ? 0 : c.bar === 'pct' ? v : c.bar === 'max' ? 100 * v / max[c.key] : 0
              return (
                <td key={c.key} className={`${c.num ? 'num' : ''} ${c.bar ? `bar ${c.bar}` : ''} ${c.cls?.(r) || ''}`} style={c.bar ? { '--w': `${w}%` } : undefined}>
                  {c.render ? c.render(r) : c.num ? num(v, c.digits) : v ?? <i className="muted">不明</i>}
                </td>
              )
            })}
          </tr>
        ))}
        {!rows.length && <tr className="blank"><td colSpan={cols.length} className="muted">データなし</td></tr>}
        {Array.from({ length: blanks - (rows.length ? 0 : 1) }, (_, i) => <tr key={`b${i}`} className="blank"><td colSpan={cols.length}>&nbsp;</td></tr>)}
      </tbody>
    </table>
  )
}

const GAMES = [{ key: 'games', label: '試合', num: true, bar: 'max' }, { key: 'wins', label: '勝', num: true },
  { key: 'win_pct', label: '勝率 %', num: true, digits: 1, bar: 'pct' }]
const AVGS = [{ key: 'avg_ka', label: '平均 k+a', num: true, digits: 2 }, { key: 'avg_d', label: '平均 d', num: true, digits: 2 },
  { key: 'avg_sp', label: '平均 sp', num: true, digits: 2 }, { key: 'avg_points', label: '平均 p', num: true }]
const signed = (v) => v > 0 ? `+${v}` : String(v)
const GACHI = '@gachi'   // the rule filter value for every ガチ rule (app/db/queries.GACHI)

function Panel({ title, note, wide, tools, children }) {
  return (
    <div className={`panel ${wide ? 'wide' : ''}`}>
      <div className="panel-head"><h3>{title}{note && <small>{note}</small>}</h3>{tools}</div>
      {children}
    </div>
  )
}

// a popup over the page; Esc or a click outside closes it
function Modal({ title, note, tools, onClose, children }) {
  useEffect(() => {
    const key = (e) => { if (e.key === 'Escape') onClose() }
    addEventListener('keydown', key)
    return () => removeEventListener('keydown', key)
  }, [onClose])
  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="panel-head"><h3>{title}{note && <small>{note}</small>}</h3>{tools}<button className="secondary small close" onClick={onClose}>閉じる</button></div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  )
}

// a stat table as a card: the top ROWS rows (in the current order, padded to ROWS), and a popup with all of them
// that shares the card's sort order
function StatCard({ title, note, wide, tools, cols, rows, sort: initial, dim }) {
  const [sort, setSort] = useState(initial)
  const [open, setOpen] = useState(false)
  const close = useCallback(() => setOpen(false), [])
  const table = (limit) => <SortTable cols={cols} rows={rows} sort={sort} onSort={setSort} dim={dim} limit={limit} pad={limit} />
  return (
    <Panel title={title} note={note} wide={wide} tools={tools}>
      {table(ROWS)}
      <div className="panel-foot">
        <span className="muted">{rows.length > ROWS ? `${rows.length} 件中 上位 ${ROWS} 件` : `${rows.length} 件`}</span>
        {rows.length > ROWS && <button className="secondary small" onClick={() => setOpen(true)}>すべて表示</button>}
      </div>
      {open && <Modal title={title} note={note} tools={tools} onClose={close}>{table(null)}</Modal>}
    </Panel>
  )
}

// kill / death (HUD) counts as a grid: one row per kind, one column per 30 s window; a cell's shade places its count
// between the quietest and the busiest window of its row (kills in green, deaths in red)
function Heatmap({ windows, games }) {
  if (!windows.length) return <p className="muted heat-empty">データなし</p>
  const rows = [['kill', 'win'], ['death', 'lose']]          // not killed_by: the bubble comes seconds late and is missed at Finish
  return (
    <div className="heat" style={{ gridTemplateColumns: `5.5em repeat(${windows.length}, 1fr)` }}>
      <span />
      {windows.map((w) => <span key={w.from_s} className="heat-col">{clock(w.from_s)}–</span>)}
      {rows.map(([k, tone]) => {
        const lo = Math.min(...windows.map((w) => w[k])), hi = Math.max(...windows.map((w) => w[k]))
        const total = windows.reduce((a, w) => a + w[k], 0)
        return (
          <React.Fragment key={k}>
            <span className="heat-row">{EVENT_LABEL[k]}</span>
            {windows.map((w) => (
              <div key={w.from_s} className="heat-cell" style={{ '--c': `var(--${tone})`, '--a': `${Math.round(8 + 52 * (w[k] - lo) / (hi - lo || 1))}%` }}
                   title={`${EVENT_LABEL[k]} ${clock(w.from_s)}–${clock(w.from_s + 30)}: ${w[k]} 回 (${total ? (100 * w[k] / total).toFixed(1) : 0}%)${games ? `、1 試合あたり ${(w[k] / games).toFixed(2)}` : ''}`}>
                <b>{w[k]}</b>{games ? <small>{(w[k] / games).toFixed(2)}</small> : null}
              </div>
            ))}
          </React.Fragment>
        )
      })}
    </div>
  )
}

function Kpi({ label, value, sub, cls }) {
  return <div className="kpi"><div className="kpi-label">{label}</div><div className={`kpi-value ${cls || ''}`}>{value}</div>{sub && <div className="kpi-sub">{sub}</div>}</div>
}

// the newest results as small squares, oldest left; click one for that match
function Form({ recent }) {
  const list = [...recent].reverse()
  return (
    <div className="form">
      {list.map((m) => (
        <a key={m.id} href={`#/matches/${m.id}`} className={`chip ${m.result || 'none'}`}
           title={`#${m.id} ${m.started_at?.replace('T', ' ').slice(0, 16)} ${m.stage || ''} ${m.weapon || ''}`}>
          {m.result === 'win' ? 'W' : m.result === 'lose' ? 'L' : '?'}
        </a>
      ))}
    </div>
  )
}

function EnemyWeapons({ rows }) {
  const [q, setQ] = useState('')
  const [min, setMin] = useState(3)
  const list = useMemo(() => rows.filter((r) => r.seen >= min && (!q || r.weapon.includes(q))).map((r) => ({ ...r, diff: r.i_killed - r.killed_me })), [rows, q, min])
  return (
    <StatCard title="相手のブキ別" note="差 = たおした − やられた。マイナスほど苦手" rows={list} sort={{ key: 'seen', dir: -1 }} tools={
      <div className="tools">
        <input type="search" placeholder="ブキ名で絞り込み" value={q} onChange={(e) => setQ(e.target.value)} />
        <label>遭遇 <select value={min} onChange={(e) => setMin(Number(e.target.value))}>{[1, 3, 5, 10, 20].map((n) => <option key={n} value={n}>{n} 回以上</option>)}</select></label>
      </div>
    } cols={[
      { key: 'weapon', label: 'ブキ' },
      { key: 'seen', label: '遭遇', num: true, bar: 'max' }, { key: 'wins', label: '勝', num: true },
      { key: 'win_pct', label: '勝率 %', num: true, digits: 1, bar: 'pct' },
      { key: 'i_killed', label: 'たおした', num: true }, { key: 'killed_me', label: 'やられた', num: true },
      { key: 'diff', label: '差', num: true, render: (r) => signed(r.diff), cls: (r) => r.diff > 0 ? 'good' : r.diff < 0 ? 'bad' : '' },
    ]} />
  )
}

export default function Stats() {
  const [filter, setFilter] = useState(() => ({ since: 'all', mode: '', rule: '', ...loadFilter() }))
  const [s, setS] = useState(null)
  const [err, setErr] = useState(null)
  const query = `/api/stats?since=${encodeURIComponent(filter.since)}&mode=${encodeURIComponent(filter.mode)}&rule=${encodeURIComponent(filter.rule)}`
  const load = () => api(query).then((d) => { setS(d); setErr(null) }).catch((e) => setErr(String(e)))
  useEffect(() => { load(); saveFilter(filter) }, [query])
  useEffect(() => subscribe((m) => { if (m.type === 'match_saved' || m.type === 'match_deleted') load() }), [query])
  const set = (k, v) => setFilter({ ...filter, [k]: v })

  // kill / death counts per 30 s window, one row per window
  const timeline = useMemo(() => {
    const by = {}
    for (const r of s?.my_timeline || []) (by[r.from_s] ??= { from_s: r.from_s, kill: 0, killed_by: 0, death: 0 })[r.type] = r.n
    return Object.values(by)
  }, [s])

  if (err && !s) return <p className="error">{err}</p>
  if (!s) return <p>読み込み中…</p>
  const o = s.overview?.[0] || {}
  const decided = (o.wins || 0) + (o.losses || 0)
  const pct = decided ? 100 * o.wins / decided : null
  const streak = []
  for (const m of s.recent || []) { if (m.result !== s.recent[0].result || !['win', 'lose'].includes(m.result)) break; streak.push(m) }

  return (
    <section className="dash">
      <div className="filters">
        <div className="seg">
          {PERIODS.map(([k, label]) => <button key={k} className={filter.since === k ? 'on' : ''} onClick={() => set('since', k)}>{label}</button>)}
        </div>
        <label>モード <select value={filter.mode} onChange={(e) => set('mode', e.target.value)}>
          <option value="">すべて</option>
          {(s.modes || []).map((m) => <option key={m} value={m}>{m}</option>)}
        </select></label>
        <label>ルール <select value={filter.rule} onChange={(e) => set('rule', e.target.value)}>
          <option value="">すべて</option>
          <option value={GACHI}>ガチ全部</option>
          {(s.rules || []).map((r) => <option key={r} value={r}>{r}</option>)}
        </select></label>
        {err && <span className="error">{err}</span>}
      </div>

      <div className="kpis">
        <Kpi label="試合" value={o.games || 0} sub={`${o.wins || 0} 勝 ${o.losses || 0} 敗`} />
        <Kpi label="勝率" value={pct == null ? '-' : `${pct.toFixed(1)}%`} cls={pct == null ? '' : pct >= 50 ? 'good' : 'bad'} />
        <Kpi label="連続" value={streak.length ? `${streak.length} ${streak[0].result === 'win' ? '連勝' : '連敗'}` : '-'} cls={streak[0]?.result === 'win' ? 'good' : streak.length ? 'bad' : ''} />
        <Kpi label="(k+a) / d" value={o.sum_d ? (o.sum_ka / o.sum_d).toFixed(2) : '-'} sub={o.sum_ka != null ? `${o.sum_ka} / ${o.sum_d}` : null} />
        <Kpi label="平均 k+a" value={num(o.avg_ka, 2)} />
        <Kpi label="平均 d" value={num(o.avg_d, 2)} />
        <Kpi label="平均 sp" value={num(o.avg_sp, 2)} />
        <Kpi label="平均 p" value={num(o.avg_points)} />
        <Kpi label="平均 塗り" value={o.avg_pct == null ? '-' : `${o.avg_pct}%`} />
        {o.count_games > 0 && <>
          <Kpi label="KO 勝ち / 負け" value={<>{o.ko_wins} <span className="kpi-of">/ {o.ko_losses}</span></>} cls={o.ko_wins > o.ko_losses ? 'good' : o.ko_wins < o.ko_losses ? 'bad' : ''}
               sub={`カウントのある ${o.count_games} 試合`} />
          <Kpi label="平均カウント差" value={signed(Math.round(10 * (o.avg_my_count - o.avg_enemy_count)) / 10)} cls={o.avg_my_count >= o.avg_enemy_count ? 'good' : 'bad'}
               sub={`自 ${o.avg_my_count} / 敵 ${o.avg_enemy_count}`} />
        </>}
      </div>

      {s.recent?.length > 0 && <Panel title="直近の結果" note={`${s.recent.length} 試合、右が最新`} wide><Form recent={s.recent} /></Panel>}

      <div className="grid">
        <StatCard title="日別" rows={s.daily_stats || []} sort={{ key: 'day', dir: -1 }} cols={[{ key: 'day', label: '日付' }, ...GAMES, ...AVGS]} />
        <StatCard title="ルール別" note="KO はノックアウト" rows={s.rule_stats || []} sort={{ key: 'games', dir: -1 }} cols={[
          { key: 'rule', label: 'ルール' }, ...GAMES, { key: 'ko_wins', label: 'KO 勝', num: true }, { key: 'ko_losses', label: 'KO 負', num: true }, ...AVGS.filter((c) => c.key !== 'avg_sp'),
        ]} />
        <StatCard title="ステージ別" note="5 試合未満は薄く表示" rows={s.stage_stats} sort={{ key: 'games', dir: -1 }} dim={(r) => r.games < 5}
                  cols={[{ key: 'stage', label: 'ステージ' }, ...GAMES, ...AVGS.filter((c) => c.key !== 'avg_sp')]} />
        <StatCard title="自分のブキ別" rows={s.weapon_stats} sort={{ key: 'games', dir: -1 }} cols={[{ key: 'weapon', label: 'ブキ' }, ...GAMES, ...AVGS]} />
        <StatCard title="表彰" rows={s.medal_stats} sort={{ key: 'n', dir: -1 }} cols={[
          { key: 'name', label: '名前' },
          { key: 'rank', label: '', render: (r) => <span className={`rank ${r.rank}`}>{RANK[r.rank] || r.rank || ''}</span> },
          { key: 'n', label: '回数', num: true, bar: 'max' },
        ]} />
        <Panel title="自分のキル/デス" note="試合開始からの 30 秒刻み">
          <Heatmap windows={timeline} games={o.games} />
          <div className="panel-foot"><span className="muted">色の濃さ = その行で最少〜最多のどのあたりか。数字は回数、下は 1 試合あたり</span></div>
        </Panel>
        <EnemyWeapons rows={s.enemy_weapon_stats} />
      </div>
    </section>
  )
}
