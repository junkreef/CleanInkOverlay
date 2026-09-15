import React, { useEffect, useState } from 'react'
import { api, post, subscribe } from '../api.js'

const KIND = { stage: 'ステージ', medal: '表彰', mode: 'モード', rule: 'ルール' }

// an unlabelled stage / medal signature: show where it was seen (the saved screen) and ask for the text
function Item({ it, onDone }) {
  const [label, setLabel] = useState('')
  const submit = async (e) => { e.preventDefault(); if (!label.trim()) return; await post('/api/signatures/label', { id: it.id, label: label.trim() }); onDone() }
  return (
    <div className="unknown">
      <div className="glyph"><div><b>{KIND[it.kind] || it.kind}</b></div><div className="muted">{it.id}</div></div>
      <div className="examples">
        {it.seen.map((s, i) => (
          <div key={i} className="example">
            {s.result_image && <a href={`/files/${s.result_image}`} target="_blank" rel="noreferrer"><img className="thumb" src={`/files/${s.result_image}`} alt="" /></a>}
            {s.medal_image && <a href={`/files/${s.medal_image}`} target="_blank" rel="noreferrer"><img className="thumb" src={`/files/${s.medal_image}`} alt="" /></a>}
            {s.rule_image && <a href={`/files/${s.rule_image}`} target="_blank" rel="noreferrer"><img className="thumb" src={`/files/${s.rule_image}`} alt="" /></a>}
            <div className="caption">試合 #{s.match_id}{s.position != null ? ` 表彰 ${s.position + 1} 段目` : ''}</div>
          </div>
        ))}
        {it.seen.length === 0 && <p className="muted">保存された画面がありません</p>}
      </div>
      <form onSubmit={submit} className="answer">
        <label>これは？ <input value={label} onChange={(e) => setLabel(e.target.value)} autoComplete="off" /></label>
        <button type="submit" disabled={!label.trim()}>登録</button>
      </form>
    </div>
  )
}

export default function Signatures() {
  const [list, setList] = useState([])
  const [kind, setKind] = useState('')
  const [msg, setMsg] = useState(null)
  const load = () => api(`/api/signatures/unlabelled${kind ? `?kind=${kind}` : ''}`).then(setList).catch(() => {})
  const prune = async () => {
    if (!confirm('保存された画面がない未ラベルの署名を削除します。次に見かけたときに画像付きで登録し直されます。よろしいですか？')) return
    const r = await post('/api/signatures/prune', {}); setMsg(`${r.deleted} 個削除しました`); load()
  }
  useEffect(() => { load() }, [kind])
  useEffect(() => subscribe((m) => { if (m.type === 'signatures_changed') load() }), [kind])
  return (
    <section>
      <h2>未知のステージ・表彰 <small>{list.length} 個。画像を見て文字を入れると、その署名を持つ試合すべてに反映</small></h2>
      <div className="toolbar">
        <label>種類 <select value={kind} onChange={(e) => setKind(e.target.value)}><option value="">すべて</option>{Object.entries(KIND).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
        <button className="secondary" onClick={prune} title="保存された画面がない署名を消す (次に見かけたら画像付きで登録し直される)">画像のないものを削除</button>
        {msg && <span className="muted">{msg}</span>}
      </div>
      {list.slice(0, 30).map((it) => <Item key={it.id} it={it} onDone={load} />)}
      {list.length === 0 && <p className="muted">未ラベルの署名はありません</p>}
    </section>
  )
}
