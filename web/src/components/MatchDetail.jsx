import React, { useEffect, useState } from 'react'
import { api, del } from '../api.js'
import { Score } from './Score.jsx'

const EVENT_LABEL = { death: 'デス', kill: 'たおした', killed_by: 'やられた', special: 'スペシャル' }
const sec = (ms) => `${Math.floor(ms / 60000)}:${String(Math.floor((ms % 60000) / 1000)).padStart(2, '0')}`

export default function MatchDetail({ id }) {
  const [m, setM] = useState(null)
  const [err, setErr] = useState(null)
  useEffect(() => { setM(null); api(`/api/matches/${id}`).then(setM).catch((e) => setErr(String(e))) }, [id])
  if (err) return <p className="error">{err}</p>
  if (!m) return <p>読み込み中…</p>

  const bySlot = Object.fromEntries(m.players.map((p) => [p.slot, p]))
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
