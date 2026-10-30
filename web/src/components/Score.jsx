import React from 'react'

export const isGachi = (m) => m.my_count != null || (m.rule || '').startsWith('ガチ')

// a match's rule as a small tag: ナワバリ green, ガチ yellow
export function Rule({ m }) {
  if (!m.rule) return '-'
  return <span className={`rule-tag ${isGachi(m) ? 'gachi' : 'turf'}`}>{m.rule}</span>
}

// the score: paint % for ナワバリ, counts for ガチ (+ a KO mark when it ended by ノックアウト); long adds the units / KO text
export function Score({ m, long }) {
  if (m.my_count != null) {
    return (
      <span className="score">
        {m.my_count} - {m.enemy_count}{long ? ' カウント' : ''}
        {m.knockout ? <span className="ko">{long ? (m.result === 'lose' ? 'ノックアウト負け' : 'ノックアウト勝ち') : 'KO'}</span> : null}
      </span>
    )
  }
  if (m.my_pct != null) return <span className="score">{long ? `${m.my_pct}% - ${m.enemy_pct}%` : `${m.my_pct} - ${m.enemy_pct}`}</span>
  return long ? null : '-'
}
