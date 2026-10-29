import React, { useEffect, useState } from 'react'
import { api, del } from '../api.js'
import { Score } from './Score.jsx'

const EVENT_LABEL = { death: 'デス', kill: 'たおした', killed_by: 'やられた', special: 'スペシャル' }
const sec = (ms) => `${Math.floor(ms / 60000)}:${String(Math.floor((ms % 60000) / 1000)).padStart(2, '0')}`

// ガチルール: one chart for every rule, 0 in the middle, my team upward, the enemy downward. Lines = each team's count
// (エリア: the counts; ヤグラ / ホコ: how far each team has pushed). Band under a line = what the team has to win back
// before its count moves again (エリア: the penalty, its lower edge dotted = count - penalty; ヤグラ / ホコ: from the best
// back to where the objective is now, the white line). Overtime shaded; hover for the values of a second
const RULE_WORDS = {
  ガチエリア: { debt: 'ペナルティ', floor: '点線 = カウント - ペナルティ', hold: '確保' },
  ガチヤグラ: { debt: '最高到達点との差', floor: '白い線 = ヤグラの位置', hold: '乗車', obj: 'ヤグラ' },
  ガチホコバトル: { debt: '最高到達点との差', floor: '白い線 = ホコの位置', hold: '所持', obj: 'ホコ' },
}
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v))

// per-second arrays from the timeline rows (seconds without a row are gaps): counts carried over gaps (they only grow),
// penalties kept over gaps up to 3 s and 0 after, the objective position with single misreads dropped (median of 3) and
// gaps up to 12 s joined
function series(tl) {
  const n = Math.max(0, ...tl.map((r) => r.t_s + 1)), at = Array(n).fill(null)
  for (const r of tl) at[r.t_s] = r
  const col = (k) => at.map((r) => (r ? r[k] : null))
  const carry = (a) => { let last = null; return a.map((v) => (last = v ?? last)) }
  const pen = (a) => { let last = 0, gap = 0; return a.map((v) => { if (v != null) { last = v; gap = 0 } else if (++gap > 3) last = 0; return last }) }
  const track = tl.some((r) => r.obj_pos != null || r.my_best != null)
  if (!track && !tl.some((r) => r.my_count != null)) return null
  let pos = null
  if (track) {
    const raw = col('obj_pos'), idx = raw.flatMap((v, i) => (v == null ? [] : [i])); pos = raw.slice()
    for (let k = 1; k < idx.length - 1; k++) pos[idx[k]] = [raw[idx[k - 1]], raw[idx[k]], raw[idx[k + 1]]].sort((a, b) => a - b)[1]
    for (let k = 1; k < idx.length; k++) {
      const a = idx[k - 1], b = idx[k]
      if (b - a > 1 && b - a <= 12) for (let j = a + 1; j < b; j++) pos[j] = pos[a] + ((pos[b] - pos[a]) * (j - a)) / (b - a)
    }
  }
  const my = carry(col(track ? 'my_best' : 'my_count')), en = carry(col(track ? 'enemy_best' : 'enemy_count'))
  const pm = track ? null : pen(col('my_penalty')), pe = track ? null : pen(col('enemy_penalty'))
  const floor = track
    ? [my.map((v, i) => (v == null || pos[i] == null ? null : clamp(pos[i], 0, v))), en.map((v, i) => (v == null || pos[i] == null ? null : -clamp(-pos[i], 0, v)))]
    : [my.map((v, i) => (v == null ? null : Math.max(0, v - pm[i]))), en.map((v, i) => (v == null ? null : -Math.max(0, v - pe[i])))]
  return { n, cnt: [my, en.map((v) => (v == null ? null : -v))], floor, pen: track ? null : [pm, pe], pos, hold: col('obj_holder'), ot: col('overtime') }
}

function GachiChart({ m }) {
  const [hover, setHover] = useState(null)
  const S = series(m.timeline || [])
  if (!S) return null
  const words = RULE_WORDS[m.rule] || { debt: '取り返す分', floor: S.pos ? '白い線 = 目標の位置' : '点線 = カウント - ペナルティ', hold: '確保' }
  const W = 900, L = 58, R = 12, T = 12, HALF = 110, B = 26, H = T + 2 * HALF + B
  const tMax = Math.max(300, S.n), x = (t) => L + (t / tMax) * (W - L - R), y0 = T + HALF, y = (v) => y0 - (v / 100) * HALF
  const path = (a) => { let d = '', on = false; a.forEach((v, i) => { if (v == null) { on = false; return } d += `${on ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`; on = true }); return d }
  const bands = [], floors = []
  for (const [i, k] of [[0, 'my'], [1, 'enemy']]) {
    let seg = []
    const flush = () => {
      if (seg.length > 1) {
        const top = seg.map((j) => `${x(j).toFixed(1)},${y(S.cnt[i][j]).toFixed(1)}`).join('L')
        const bot = seg.slice().reverse().map((j) => `${x(j).toFixed(1)},${y(S.floor[i][j]).toFixed(1)}`).join('L')
        bands.push(<path key={`${k}${seg[0]}`} d={`M${top}L${bot}Z`} className={`band ${k}`} />)
        if (!S.pos) floors.push(<path key={`f${k}${seg[0]}`} d={path(S.floor[i].map((v, j) => (seg.includes(j) && Math.abs(v) >= 0.6 ? v : null)))} className="floor dot" />)
      }
      seg = []
    }
    for (let j = 0; j < S.n; j++) { const c = S.cnt[i][j], f = S.floor[i][j]; if (c != null && f != null && Math.abs(c - f) > 0.5) seg.push(j); else flush() }
    flush()
  }
  const ots = S.ot.flatMap((v, i) => (v ? [i] : []))
  const move = (ev) => {
    const svg = ev.currentTarget, pt = svg.createSVGPoint(); pt.x = ev.clientX; pt.y = ev.clientY
    const p = pt.matrixTransform(svg.getScreenCTM().inverse()), i = Math.round(((p.x - L) / (W - L - R)) * tMax)
    const box = svg.parentNode.getBoundingClientRect()
    setHover(i >= 0 && i < S.n ? { i, left: ev.clientX - box.left, top: ev.clientY - box.top, right: ev.clientX - box.left > box.width - 220 } : null)
  }
  const h = hover?.i
  return (
    <div className="objchart gachi">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${m.rule || 'ガチルール'}のカウントの推移`} onPointerMove={move} onPointerLeave={() => setHover(null)}>
        {ots.length > 0 && <rect x={x(ots[0])} y={T} width={x(ots[ots.length - 1] + 1) - x(ots[0])} height={2 * HALF} className="ot" />}
        {[100, 50, -50, -100].map((v) => <g key={v}><line x1={L} x2={W - R} y1={y(v)} y2={y(v)} className="grid" /><text x={L - 6} y={y(v) + 4} className="axis" textAnchor="end">{v === 100 ? '味方 100' : v === -100 ? '相手 100' : Math.abs(v)}</text></g>)}
        <line x1={L} x2={W - R} y1={y0} y2={y0} className="grid zero" /><text x={L - 6} y={y0 + 4} className="axis" textAnchor="end">0</text>
        {Array.from({ length: Math.floor(tMax / 60) + 1 }, (_, i) => i * 60).map((t) => <text key={t} x={x(t)} y={H - 8} className="axis" textAnchor="middle">{t / 60}:00</text>)}
        {bands}{floors}
        {S.pos && <path d={path(S.pos.map((v) => (v == null ? null : clamp(v, -100, 100))))} className="floor" />}
        <path d={path(S.cnt[0])} className="best my" /><path d={path(S.cnt[1])} className="best enemy" />
        {h != null && <line x1={x(h)} x2={x(h)} y1={T} y2={T + 2 * HALF} className="crosshair" />}
      </svg>
      {h != null && (
        <div className="tip" style={{ top: hover.top - 10, ...(hover.right ? { right: `calc(100% - ${hover.left - 14}px)` } : { left: hover.left + 14 }) }}>
          <div className="muted">{sec(h * 1000)}{S.ot[h] ? ' 延長戦' : ''}</div>
          {[[0, 'my', '味方'], [1, 'enemy', '相手']].map(([i, k, who]) => S.cnt[i][h] != null && (
            <div key={k}><i className={`bar ${k}`} /><b>{Math.round(Math.abs(S.cnt[i][h]))}</b> {who}のカウント
              {S.pen && S.pen[i][h] > 0 && <span className="muted"> (ペナルティ {S.pen[i][h]})</span>}</div>
          ))}
          {S.pos && S.pos[h] != null && <div><b>{S.pos[h] > 0 ? '+' : ''}{Math.round(S.pos[h])}</b> {words.obj || '目標'}の位置</div>}
          <div className="muted">{S.hold[h] === 'my' ? `味方が${words.hold}` : S.hold[h] === 'enemy' ? `相手が${words.hold}` : `${words.hold}なし`}</div>
        </div>
      )}
      <div className="objlegend muted">
        <span><i className="bar my" />味方のカウント (上へ)</span><span><i className="bar enemy" />相手のカウント (下へ)</span>
        <span><i className="swatch" />帯 = カウントが動き出すまでに取り返す分 ({words.debt})</span>
        <span><i className={S.pos ? 'fl solid' : 'fl'} />{words.floor}</span>
        {ots.length > 0 && <span>網かけ = 延長戦</span>}
        {m.my_count != null && <span>最終カウント {m.my_count} - {m.enemy_count}{m.knockout ? ' (ノックアウト)' : ''}</span>}
      </div>
    </div>
  )
}

export default function MatchDetail({ id }) {
  const [m, setM] = useState(null)
  const [err, setErr] = useState(null)
  useEffect(() => { setM(null); api(`/api/matches/${id}`).then(setM).catch((e) => setErr(String(e))) }, [id])
  if (err) return <p className="error">{err}</p>
  if (!m) return <p>読み込み中…</p>

  const bySlot = Object.fromEntries(m.players.map((p) => [p.slot, p]))
  const selfSlot = m.players.find((p) => p.is_self)?.slot
  const who = (slot) => slot == null ? '' : (bySlot[slot]?.weapon || `slot${slot}`) + (bySlot[slot]?.is_self ? ' (自分)' : '')
  const imgs = [['ルール画面', m.rule_image], ['表彰', m.medal_image], ['リザルト', m.result_image]].filter(([, p]) => p)

  const remove = async () => {
    if (!confirm(`試合 #${m.id} を削除しますか？`)) return
    await del(`/api/matches/${m.id}`); location.hash = '#/matches'
  }

  return (
    <section>
      <p><a href="#/matches">← 一覧</a></p>
      <h2>
        試合 #{m.id} <span className={`result ${m.result}`}>{m.result === 'win' ? 'WIN' : m.result === 'lose' ? 'LOSE' : '?'}</span>
        <small> {m.started_at?.replace('T', ' ')} / {m.rule || '-'} / {m.stage || '未ラベル'} / <Score m={m} long /> / {m.duration_s ? `${m.duration_s}s` : ''}</small>
      </h2>
      {m.notes && <p className="warn">⚠ {m.notes}</p>}

      <h3>成績</h3>
      <table className="list">
        <thead><tr><th>slot</th><th>チーム</th><th>ブキ</th><th>p</th><th>k+a</th><th>d</th><th>sp</th><th>紐づけ</th></tr></thead>
        <tbody>
          {m.players.map((p) => (
            <tr key={p.slot} className={p.is_self ? 'self' : ''}>
              <td>{p.slot}</td><td>{p.team === 'ally' ? '味方' : '敵'}</td>
              <td>{p.weapon || <i className="muted">不明</i>}{p.is_self ? ' ★' : ''}</td>
              <td>{p.points ?? '-'}</td><td>{p.kills_assists ?? '-'}</td><td>{p.deaths ?? '-'}</td><td>{p.specials ?? '-'}</td>
              <td className="muted">{p.link_score ?? '-'}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {m.medals.length > 0 && (
        <>
          <h3>表彰</h3>
          <ul className="medals">{m.medals.map((d, i) => <li key={i} className={d.rank}>{d.rank === 'gold' ? '🥇' : '🥈'} {d.name}</li>)}</ul>
        </>
      )}

      {m.timeline?.some((r) => r.obj_pos != null || r.my_best != null || r.my_count != null) && (
        <>
          <h3>カウントの推移 <small>味方が上、相手が下。ヤグラ / ホコは画面上部の線の上の進み (カウントとは目盛りが少し違う)。マップやジャンプで HUD が見えない秒はつないでいる</small></h3>
          <GachiChart m={m} />
        </>
      )}

      <h3>時系列 <small>{m.events.length} 件</small></h3>
      <table className="list events">
        <thead><tr><th>経過</th><th>残り</th><th>種類</th><th>誰が</th><th>相手</th><th>元</th><th>信頼度</th></tr></thead>
        <tbody>
          {m.events.map((e) => (
            <tr key={e.id} className={`ev ${e.type} ${e.slot != null && bySlot[e.slot]?.is_self ? 'self' : ''}`}>
              <td>{sec(e.t_ms)}</td><td>{e.clock || ''}</td><td>{EVENT_LABEL[e.type] || e.type}</td>
              <td>{who(e.slot)}</td><td>{who(e.target_slot)}</td><td className="muted">{e.source}</td><td className="muted">{e.confidence ?? ''}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {imgs.length > 0 && (
        <>
          <h3>画像</h3>
          <div className="images">{imgs.map(([label, p]) => <a key={p} href={`/files/${p}`} target="_blank" rel="noreferrer"><img src={`/files/${p}`} alt={label} /><span>{label}</span></a>)}</div>
        </>
      )}
      <p><button className="danger" onClick={remove}>この試合を削除</button></p>
    </section>
  )
}
