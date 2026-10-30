import React, { useEffect, useState } from 'react'
import { api, subscribe } from '../api.js'
import { Rule, Score } from './Score.jsx'

const fmt = (iso) => iso ? iso.replace('T', ' ').slice(0, 16) : ''

export default function MatchList() {
  const [rows, setRows] = useState([])
  const [err, setErr] = useState(null)
  const load = () => api('/api/matches?limit=200').then(setRows).catch((e) => setErr(String(e)))
  useEffect(() => { load() }, [])
  useEffect(() => subscribe((m) => { if (m.type === 'match_saved' || m.type === 'match_deleted') load() }), [])

  if (err) return <p className="error">{err}</p>
  return (
    <section>
      <h2>試合一覧 <small>{rows.length} 件、新しい順。ライブで記録されると自動で増えます</small></h2>
      <table className="list">
        <thead>
          <tr><th>#</th><th>開始</th><th>ルール</th><th>ステージ</th><th>結果</th><th title="ナワバリは塗り %、ガチはカウント">スコア</th><th>ブキ</th><th>p</th><th>k+a</th><th>d</th><th>sp</th><th>表彰</th><th>元</th></tr>
        </thead>
        <tbody>
          {rows.map((m) => (
            <tr key={m.id} className={m.result} onClick={() => (location.hash = `#/matches/${m.id}`)}>
              <td>{m.id}</td><td>{fmt(m.started_at)}</td><td><Rule m={m} /></td><td>{m.stage || <i className="muted">未ラベル</i>}</td>
              <td className="result">{m.result === 'win' ? 'WIN' : m.result === 'lose' ? 'LOSE' : '-'}</td>
              <td><Score m={m} /></td>
              <td>{m.weapon || '-'}</td><td>{m.points ?? '-'}</td><td>{m.kills_assists ?? '-'}</td><td>{m.deaths ?? '-'}</td><td>{m.specials ?? '-'}</td>
              <td>{m.medals || ''}</td><td className="muted">{m.source === 'live' ? 'live' : '録画'}{m.notes ? ' ⚠' : ''}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}
