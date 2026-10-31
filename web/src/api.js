// thin client for the backend: JSON over fetch + one shared WebSocket for pushes
export async function api(path, opts) {
  const r = await fetch(path, opts)
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
  return r.json()
}

export const post = (path, body) => api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
export const del = (path) => api(path, { method: 'DELETE' })

// local ISO time -> '09:23' today, '10/30 23:10' on another day
export function clockLabel(iso) {
  const d = new Date(iso), now = new Date(), hm = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  return d.toDateString() === now.toDateString() ? hm : `${d.getMonth() + 1}/${d.getDate()} ${hm}`
}

const listeners = new Set()
let ws = null

function connect() {
  const url = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`
  ws = new WebSocket(url)
  ws.onmessage = (e) => { const msg = JSON.parse(e.data); for (const l of listeners) l(msg) }
  ws.onclose = () => { for (const l of listeners) l({ type: 'disconnected' }); setTimeout(connect, 2000) }
  ws.onopen = () => { for (const l of listeners) l({ type: 'connected' }) }
}

// subscribe(fn) -> unsubscribe; fn receives every pushed message
export function subscribe(fn) {
  listeners.add(fn)
  if (!ws) connect()
  return () => listeners.delete(fn)
}
