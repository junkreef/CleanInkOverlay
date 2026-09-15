import React, { useEffect, useState } from 'react'
import { api, subscribe } from '../api.js'

const TITLES = { weapon_stats: '自分のブキ別', stage_stats: 'ステージ別', enemy_weapon_stats: '相手のブキ別', medal_stats: '表彰', my_timeline: '自分のキル/デス (30 秒刻み)' }
const COLS = { games: '試合', wins: '勝', win_pct: '勝率 %', avg_ka: '平均 k+a', avg_d: '平均 d', avg_sp: '平均 sp', avg_points: '平均 p', seen: '遭遇', killed_me: 'やられた', i_killed: 'たおした', from_s: '開始秒', type: '種類', n: '回数', name: '名前', rank: '', weapon: 'ブキ', stage: 'ステージ' }

function Table({ rows }) {
  if (!rows?.length) return <p className="muted">データなし</p>
  const cols = Object.keys(rows[0])
  return (
    <table className="list">
      <thead><tr>{cols.map((c) => <th key={c}>{COLS[c] ?? c}</th>)}</tr></thead>
      <tbody>{rows.map((r, i) => <tr key={i}>{cols.map((c) => <td key={c}>{r[c] ?? '-'}</td>)}</tr>)}</tbody>
    </table>
  )
}

export default function Stats() {
  const [s, setS] = useState(null)
  const load = () => api('/api/stats').then(setS).catch(() => {})
  useEffect(() => { load() }, [])
  useEffect(() => subscribe((m) => { if (m.type === 'match_saved' || m.type === 'match_deleted') load() }), [])
  if (!s) return <p>読み込み中…</p>
  return (
    <section>
      {Object.entries(TITLES).map(([k, title]) => (
        <div key={k}><h2>{title}</h2><Table rows={s[k]} /></div>
      ))}
    </section>
  )
}
