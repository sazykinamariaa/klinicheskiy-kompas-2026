// Правка препаратов, аллергий и нежелательных явлений («Лекарственная безопасность»). Черновик — локальная модель, исправлено при проверке.
import React, { useState } from 'react'
import { api, post, put } from './api.js'
import { Busy, toast } from './common.jsx'

const SEV = { mild: 'лёгкое', moderate: 'умеренное', moderate_to_severe: 'выраженное' }

export default function DsEdit({ p, onSaved }) {
  const u = '/api/doctor/patients/' + p.patient_id
  const [name, setName] = useState(''), [dose, setDose] = useState('')
  const [hs, setHs] = useState(p.hypersensitivity || 'unknown'), [al, setAl] = useState(p.drug_allergies || '')
  const [sym, setSym] = useState(''), [sev, setSev] = useState('mild'), [pers, setPers] = useState(true)
  const done = async fn => { await fn(); toast('Сохранено'); onSaved() }
  return <div className="ds-edit">
    <section className="ds-edit-sec"><h5>Препараты</h5>
      {p.meds.map(m => <div key={m.id} className="ds-row"><span>{m.name}{m.dose ? ' — ' + m.dose : ''}</span>
        <Busy cls="sec" onClick={() => done(() => api('DELETE', u + '/meds/' + m.id))}>Убрать</Busy></div>)}
      <div className="ds-row"><input aria-label="Название препарата" placeholder="Название" value={name} onChange={e => setName(e.target.value)} />
        <input aria-label="Доза" placeholder="Доза" value={dose} onChange={e => setDose(e.target.value)} />
        <Busy cls="sec" disabled={name.trim().length < 2} onClick={() => done(async () => { await post(u + '/meds', { name: name.trim(), dose: dose.trim() || null }); setName(''); setDose('') })}>Добавить</Busy></div>
    </section>
    <section className="ds-edit-sec"><h5>Аллергии</h5>
      <div className="ds-row"><select aria-label="Гиперчувствительность к препарату" value={hs} onChange={e => setHs(e.target.value)}>
        <option value="yes">есть</option><option value="no">нет</option><option value="unknown">неизвестно</option></select>
        <input aria-label="Какие аллергии" placeholder="Какие препараты или вещества" value={al} onChange={e => setAl(e.target.value)} />
        <Busy cls="sec" onClick={() => done(async () => { await put(u + '/profile/hypersensitivity', { value: hs }); await put(u + '/profile/drug_allergies', { value: al.trim() || null }) })}>Сохранить</Busy></div>
    </section>
    <section className="ds-edit-sec"><h5>Нежелательные явления</h5>
      {p.ae.map(a => <div key={a.id} className="ds-row"><span>{a.symptom || 'нежелательное явление'} — {SEV[a.severity] || a.severity}{a.persists ? ', сохраняется' : ', прошло'}</span>
        {a.persists && <Busy cls="sec" onClick={() => done(() => put(u + '/ae/' + a.id, { persists: false }))}>Отметить: прошло</Busy>}</div>)}
      <div className="ds-row"><input aria-label="Симптом" placeholder="Симптом" value={sym} onChange={e => setSym(e.target.value)} />
        <select aria-label="Выраженность" value={sev} onChange={e => setSev(e.target.value)}>{Object.entries(SEV).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
        <label className="ds-check"><input type="checkbox" checked={pers} onChange={e => setPers(e.target.checked)} /> Сохраняется</label>
        <Busy cls="sec" disabled={sym.trim().length < 2} onClick={() => done(async () => { await post(u + '/ae', { severity: sev, persists: pers, symptoms: [sym.trim()], note: sym.trim() }); setSym('') })}>Зафиксировать</Busy></div>
    </section>
  </div>
}
