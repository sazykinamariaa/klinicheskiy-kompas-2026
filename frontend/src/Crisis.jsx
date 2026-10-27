import React, { useState } from 'react'
import { get } from './api.js'
import { Icon } from './common.jsx'

export default function Crisis({ s, disclaimer }) {
  const [more, setMore] = useState(false)
  const [d, setD] = useState(null)

  const tel = (s.buttons || []).filter(b => b.tel)
  const main = tel[0]
  const second = tel[1]

  const openMore = async () => {
    if (!more && !d && s.details_available) {
      try {
        const details = await get('/api/patient/support/details')
        setD(details)
      } catch {}
    }
    setMore(!more)
  }

  return <div className="crisis1" role="alert">
    <h1>{s.title}</h1>
    <p className="c1-lines">{(s.lines || []).slice(0, 2).join(' ')}</p>
    {main && <a className="c1-main" href={'tel:' + main.tel}><Icon name="phone" size={28} />{main.label}</a>}
    {second && <a className="c1-second" href={'tel:' + second.tel}><Icon name="phone" size={20} />{second.label}</a>}
    <button className="c1-more" onClick={openMore} aria-expanded={more}>{more ? 'Скрыть' : 'Ещё варианты помощи'}<Icon name={more ? 'x' : 'down'} size={18} /></button>
    {more && <div className="c1-extra">
      {(s.lines || []).slice(2).map((l, i) => <p key={i}>{l}</p>)}
      {(s.buttons || []).filter(b => !b.tel).map(b => b.id === 'contact_doctor' ? <a key={b.id} className="c1-row" href="#/p/messages"><Icon name="message" size={20} />{b.label}</a> : <span key={b.id} className="c1-row off"><Icon name="phone" size={20} />{b.label}<small>номер проверяется</small></span>)}
      {s.after_hours_notice && <p className="c1-note">{s.after_hours_notice}</p>}
      {d && <div className="c1-details"><p><b>{d.lead}</b></p><ul>{(d.instructions || []).map((x, i) => <li key={i}>{x}</li>)}</ul><p>{d.help_to_call}</p><p>{d.doctor_notified_line}</p></div>}
    </div>}
    {disclaimer && <p className="c1-disc">{disclaimer}</p>}
  </div>
}