import React, { useState } from 'react'
import { get, post, put } from './api.js'
import { useLoad, Err, Busy, Icon, Loading, toast, fmtDay } from './common.jsx'

export function Methods() {
  const [d, err] = useLoad(() => get('/api/patient/methods'), [])
  if (err) return <div className="wrap"><Err e={err} /></div>
  if (!d) return <div className="wrap"><Loading rows={3} /><Loading rows={3} /></div>
  const t = d.texts
  return (
    <div className="wrap">
      <div className="hello">
        <span className="eyebrow">Самонаблюдение</span>
        <h1>{t.title}</h1>
        <p>{t.lead}</p>
      </div>
      <div className="p-section">{t.regular_title}</div>
      <p className="small mute">{t.regular_lead} {t.interval_label.replace('{days}', d.interval_days)}</p>
      {d.regular.map((r) => (
        <div className="card m-card" key={r.id}>
          <div className="m-head">
            <span className="bub"><Icon name="list" size={22} /></span>
            <div className="m-title">
              <b>{r.title}</b>
              <small>{r.last_at ? t.last_filled.replace('{date}', fmtDay(r.last_at)) : t.never_filled}</small>
            </div>
            {r.due && <span className="m-due">{t.due_now}</span>}
          </div>
          {r.count >= 1 && (
            <div className="m-cmp">
              <div><span>{t.compare_first}</span><b className={'cmp-' + r.vs_first}>{r.vs_first_text}</b></div>
              <div><span>{t.compare_prev}</span><b className={'cmp-' + r.vs_prev}>{r.vs_prev_text}</b></div>
            </div>
)}
          <div className="m-foot">
            <span className="small mute">{t.count_label.replace('{count}', r.count)}{!r.due && r.next_on ? ' · ' + t.next_on.replace('{date}', fmtDay(r.next_on)) : ''}</span>
            <a href={'#/p/scale/' + r.id}>
              <button className={r.due ? '' : 'sec'}>
                {r.count ? t.repeat_button : t.start_button}
                <Icon name="arrowRight" size={18} />
              </button>
            </a>
  </div>
        </div>
      ))}
      <p className="small mute">{t.cmp_note}</p>
      <div className="p-section">{t.extra_title}</div>
      <p className="small mute">{t.extra_lead}</p>
      <div className="p-list">
        {d.reference.map((x) => (
          <div className="p-row m-ref" key={x.id}>
            <span className="bub"><Icon name="clipboard" size={22} /></span>
            <span className="txt">
              <b>{x.title}</b>
              <small>{x.text}</small>
              <small className="m-by">{x.by}</small>
              {x.suggested && <span className="m-suggest" title={x.why}><Icon name="sparkle" size={16} />{x.suggested_text}</span>}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

export function GoalCard() {
  const [d, err, , setD] = useLoad(() => get('/api/patient/goal'), [])
  const [edit, setEdit] = useState(false)
  const [val, setVal] = useState('')
  if (err) return <Err e={err} />
  if (!d) return <Loading rows={2} />
  const t = d.texts
  if (edit) {
    return (
      <div className="card goal-card">
        <div className="goal-head"><span className="bub"><Icon name="sparkle" size={22} /></span><h3>{t.title}</h3></div>
        <textarea value={val} onChange={e => setVal(e.target.value)} placeholder={t.placeholder} aria-label={t.title} />
        <div className="row">
          <button className="sec" onClick={() => setEdit(false)}>Отмена</button>
          <Busy onClick={async () => { setD(await put('/api/patient/goal', { text: val.trim() })); setEdit(false); toast(t.saved) }} disabled={val.trim().length < 3}>{t.save}</Busy>
        </div>
      </div>
    )
  } else {
    return (
      <div className="card goal-card">
        <div className="goal-head">
          <span className="bub"><Icon name="sparkle" size={22} /></span>
          <h3>{t.title}</h3>
          {d.text && <button className="link" onClick={() => { setVal(d.text); setEdit(true) }}><Icon name="edit" size={16} />{t.edit}</button>}
        </div>
        {d.text ? <p className="goal-text">{d.text}</p> : <p className="mute">{t.empty}</p>}
        {!d.text && <button className="sec" onClick={() => setEdit(true)}><Icon name="edit" size={18} />{t.save}</button>}
        {d.text && <p className="small mute">{d.by === 'doctor' ? t.by_doctor : t.by_patient}</p>}
      </div>
    )
  }
}

export function Steps() {
  const [d, , , setD] = useLoad(() => get('/api/patient/achievements'), [])
  if (!d) return null
  if (!d.enabled) {
    return (
      <div className="card steps-off">
        <p className="small mute">{d.texts.hidden_note}</p>
        <Busy cls="sec" onClick={async () => setD(await put('/api/patient/achievements', { enabled: true }))}>
          <Icon name="eye" size={18} />
          {d.texts.show}
        </Busy>
      </div>
    )
  }
  if (!d.visible) return null
  const t = d.texts
  return (
    <div className="card steps">
      <h3>{t.title}</h3>
      <p className="small mute">{t.lead}</p>
      {d.phrase && <p className="steps-phrase"><Icon name="heart" size={18} />{d.phrase}</p>}
      <div className="steps-today">
        <b>{t.today_title}</b>
        <span className={'st-chip' + (d.today.visit ? ' on' : '')}>
          <Icon name={d.today.visit ? 'checkCircle' : 'clock'} size={16} />
          {t.today_visit}
        </span>
        <span className={'st-chip' + (d.today.checkin ? ' on' : '')}>
          <Icon name={d.today.checkin ? 'checkCircle' : 'clock'} size={16} />
          {t.today_checkin}
        </span>
        {d.today.doses_need > 0 && <span className={'st-chip' + (d.today.doses >= d.today.doses_need ? ' on' : '')}>
          <Icon name="pill" size={16} />
          {t.today_doses}: {d.today.doses} / {d.today.doses_need}
        </span>}
      </div>
      <div className="steps-grid">
        {d.items.map(i => (
          <div key={i.id} className={'step' + (i.earned ? ' earned' : '')}>
            <span className="step-ico"><Icon name={i.earned ? 'checkCircle' : 'sparkle'} size={20} /></span>
            <b>{i.title}</b>
            <small>{i.text}</small>
            {!i.earned && i.need > 1 && <span className="step-prog" role="progressbar" aria-valuenow={i.done} aria-valuemax={i.need}><i style={{ width: Math.round(100 * i.done / i.need) + '%' }} /><em>{t.progress.replace('{done}', i.done).replace('{need}', i.need)}</em></span>}
          </div>
        ))}
      </div>
      <button className="link" onClick={async () => setD(await put('/api/patient/achievements', { enabled: false }))}><Icon name="eyeOff" size={16} />{t.hide}</button>
    </div>
  )
}

export function MedToday() {
  const [d, , , setD] = useLoad(() => get('/api/patient/medication'), [])
  if (!d || !d.active) return null
  const allDone = d.slots.every(s => s.taken)
  return (
    <div className="card med-today">
      <div className="med-head">
        <span className="bub"><Icon name="pill" size={22} /></span>
        <div>
          <h3>{d.texts.title}</h3>
          <p className="small mute">{d.drug} · {d.regimen}</p>
        </div>
      </div>
      <div className="med-slots">
        {d.slots.map(s => (
          <div key={s.id} className={'med-slot' + (s.taken ? ' taken' : '')}>
            <span className="pill-ico" aria-hidden="true"><i /></span>
            <b>{s.label}</b>
            {s.taken ? <span className="med-ok"><Icon name="check" size={16} />{d.texts.taken}</span> : <Busy cls="sec" onClick={async () => { setD(await post('/api/patient/medication/dose', { slot: s.id })); toast(d.texts.taken) }}>{d.texts.mark}</Busy>}
          </div>
        ))}
      </div>
      {allDone && <p className="small med-done"><Icon name="checkCircle" size={16} />{d.texts.all_done}</p>}
      {d.with_food && <p className="small mute">{d.with_food}</p>}
    </div>
  )
}

export function MedDetails() {
  const [d] = useLoad(() => get('/api/patient/medication'), [])
  if (!d || !d.active) return null
  return (
    <div className="card med-details">
      <h3><Icon name="pill" size={20} /> {d.texts.details_title}</h3>
      <dl className="kv">
        <dt>Препарат</dt><dd>{d.drug}</dd>
        <dt>Как принимать</dt><dd>{d.regimen}</dd>
        {d.route && <><dt>Способ</dt><dd>{d.route}</dd></>}
        {d.with_food && <><dt>Когда</dt><dd>{d.with_food}</dd></>}
        {d.swallow && <><dt>Как глотать</dt><dd>{d.swallow}</dd></>}
        {d.duration && <><dt>Длительность</dt><dd>{d.duration}</dd></>}
      </dl>
      {d.doctor_changes && <p className="small">Изменения врача: {typeof d.doctor_changes === 'string' ? d.doctor_changes : Object.values(d.doctor_changes).join('; ')}</p>}
      {d.missed_dose && <div className="p-note"><Icon name="info" size={20} /><span><b>{d.texts.missed_title}.</b> {d.missed_dose}</span></div>}
      <p className="small mute">{d.texts.prescribed.replace('{date}', fmtDay(d.started_on))} · {d.source}</p>
      <p className="small mute">{d.texts.note}</p>
    </div>
  )
}