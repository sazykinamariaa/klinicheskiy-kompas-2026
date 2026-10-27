// Уточняющие вопросы первичной анкеты («Если ответ «Да», уточните…», «укажите какие») — по документу медиков.
// Черновик — локальная модель; переписано при проверке (мутация состояния, выбор варианта, подписи ответов).
import React from 'react'

const pick = v => Array.isArray(v) ? v : v && typeof v === 'object' ? [v.choice] : [v]
const empty = { multi: [], single: null, single_or_text: { choice: null, text: '' }, free_text_structured: {}, text: '' }

export function visibleFollowups(q, cur, fv) {
  return (q.followups || []).filter(f => {
    const s = f.show_if, v = s.q === q.id ? cur : (fv || {})[s.q]
    if (v == null || (q.type === 'multi' && s.q === q.id && Array.isArray(v) && !v.length)) return false
    if (!s.any && !s.not) return true
    const sel = pick(v).filter(x => typeof x === 'string' && x)
    if (s.any) return sel.some(x => s.any.includes(x))
    return sel.some(x => !s.not.includes(x))
  })
}

export function Followups({ items, fv, setFv }) {
  if (!items || !items.length) return null
  return <div className="fu-box">
    <p className="fu-title">Уточните, если хотите — это необязательно</p>
    {items.map(f => {
      const v = fv[f.id] ?? empty[f.type], set = nv => setFv({ ...fv, [f.id]: nv })
      const opts = (isOn, onClick) => f.options.map(o => <button key={o.id} type="button" className={'opt' + (f.type === 'multi' ? ' multi' : '') + (isOn(o.id) ? ' on' : '')}
        aria-pressed={isOn(o.id)} onClick={() => onClick(o.id)}>{o.label}</button>)
      let body = null
      if (f.type === 'multi') body = opts(id => v.includes(id), id => set(v.includes(id) ? v.filter(x => x !== id) : [...v, id]))
      else if (f.type === 'single') body = opts(id => v === id, id => set(v === id ? null : id))
      else if (f.type === 'single_or_text') {
        const o = typeof v === 'string' ? { choice: v, text: '' } : v
        body = <>{opts(id => o.choice === id, id => set({ ...o, choice: o.choice === id ? null : id }))}
          <input className="fu-text" aria-label="Своими словами" placeholder="Или напишите своими словами" value={o.text || ''} onChange={e => set({ ...o, text: e.target.value })} /></>
      } else if (f.type === 'free_text_structured') body = (f.fields || []).map(k => <label key={k} className="fu-label">{k}
        <textarea rows={2} aria-label={k} value={v[k] || ''} onChange={e => set({ ...v, [k]: e.target.value })} /></label>)
      else body = <input className="fu-text" aria-label={f.text} value={v || ''} onChange={e => set(e.target.value)} />
      return <div key={f.id} className="fu-item"><p className="fu-q">{f.text}</p>{body}</div>
    })}
  </div>
}

export function fuText(f, v) {
  const lab = id => ((f.options || []).find(o => o.id === id) || {}).label || id
  if (v == null || v === '' || (Array.isArray(v) && !v.length)) return null
  if (Array.isArray(v)) return v.map(lab).join(', ')
  if (typeof v === 'object') {
    if (f.type === 'free_text_structured') return Object.entries(v).filter(([, x]) => String(x || '').trim()).map(([k, x]) => k + ': ' + String(x).trim()).join('; ') || null
    return [v.choice ? lab(v.choice) : null, (v.text || '').trim() || null].filter(Boolean).join(', ') || null
  }
  return lab(v).trim() || null
}

// Пустой ответ уточнения отправляется как null (сервер удаляет прежний ответ)
export const fuValue = (f, v) => fuText(f, v) == null ? null : v
