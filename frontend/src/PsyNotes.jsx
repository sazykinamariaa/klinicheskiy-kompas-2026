import React, { useState } from 'react'
import { get, post } from './api.js'
import { useLoad, Err, fmt, Icon, Pill, toast } from './common.jsx'

const DEC = [['consult_scheduled', 'Консультация назначена'], ['advice_to_doctor', 'Рекомендации лечащему врачу'], ['back_to_doctor', 'Наблюдение у лечащего врача'], ['other', 'Другое']]

export function PsyBasis({ rid }) {
  const [b] = useLoad(() => get(`/api/psychiatrist/referrals/${rid}/basis`), [rid])
  if (!b) return null
  return <div className="psy-basis"><div className="xs mute" style={{ fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.05em' }}>Почему направлен</div><p style={{ margin: '4px 0' }}><b>{b.rule_id}</b>: {b.title}</p><p className="small mute" style={{ margin: 0 }}>Направил: {b.confirmed_by || '—'} · {fmt(b.confirmed_at)}{b.source && b.source.source ? ' · источник: ' + b.source.source : ''}</p></div>
}

export function PsyNotes({ rid }) {
  const [list, , reload] = useLoad(() => get(`/api/psychiatrist/referrals/${rid}/notes`), [rid])
  const [d, setD] = useState('consult_scheduled')
  const [c, setC] = useState('')
  const [e, setE] = useState(null)
  const [busy, setBusy] = useState(false)
  const save = async () => {
    setE(null)
    setBusy(true)
    try {
      await post(`/api/psychiatrist/referrals/${rid}/notes`, { decision: d, comment: c })
      setC('')
      reload()
      toast('Решение записано')
    } catch (x) {
      setE(x.message)
    }
    setBusy(false)
  }
  return <div className="psy-notes">
    <h3 style={{ marginTop: 16 }}>Решение психиатра</h3>
    {list && list.map(n => <div key={n.id} className="psy-note"><Pill tone="brand">{n.decision_label}</Pill><p style={{ margin: '6px 0 2px' }}>{n.comment}</p><span className="xs mute">{n.author} · {fmt(n.ts)}</span></div>)}
    {list && list.length === 0 && <p className="small mute">Решение ещё не записано.</p>}
    <label htmlFor="psd">Решение</label><select id="psd" value={d} onChange={x => setD(x.target.value)}>{DEC.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
    <label htmlFor="psc">Комментарий (обязателен)</label><textarea id="psc" value={c} onChange={x => setC(x.target.value)} />
    <Err e={e} />
    <button style={{ marginTop: 12 }} disabled={busy || c.trim().length < 3} onClick={save}><Icon name="check" size={18} />Записать решение</button>
  </div>
}

export function DoctorPsyNotes({ pid }) {
  const [list] = useLoad(() => get(`/api/doctor/patients/${pid}/psy-notes`), [pid])
  if (!list || !list.length) return null
  return <div className="card"><div className="card-head"><span className="ico-bubble"><Icon name="users" size={18} /></span><h3>Ответ психиатра</h3></div>{list.map(n => <div key={n.id} className="psy-note"><Pill tone="brand">{n.decision_label}</Pill> <span className="xs faint">{n.rule_id}</span><p style={{ margin: '6px 0 2px' }}>{n.comment}</p><span className="xs mute">{n.author} · {fmt(n.ts)}</span></div>)}</div>
}