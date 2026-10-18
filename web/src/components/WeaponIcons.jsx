import React, { useEffect, useState } from 'react'
import { api, post, subscribe } from '../api.js'

const ROW = { win1: '勝ち 1 行目', win2: '勝ち 2 行目', win3: '勝ち 3 行目', win4: '勝ち 4 行目', lose1: '負け 1 行目', lose2: '負け 2 行目', lose3: '負け 3 行目', lose4: '負け 4 行目' }

// an unknown weapon icon group: its crops, the result screens it was seen on, and a name picked from the weapon list
// (filled in with the wiki's guess when the wiki icons named it, only not confidently enough)
function Item({ it, onDone }) {
  const [name, setName] = useState(it.guess || '')
  const [err, setErr] = useState(null)
  const submit = async (e) => {
    e.preventDefault(); if (!name.trim()) return
    try { await post('/api/weapon_icons/label', { id: it.id, name: name.trim() }); onDone() } catch (x) { setErr(String(x)) }
  }
  return (
    <div className="unknown">
      <div className="glyph">
        {it.samples.slice(0, 3).map((s) => <img key={s} className="icon" src={`/files/${s}`} alt="" />)}
        <div className="muted">{it.id}</div>
      </div>
      <div className="examples">
        {it.seen.map((s, i) => (
          <div key={i} className="example">
            {s.result_image && <a href={`/files/${s.result_image}`} target="_blank" rel="noreferrer"><img className="thumb" src={`/files/${s.result_image}`} alt="" /></a>}
            <div className="caption">試合 <a href={`#/matches/${s.match_id}`}>#{s.match_id}</a> {s.rows.map((r) => ROW[r] || r).join(', ')}</div>
          </div>
        ))}
        {it.seen.length === 0 && <p className="muted">保存された試合がありません</p>}
      </div>
      <form onSubmit={submit} className="answer">
        <label>このブキは？ <input className="wide" list="weapon-names" value={name} onChange={(e) => setName(e.target.value)} autoComplete="off" /></label>
        <button type="submit" disabled={!name.trim()}>登録</button>
        <span className="hint">{it.guess ? `wiki の推定: ${it.guess}（合っていればそのまま登録）` : '候補にない新ブキはそのまま入力'}</span>
        {err && <span className="hint">{err}</span>}
      </form>
    </div>
  )
}

export default function WeaponIcons() {
  const [list, setList] = useState([])
  const [names, setNames] = useState([])
  const load = () => api('/api/weapon_icons/unknown').then(setList).catch(() => {})
  useEffect(() => { load(); api('/api/weapons').then(setNames).catch(() => {}) }, [])
  useEffect(() => subscribe((m) => { if (m.type === 'weapon_icons_changed' || m.type === 'match_saved') load() }), [])
  return (
    <section>
      <h2>未知・確認待ちのブキ <small>{list.length} 種類。見た目ごとにまとめてあり、名前を付けると判定に使われ、その試合すべてに反映</small></h2>
      <datalist id="weapon-names">{names.map((n) => <option key={n} value={n} />)}</datalist>
      {list.slice(0, 30).map((it) => <Item key={it.id} it={it} onDone={load} />)}
      {list.length === 0 && <p className="muted">未知・確認待ちのブキはありません</p>}
    </section>
  )
}
