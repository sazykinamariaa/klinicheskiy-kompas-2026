import React, { useEffect, useState } from 'react'
import Icon from './Icon.jsx'
export { default as Icon, Mark } from './Icon.jsx'

export function useLoad(fn, deps = []) {
  const [data, setData] = useState(null), [err, setErr] = useState(null), [n, setN] = useState(0)
  useEffect(() => { let on = true; setErr(null); fn().then(d => on && setData(d)).catch(e => on && setErr(e.message)); return () => { on = false } }, [...deps, n])
  return [data, err, () => setN(x => x + 1), setData]
}
export const Err = ({ e }) => e ? <p className="err" role="alert"><Icon name="info" size={18} /><span>{e}</span></p> : null
export const LEVEL = { red: ['Критический', 'lv-red'], orange: ['Оперативная оценка', 'lv-orange'], yellow: ['Плановая оценка', 'lv-yellow'], green: ['Наблюдение', 'lv-green'] }
export const Level = ({ l, short }) => { const [t, c] = LEVEL[l] || ['—', 'lv-gray']; return <span className={'lv ' + c}>{short ? t.split(' ')[0] : t}</span> }
// Сервер отдаёт время в UTC без суффикса зоны: показываем в часовом поясе пользователя
export const toDate = s => new Date(typeof s === 'string' && s.length > 10 && !/(z|[+-]\d\d:?\d\d)$/i.test(s) ? s + 'Z' : s)
export const fmt = s => s ? toDate(s).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' }) : '—'
export const fmtDay = s => s ? toDate(s).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' }) : '—'
export const fmtTime = s => s ? toDate(s).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }) : ''
export function Busy({ children, onClick, cls, ...p }) {
  const [b, setB] = useState(false), [e, setE] = useState(null)
  return <><button className={(cls || '') + (b ? ' is-busy' : '')} disabled={b || p.disabled} aria-busy={b || undefined} title={p.title}
    onClick={async () => { setB(true); setE(null); try { await onClick() } catch (x) { setE(x.message) } setB(false) }}>{children}</button><Err e={e} /></>
}
export const toast = msg => dispatchEvent(new CustomEvent('kk-toast', { detail: msg }))
export function Toaster() {
  const [m, setM] = useState(null)
  useEffect(() => { let t; const f = e => { setM(e.detail); clearTimeout(t); t = setTimeout(() => setM(null), 3200) }; addEventListener('kk-toast', f); return () => { removeEventListener('kk-toast', f); clearTimeout(t) } }, [])
  return <div className="toast-wrap" role="status" aria-live="polite">{m && <div className="toast"><Icon name="checkCircle" size={18} />{m}</div>}</div>
}
export const go = h => { if (location.hash === h) dispatchEvent(new HashChangeEvent('hashchange')); else location.hash = h }

// Заглушка загрузки: «скелет» вместо текста «Загрузка…»
export const Loading = ({ rows = 3, card = true }) => <div className={card ? 'card skel-card' : 'skel-card'} aria-busy="true" aria-label="Загрузка">
  <div className="skel" style={{ width: '38%', height: 18 }} />{Array.from({ length: rows }).map((_, i) => <div key={i} className="skel" style={{ width: (92 - i * 13) + '%' }} />)}</div>
export const PageLoading = ({ narrow }) => <div className={'wrap' + (narrow ? ' narrow' : '')}><Loading rows={2} /><Loading rows={4} /></div>

export const Empty = ({ icon = 'inbox', title, children }) => <div className="empty"><span className="empty-ico"><Icon name={icon} size={22} /></span>
  {title && <strong>{title}</strong>}{children && <span className="mute">{children}</span>}</div>

export const Pill = ({ tone = 'gray', icon, children, title }) => <span className={'pill pill-' + tone} title={title}>{icon && <Icon name={icon} size={14} stroke={2} />}{children}</span>

export const Avatar = ({ text, size = 36, tone }) => <span className={'avatar' + (tone ? ' av-' + tone : '')} style={{ width: size, height: size, fontSize: Math.round(size * 0.36) }} aria-hidden="true">{(text || '?').slice(0, 2).toUpperCase()}</span>

export const PageHead = ({ title, sub, children, crumbs }) => <div className="page-head">
  <div className="page-head-text">{crumbs}<h1>{title}</h1>{sub && <p className="sub">{sub}</p>}</div>{children && <div className="page-actions">{children}</div>}</div>
