import React, { useState, useEffect } from 'react'
import { get, post } from './api.js'
import { useLoad, Err, Level, fmt, fmtDay, Busy, Icon, Loading, Empty, Pill, PageHead, toast } from './common.jsx'
import { TimeChart, COL, DASHN } from './Doctor.jsx'

export function WhatChanged({ pid }) {
  const [open, setOpen] = useState(false)
  const [d, setD] = useState(null)
  const [side, setSide] = useState('')

  return (
    <span className="wc">
      <button
        className="wc-btn"
        aria-label="Что изменилось?"
        title="Что изменилось?"
        aria-expanded={open}
        onClick={async e => {
          if (!open) {
            setSide(e.currentTarget.getBoundingClientRect().left > window.innerWidth / 2 ? ' r' : '')
            setOpen(true)
            const data = await get(`/api/psychiatrist/patients/${pid}/what-changed`)
            setD(data)
          } else {
            setOpen(false)
  }
        }}
      >
        ?
      </button>
      {open && (
        <div className={'wc-pop card' + side} role="dialog" aria-label="Что изменилось">
          {!d ? (
            <Loading rows={2} />
          ) : (
            <>
              <h4>Что изменилось{d.period.from ? ' с ' + fmtDay(d.period.from) : ''}</h4>
              <ul>
                {d.lines.map((l, i) => (
                  <li key={i}>{l}</li>
                ))}
              </ul>
              {d.attention.length > 0 && (
                <>
                  <h4>Требует внимания</h4>
                  <ul>
                    {d.attention.map((l, i) => (
                      <li key={i}>{l}</li>
                    ))}
                  </ul>
                </>
              )}
              <p className="xs mute">{d.note}</p>
            </>
          )}
          <button className="link" onClick={() => setOpen(false)}>
            Закрыть
          </button>
        </div>
      )}
    </span>
  )
}

export function PatientPicker({ value, onChange }) {
  const [data, err] = useLoad(() => get('/api/psychiatrist/patients'), [])

  useEffect(() => {
    if (data && data.length > 0 && value == null) {
      onChange(data[0].patient_id)
    }
  }, [data, value])

  if (data && data.length === 0) {
    return (
      <Empty icon="users" title="Пациентов пока нет">
        Здесь появятся пациенты после направления лечащим врачом
      </Empty>
    )
  }

  if (err) {
    return <Err e={err} />
  }

  return (
    <div className="pk" role="tablist">
      {data && data.map((p) => (
        <button
          key={p.patient_id}
          role="tab"
          aria-selected={value === p.patient_id}
          className={'pk-chip' + (value === p.patient_id ? ' on' : '')}
          onClick={() => onChange(p.patient_id)}
        >
          <Level l={p.level} short />
          <b>{p.code}</b>
          <span className="xs mute">{p.referral_status}</span>
        </button>
      ))}
    </div>
  )
}

export function PsyCard({ pid }) {
  const [d, err] = useLoad(() => get(`/api/psychiatrist/patients/${pid}/card`), [pid])

  if (err) {
    return <Err e={err} />
  }

  if (!d) {
    return <Loading rows={3} />
  }

  const QA = ({ q, a }) => a ? <div className="ps-qa"><span className="ps-q">{q}</span><span className="ps-a">{a}</span></div> : null

  return (
    <div className="ps-card">
      {d.diagnosis && <p className="small"><b>Диагноз:</b> {d.diagnosis.code}{d.diagnosis.title ? ' — ' + d.diagnosis.title : ''}</p>}
      <p className="small">
        Направление {d.referral.rule_id} · {d.referral.status} · от{' '}
        {fmt(d.referral.confirmed_at)}{d.referral.accepted_at ? ' · подтверждён психиатром ' + fmtDay(d.referral.accepted_at) : ''}{' '}
        <a className="link" href="#/psy/referrals">
          Сводка и решение по направлению
        </a>
      </p>
      <div className="dy-grid">
        <div className="ps-sec">
          <h4>
            <Icon name="clipboard" size={16} /> Анамнез
</h4>
          <QA q="Начало симптомов" a={d.anamnesis.onset} />
          <QA q="Предыдущие эпизоды и ремиссии" a={d.anamnesis.episodes} />
          <QA q="Симптомы" a={d.anamnesis.symptoms} />
          <QA q="Тревога" a={d.anamnesis.anxiety} />
          <QA q="Панические приступы" a={d.anamnesis.panic} />
          <QA q="Сон за последнюю неделю (чек-ин)" a={d.anamnesis.sleep_recent} />
        </div>
        <div className="ps-sec">
          <h4>
            <Icon name="activity" size={16} /> Функционирование
</h4>
          <QA q="Влияние на работу, учёбу, отношения, повседневные дела" a={d.functioning.impact} />
        </div>
        <div className="ps-sec">
          <h4>
            <Icon name="pill" size={16} /> Предшествующее лечение
</h4>
          <QA q="Помощь ранее" a={d.treatment.help} />
          {d.treatment.order && (
            <QA
              q="Текущая терапия"
              a={d.treatment.order.drug + ' — ' + d.treatment.order.regimen + ', с ' + fmtDay(d.treatment.order.started_on)}
            />
          )}
          <QA q="Препараты" a={d.treatment.meds.map(m => m.name + (m.dose ? ' ' + m.dose : '')).join(', ')} />
          <QA q="Со слов пациента" a={d.treatment.meds_from_intake} />
          <QA q="Переносимость" a={d.treatment.ae.map(x => (x.symptom || 'нежелательное явление') + ' — ' + x.severity + (x.persists ? ', сохраняется' : ''))} />
        </div>
        <div className="ps-sec">
          <h4>
            <Icon name="alert" size={16} /> Факторы риска
</h4>
          {d.risks.suicidal && <QA q="Мысли о смерти (анкета)" a={d.risks.suicidal} />}
          {d.risks.safety_followup.map((x, i) => (
            <QA key={i} q={'Уточняющий вопрос: ' + x.q} a={x.a} />
          ))}
          <QA q="Сопутствующие заболевания" a={d.risks.comorbid.join('; ')} />
          <QA q="Вещества (алкоголь)" a={d.risks.substances} />
          <QA q="Семейный анамнез" a={d.risks.family} />
          {d.risks.drug.contraindications.map((c, i) => (
            <QA key={'c' + i} q="Противопоказание" a={c.text + (c.ohlp_section ? ' (ОХЛП ' + c.ohlp_section + ')' : '')} />
          ))}
          {d.risks.drug.interactions.map((x, i) => (
            <QA key={'x' + i} q="Взаимодействие" a={x.title + (x.med ? ' — ' + x.med : '')} />
          ))}
        </div>
        <div className="ps-sec">
          <h4>
            <Icon name="list" size={16} /> Обследования
</h4>
          {d.exams.scales.length ? (
            d.exams.scales.map(s => (
              <QA key={s.id} q={s.title} a={s.latest + (s.label ? ' — ' + s.label : '') + (s.count > 1 ? ' (исходно ' + s.baseline + ', заполнений ' + s.count + ')' : '')} />
            ))
          ) : (
            <p className="small mute">Опросники не заполнялись</p>
          )}
        </div>
      </div>
    </div>
  )
}

export function PsyHome() {
  const [sel, setSel] = useState(null)
  const [open, setOpen] = useState(null)
  const [d, err, reload] = useLoad(() => get('/api/psychiatrist/overview'), [])

  if (err) {
    return <div className="wrap"><Err e={err} /></div>
  }

  if (!d) {
    return <div className="wrap"><Loading rows={3} /></div>
  }

  const ICON = {
    new: 'inbox',
    worsening: 'activity',
    adverse_events: 'pill',
    risks: 'alert',
    confirmed: 'checkCircle',
    reassessment: 'calendar',
    overdue: 'clock'
  }

  const cur = sel ? d.buckets.find(b => b.id === sel) : null

  return (
    <div className="wrap">
      <PageHead title="Мои пациенты" sub="Пациенты, проходящие лечение или направленные лечащим врачом. Выберите раздел." />
      <section className="card">
        <div className="ps-grid">
          {d.buckets.map(b => (
            <button
              key={b.id}
              className={'ps-tile' + (sel === b.id ? ' on' : '')}
              aria-pressed={sel === b.id}
              onClick={() => {
                setSel(sel === b.id ? null : b.id)
                setOpen(null)
              }}
            >
              <Icon name={ICON[b.id] || 'users'} size={20} />
              <span className="ps-title">{b.title}</span>
              <span className="ps-count">{b.patients.length}</span>
            </button>
          ))}
        </div>
        {cur && (
          <div className="ps-list">
            {cur.patients.length === 0 ? (
              <Empty icon="inbox" title="Пока никого" />
            ) : (
              cur.patients.map(x => (
                <div key={sel + x.patient_id + x.note} className={'ps-row' + (open === x.patient_id ? ' open' : '')}>
                  <div className="ps-head">
                    <button className="link" aria-expanded={open === x.patient_id} onClick={() => setOpen(open === x.patient_id ? null : x.patient_id)}>
                      <span className="ps-code">{x.code}</span>
      <span className="ps-note">{x.note}</span>
      {x.at && <span className="xs mute">{fmt(x.at)}</span>}
      <Icon name={open === x.patient_id ? 'down' : 'right'} size={16} />
    </button>
    {sel === 'new' && x.referral_id && <Busy cls="sec" onClick={async () => { await post('/api/psychiatrist/referrals/' + x.referral_id + '/accept', {}); toast('Пациент подтверждён'); reload() }}>Подтвердить</Busy>}
    <WhatChanged pid={x.patient_id} />
</div>
    {open === x.patient_id && <PsyCard pid={x.patient_id} />}
</div>
))
)}
</div>
)}
</section>
</div>
)
}
const KIND = { alert: 'Сигнал', drug: 'Препарат', routing: 'Направление' }
const chg = x => typeof x === 'string' ? x : Array.isArray(x) ? x.join('; ') : x && typeof x === 'object' ? Object.values(x).filter(v => v != null && v !== '').join('; ') : String(x)

export function PsyDynamics() {
  const [pid, setPid] = useState(null);
  const [d, err] = useLoad(() => pid ? get('/api/psychiatrist/patients/' + pid + '/dynamics') : Promise.resolve(null), [pid]);
  return <div className="wrap">
    <PageHead title="Динамика состояния" sub="Самоотчёты PHQ-9 и GAD-7, ежедневные отметки, терапия и нежелательные явления на одной оси времени." />
    <PatientPicker value={pid} onChange={setPid} />
    {err ? <Err e={err} /> : !d ? <Loading rows={3} /> : <section className="card">
      <div className="row">
        <h3 style={{ margin: 0 }}>{d.patient.code}</h3>
        <WhatChanged pid={pid} />
      </div>
      {Object.keys(d.series).length ? <>
        <div className="chart-legend">{Object.entries(d.series).map(([k, v], i) => <span key={k}><i style={{ borderTopColor: COL[i % 3], borderTopStyle: DASHN[i % 3] }} />{v.title}</span>)}
          {d.events.length > 0 && <span className="xs mute">Отметки на оси: начало терапии и нежелательные явления</span>}</div>
        <TimeChart series={Object.entries(d.series)} events={d.events} range={12} /></> : <p className="small mute">Шкалы ещё не заполнялись</p>}
      <div className="dy-grid">
        <div className="ps-sec">
          <h4>Сопоставление с предыдущим самоотчётом</h4>
          {Object.entries(d.series).map(([k, s]) => <p key={k} className="small">
            <b>{s.title}:</b> {s.previous != null ? s.previous + ' → ' + s.latest : 'одно заполнение: ' + s.latest} (исходно {s.baseline})
          </p>)}
        </div>
        <div className="ps-sec">
          <h4>Терапия</h4>
          {d.therapy ? <p className="small">{d.therapy.drug}: {d.therapy.regimen}, начата {fmtDay(d.therapy.started_on)}{d.therapy.doctor_changes ? '; изменения врача: ' + chg(d.therapy.doctor_changes) : ''}</p> : <p className="small mute">Назначения нет</p>}
          <h4>Нежелательные явления</h4>
          {d.ae.length ? <ul className="small">{d.ae.map((a, i) => <li key={i}>{a.symptom || 'нежелательное явление'} — {a.severity}{a.persists ? ', сохраняется' : ''} · {fmtDay(a.at)}</li>)}</ul> : <p className="small mute">Не отмечены</p>}
        </div>
        <div className="ps-sec">
          <h4>Пропущенные оценки и периоды без данных</h4>
          {d.missed_assessments.map((m, i) => <p key={i} className="small">{m}</p>)}
          {d.gaps.map((g, i) => <p key={'g' + i} className="small">Нет чек-инов {g.days} дн.: {fmtDay(g.from)} — {fmtDay(g.to)}</p>)}
          {!d.missed_assessments.length && !d.gaps.length && <p className="small mute">Пропусков нет</p>}
        </div>
      </div>
      <h4>Сон, настроение и тревога по чек-инам</h4>
      <p className="xs mute">{d.activity_note}</p>
      <div style={{ overflowX: 'auto' }}>
        <table className="dy-table">
          <thead>
            <tr><th>Дата</th><th>Сниженное настроение, 0–10</th><th>Тревога, 0–10</th><th>Сон</th><th>Приём лекарства</th><th>Неприятные ощущения</th></tr>
          </thead>
          <tbody>
            {d.checkins.slice(-14).reverse().map(c => <tr key={c.day}><td>{fmtDay(c.day)}</td><td>{c.mood_low ?? '—'}</td><td>{c.anxiety ?? '—'}</td><td>{c.sleep || '—'}</td><td>{c.doses || '—'}</td><td>{c.side_effects || '—'} </td></tr>)}
          </tbody>
        </table>
      </div>
    </section>}
  </div>;
}

export function PsyRecommendations() {
  const [d, err, reload] = useLoad(() => get('/api/psychiatrist/recommendations'), []);
  const [c, setC] = useState({});
  if (err) return <div className="wrap"><Err e={err} /></div>;
  if (!d) return <div className="wrap"><Loading rows={4} /></div>;
  if (!d.length) return <div className="wrap"><Empty icon="sparkle" title="Рекомендаций нет">Появятся, когда врач направит пациента к психиатру.</Empty></div>;

  return <div className="wrap">
    <PageHead title="Клинические рекомендации" sub="Изменения и их значимость, варианты оценки, проверки противопоказаний и взаимодействий, источник." />
    {d.map(p => <section key={p.patient_id} className="card">
      <div className="row">
        <Level l={p.level} />
        <h3 style={{ margin: 0 }}>{p.code}</h3>
        <WhatChanged pid={p.patient_id} />
      </div>
      {p.items.map(it => <div key={it.key} className="rc-item">
        <span className="rc-kind">{KIND[it.kind] || it.kind}</span>
        <p><b>{it.found}</b></p>
        {it.basis && <p className="small"><b>Основание:</b> {it.basis}</p>}
        {it.next_step && <p className="small"><b>Предлагаемая оценка:</b> {it.next_step}</p>}
        {(it.risks.length > 0 || it.clarify.length > 0) && <p className="small"><b>Проверить:</b> {[...it.risks, ...it.clarify].join('; ')}</p>}
        {it.source && it.source.id && <p className="xs">Источник: <a href={'#/sources/' + it.source.id}>{it.source.title}</a></p>}
        {it.decision ? <p className="rc-done small"><Pill tone={it.decision.label === 'Отклонено' ? 'gray' : 'green'}>{it.decision.label}</Pill> {it.decision.comment} <span className="xs mute">{fmt(it.decision.at)}</span></p> :
          <div className="rc-dec">
            <input aria-label="Комментарий психиатра" placeholder="Комментарий (обязателен для «Изменить» и «Отклонить»)" value={c[it.key] || ''} onChange={e => setC({ ...c, [it.key]: e.target.value })} />
            {[['confirm', 'Подтвердить'], ['modify', 'Изменить'], ['reject', 'Отклонить']].map(([k, l]) => <Busy key={k} cls={k === 'confirm' ? '' : 'sec'} disabled={k !== 'confirm' && (c[it.key] || '').trim().length < 3} onClick={async () => { await post('/api/psychiatrist/recommendations/' + p.patient_id + '/decision', { item_key: it.key, decision: k, comment: c[it.key] || '' }); reload(); toast('Решение записано') }}>{l}</Busy>)}
          </div>}
      </div>)}
    </section>)}
  </div>;
}

export function PsyPlan() {
  const [pid, setPid] = useState(null);
  const [d, err] = useLoad(() => pid ? get('/api/psychiatrist/patients/' + pid + '/plan') : Promise.resolve(null), [pid]);
  return <div className="wrap">
    <PageHead title="План лечения и наблюдения" sub="Согласованный план, терапия, переносимость, сроки следующей оценки и история решений." />
    <PatientPicker value={pid} onChange={setPid} />
    {err ? <Err e={err} /> : !d ? <Loading rows={3} /> : <section className="card">
      <div className="row">
        <h3 style={{ margin: 0 }}>{d.patient.code}</h3>
        <WhatChanged pid={pid} />
      </div>
      <div className="dy-grid">
        <div className="ps-sec">
          <h4>Согласованный план</h4>
          {d.agreed_plan.sections.length ? d.agreed_plan.sections.map((s, i) => <p key={i} className="small">{s.label}: {s.text}</p>) : <p className="small mute">План пока не заполнен</p>}
          <p className="xs mute">{d.agreed_plan.confirmed_by_doctor ? 'Подтверждён врачом' : 'Врач ещё не подтвердил план'} </p>
        </div>
        <div className="ps-sec">
          <h4>Текущая терапия</h4>
          {d.therapy.length ? d.therapy.map((t, i) => <p key={i} className="small">{t.drug}: {t.regimen}, с {fmtDay(t.started_on)}{t.stopped ? ' (отменено)' : ''}{t.doctor_changes ? '; изменения врача: ' + chg(t.doctor_changes) : ''}</p>) : <p className="small mute">Назначений нет</p>}
        </div>
        <div className="ps-sec">
          <h4>Переносимость и нежелательные явления</h4>
          {d.tolerance.length ? <ul className="small">{d.tolerance.map((a, i) => <li key={i}>{a.symptom || 'нежелательное явление'} — {a.severity}{a.persists ? ', сохраняется' : ''}</li>)}</ul> : <p className="small mute">Не отмечены</p>}
        </div>
        <div className="ps-sec">
          <h4>Следующая оценка и визиты</h4>
          <p className="small">Следующая оценка PHQ-9 и GAD-7: {d.next_assessment ? fmtDay(d.next_assessment) : 'не запланирована'}</p>
          {d.visits.map((v, i) => <p key={i} className="small"><Icon name="calendar" size={14} /> {fmt(v.at)}{v.note ? ' — ' + v.note : ''}</p>)}
          {!d.visits.length && <p className="small mute">Контрольный визит не назначен</p>}
        </div>
        <div className="ps-sec">
          <h4>Цели пациента</h4>
          {d.goal ? <p className="small">«{d.goal.text}» <span className="xs mute">({d.goal.by})</span></p> : <p className="small mute">Цель не сформулирована</p>}
        </div>
        <div className="ps-sec">
          <h4>История решений</h4>
          {d.history.length ? <ul className="small pl-list">{d.history.map((h, i) => <li key={i}>{h.at ? fmt(h.at) + ' · ' : ''}{h.who}: {h.text}</li>)}</ul> : <p className="small mute">Решений пока нет</p>}
        </div>
      </div>
    </section>}
  </div>;
}

export function PsyMessages() {
  const [d, err, reload] = useLoad(() => get('/api/psychiatrist/messages'), []);
  if (err) return <div className="wrap"><Err e={err} /></div>;
  if (!d) return <div className="wrap"><Loading rows={4} /></div>;
  if (!d.length) return <div className="wrap"><Empty icon="message" title="Сообщений нет" /></div>;
  
  return <div className="wrap">
    <PageHead title="Сообщения от пациентов" sub="Самоотчёты между приёмами, вопросы о переносимости, изменения самочувствия." />
    {d.map(p => <section key={p.patient_id} className="card">
      <div className="row">
        <h3 style={{ margin: 0 }}>{p.code}</h3>
        <WhatChanged pid={p.patient_id} />
        <span className="grow" />
        {p.unread > 0 && <Pill tone="amber">непрочитанных: {p.unread}</Pill>}
        {p.needs_reply > 0 && <Pill tone="brand">ждут ответа: {p.needs_reply}</Pill>}
      </div>
      {p.items.length === 0 ? <p className="small mute">Пока нет</p> : p.items.map((m, i) => <div key={i} className={'ms-item' + (m.read ? '' : ' unread')}>
        <div className="row">
          <Pill tone={m.kind === 'message' ? 'brand' : m.kind === 'tolerance' ? 'amber' : m.kind === 'state' ? 'violet' : 'gray'}>{m.type}</Pill>
          <span className="xs mute">{fmt(m.at)}</span>
          <span className="grow" />
          {m.needs_reply && <span className="xs">нужен ответ</span>}
          {!m.read && <Busy cls="sec" onClick={async () => { await post('/api/psychiatrist/messages/' + m.id + '/read', {}); reload(); toast('Отмечено как прочитанное') }}>Прочитано</Busy>}
        </div>
        <p className="small">{m.text}</p>
        {m.context.length > 0 && <p className="ms-ctx xs mute">В истории: {m.context.join('; ')}</p>}
      </div>)}
    </section>)}
  </div>;
}
