import React, { useState } from 'react'
import { get, post } from './api.js'
import { useLoad, Err, Level, fmt, fmtDay, Busy, Icon, Loading, Empty, Pill, PageHead, toast } from './common.jsx'
import DsEdit from './DsEdit.jsx'

export function Buckets() {
  const [d, err] = useLoad(() => get('/api/doctor/overview'), [])
  const [sel, setSel] = useState(null)
  const [open, setOpen] = useState(null)

  if (err) return <Err e={err} />
  if (!d) return <div className="card"><Loading rows={2} /></div>

  const ICON = {
    on_treatment: 'pill',
    new_intake: 'clipboard',
    worsening: 'alert',
    referrals: 'users',
    visits: 'calendar'
  }

  const cur = d.buckets.find(b => b.id === sel)
  return (
    <section className="card bk" aria-label="Мои пациенты по категориям">
      <div className="row">
        <h2 style={{ margin: 0 }}>Разделы</h2>
        <span className="grow" />
        <span className="small mute">Выберите раздел, чтобы увидеть пациентов</span>
      </div>
      <div className="bk-grid">
        {d.buckets.map(b => (
          <button
            key={b.id}
            className={'bk-tile' + (sel === b.id ? ' on' : '')}
            aria-pressed={sel === b.id}
            onClick={() => { setSel(sel === b.id ? null : b.id); setOpen(null) }}
          >
            <Icon name={ICON[b.id] || 'users'} size={20} />
            <span className="bk-title">{b.title}</span>
            <span className="bk-count">{b.patients.length}</span>
  </button>
        ))}
      </div>
      {cur && (
        <div className="bk-list">
          {cur.patients.length === 0 ? (
            <Empty icon="inbox" title="Пока никого">В этом разделе нет пациентов</Empty>
          ) : (
            cur.patients.map(x => (
              <div key={sel + x.patient_id + x.note} className={'bk-row' + (open === x.patient_id ? ' open' : '')}>
                <button className="link bk-head" aria-expanded={open === x.patient_id} onClick={() => setOpen(open === x.patient_id ? null : x.patient_id)}>
                  <span className="bk-code">{x.code}</span>
                  <span className="bk-note">{x.note}</span>
                  {x.at && <span className="xs mute">{fmt(x.at)}</span>}
                  <Icon name={open === x.patient_id ? 'down' : 'right'} size={16} />
                </button>
                {open === x.patient_id && <BriefCard id={x.patient_id} />}
              </div>
            ))
          )}
        </div>
      )}
    </section>
  )
}

export function BriefCard({ id }) {
  const [d, err, , setD] = useLoad(() => get('/api/doctor/patients/' + id + '/brief'), [id])

  if (err) return <Err e={err} />
  if (!d) return <Loading rows={3} />

  const Sec = ({ title, icon, children }) => (
    <div className="bf-sec">
      <h4><Icon name={icon} size={16} />{title}</h4>
      {children}
    </div>
  )

  const QA = ({ q, a }) => a ? <div className="bf-qa"><span className="bf-q">{q}</span><span className="bf-a">{a}</span></div> : null

  return (
    <div className="bf">
      <div className="row">
        <span className="small mute">Анкета: {d.intake_progress.answered} из {d.intake_progress.total}</span>
        <span className="grow" />
        {d.reviewed ? (
          <Pill tone="green" icon="checkCircle">Анкета просмотрена</Pill>
        ) : (
          <Busy cls="sec" onClick={async () => {
            await post('/api/doctor/patients/' + id + '/intake-reviewed')
            setD({ ...d, reviewed: true }); toast('Отмечено: анкета просмотрена')
          }}>
            <Icon name="check" size={16} />Анкета просмотрена
          </Busy>
        )}
        <a href={'#/doctor/patient/' + id}><button className="sec"><Icon name="external" size={16} />Полная карточка</button></a>
      </div>
      <div className="bf-grid">
        <Sec title="Краткая анкета и история симптомов" icon="clipboard">
          {d.intake.map(x => <QA key={x.id} q={x.q} a={x.a} />)}
        </Sec>
        <Sec title="PHQ-9 и GAD-7" icon="activity">
          {d.scales.length === 0 ? (
            <p className="small mute">Шкалы ещё не заполнены</p>
) : (
            d.scales.map(s => (
              <div key={s.id} className="bf-scale">
                <b>{s.title}: {s.latest}</b>
                {s.label && <span className="small">{s.label}</span>}
                <span className="xs mute">{s.count > 1 ? 'исходно ' + s.baseline + ' · заполнений ' + s.count : 'одно заполнение'}{s.date ? ' · ' + fmtDay(s.date) : ''}</span>
              </div>
            ))
          )}
        </Sec>
        <Sec title="Длительность и влияние на жизнь" icon="calendar">
          <QA q="Когда появились симптомы" a={d.duration_impact.duration} />
          <QA q="Насколько мешают" a={d.duration_impact.impact} />
        </Sec>
        <Sec title="Предыдущие эпизоды и лечение" icon="list">
          <QA q="Похожие периоды раньше" a={d.history.episodes} />
          <QA q="Помощь, которую получал(а)" a={d.history.help} />
        </Sec>
        <Sec title="Заболевания, препараты, аллергии" icon="pill">
          <QA q="Хронические заболевания" a={d.somatic.chronic} />
          <QA q="Неврологические события" a={d.somatic.neuro} />
          <QA q="Соматические состояния" a={d.somatic.somatic} />
          {d.somatic.order && <QA q="Назначено" a={d.somatic.order.drug + ' — ' + d.somatic.order.regimen + ', с ' + fmtDay(d.somatic.order.started_on)} />}
          <QA q="Препараты (врач)" a={d.somatic.meds.map(m => m.name + (m.dose ? ' ' + m.dose : '')).join(', ')} />
          <QA q="Препараты (со слов пациента)" a={d.somatic.meds_from_intake} />
          <QA q="Аллергия на компоненты" a={{ yes: 'да', no: 'нет', unknown: 'неизвестно' }[d.somatic.hypersensitivity] || 'нет данных'} />
        </Sec>
        <Sec title="Факторы риска и противопоказания" icon="alert">
          {d.risks.contraindications.map((c, i) => (
            <div key={'c' + i} className="bf-risk ci">
              <Pill tone="red" icon="alert">Противопоказание</Pill>
              {c.text}
              {c.ohlp_section && <span className="xs mute"> · ОХЛП {c.ohlp_section}</span>}
            </div>
          ))}
          {d.risks.interactions.map((x, i) => (
            <div key={'x' + i} className="bf-risk">
              <Pill tone={x.level === 'red' ? 'red' : 'amber'} icon="pill">{x.title}</Pill>
              {x.med}
            </div>
          ))}
          {d.risks.cautions.map((c, i) => (
            <div key={'w' + i} className="bf-risk">
              <Pill tone="yellow">Осторожность</Pill>
              {c}
            </div>
          ))}
          {d.risks.risk_factors.map((r, i) => (
            <div key={'r' + i} className="bf-risk">
              <Pill tone="violet">{r.text}</Pill>
              <span className="small">{r.answer}</span>
            </div>
          ))}
          {d.risks.contraindications.length === 0 && d.risks.interactions.length === 0 && d.risks.cautions.length === 0 && d.risks.risk_factors.length === 0 && (
            <p className="small mute">По введённым данным не выявлено</p>
          )}
        </Sec>
      </div>
    </div>
  )
}

const KIND = { routing: ['Маршрутизация', 'users'], drug: ['Препарат', 'pill'], alert: ['Сигнал', 'alert'] }
const SEV = { mild: 'лёгкое', moderate: 'умеренное', moderate_to_severe: 'выраженное' }
const TONE = { contraindicated: 'red', interaction_requires_decision: 'amber', safety_check_incomplete: 'yellow', out_of_indication: 'violet' }

export function Hints() {
  const [d, err] = useLoad(() => get('/api/doctor/hints'), []);

  if (err) return <div className="wrap"><Err e={err} /></div>;
  if (d === null) return <div className="wrap"><Loading rows={3} /></div>;

  if (!d.length) {
    return <div className="wrap"><Empty icon="sparkle" title="Подсказок нет">Новых оснований для подсказок не найдено</Empty></div>;
  }

  return <div className="wrap">
    <PageHead title="Клинические подсказки" />
    {d.map(p => <section className="card hn-card" key={p.patient_id}>
      <div className="row">
        <h3 style={{ margin: 0 }}>{p.code}</h3>
        <Level l={p.level} />
        <span className="grow" />
        <a className="link" href={'#/doctor/patient/' + p.patient_id}>Открыть карточку</a>
      </div>
      {p.items.map((it, i) => <div className="hn-item" key={i}>
        <div className="row">
          <span className="hn-kind"><Icon name={KIND[it.kind][1]} size={16} />{KIND[it.kind][0]}{it.kind === 'routing' ? (it.tier === 'mandatory' ? ' · обязательно' : ' · желательно') : ''}</span>
        </div>
        <p className="hn-found"><b>Что обнаружено:</b> {it.found}</p>
        <p className="hn-basis"><b>Основание:</b> {it.basis}</p>
        {it.clarify.length > 0 && <div className="hn-block"><h5>Что нужно уточнить</h5><ul>{it.clarify.map((w, k) => <li key={k}>{w}</li>)}</ul></div>}
        {it.risks.length > 0 && <div className="hn-block"><h5>Риски и ограничения для проверки</h5><ul>{it.risks.map((w, k) => <li key={k}>{w}</li>)}</ul></div>}
        {it.next_step && <p className="hn-next"><Icon name="right" size={16} /><b>Предлагаемый шаг:</b> {it.next_step}</p>}
        {it.source && it.source.id && <p className="hn-src xs"><Icon name="book" size={14} />Источник: <a href={'#/sources/' + it.source.id}>{it.source.title}</a></p>}
      </div>)}
    </section>)}
  </div>;
}

export function DoctorReferrals() {
  const [d, err, reload] = useLoad(() => get('/api/doctor/referrals'), []);

  const [f, setF] = useState({ patient: '', rule: '', comment: '' });
  if (err) return <div className="wrap"><Err e={err} /></div>;
  if (d === null) return <div className="wrap"><Loading rows={3} /></div>;

  const STEPS = [['created', 'Создано'], ['received', 'Получено'], ['accepted', 'Подтверждено психиатром'], ['completed', 'Завершено']];

  return <div className="wrap">
    <PageHead title="Направления и передача пациентов" />
    <section className="card rf-form">
      <h3>Создать направление к психиатру</h3>
      <label htmlFor="rf-p">Пациент</label>
      <select id="rf-p" value={f.patient} onChange={e => setF({ ...f, patient: e.target.value })}>
        <option value="">— выберите —</option>
        {d.patients.map(p => <option key={p.id} value={p.id}>{p.code}</option>)}
      </select>
      <label htmlFor="rf-r">Основание для направления</label>
      <select id="rf-r" value={f.rule} onChange={e => setF({ ...f, rule: e.target.value })}>
        <option value="">— выберите —</option>
        {d.bases.map(b => <option key={b.id} value={b.id}>{(b.kind === 'mandatory' ? 'Обязательно: ' : 'Желательно: ') + b.title}</option>)}
      </select>
      <label htmlFor="rf-c">Комментарий для психиатра</label>
      <textarea id="rf-c" value={f.comment} onChange={e => setF({ ...f, comment: e.target.value })} />
      <p className="xs mute">Будут переданы: результаты анкеты и шкал, краткий анамнез, препараты, факторы риска.</p>
      <Busy onClick={async () => {
        await post('/api/doctor/patients/' + f.patient + '/referrals', { rule_id: f.rule, comment: f.comment });
        setF({ patient: '', rule: '', comment: '' });
        reload();
        toast('Направление создано');
      }} disabled={!f.patient || !f.rule}><Icon name="send" size={16} />Создать направление</Busy>
    </section>
    <section className="card">
      <h3>Направления</h3>
      {d.referrals.length === 0 ? <Empty icon="users" title="Направлений пока нет" /> : d.referrals.map(r => <div key={r.id} className="rf-item">
        <div className="row">
          <b>{r.code}</b><span>{r.title}</span>
          <Pill tone={r.status === 'completed' ? 'green' : 'brand'}>{r.status_label}</Pill>
          <span className="grow" />
          <span className="xs mute">создано {fmt(r.confirmed_at)}</span>
        </div>
        <ol className="rf-steps">{STEPS.map(([k, l]) => { const e = r.events.find(x => x.kind === k); return <li key={k} className={'rf-step' + (e ? ' done' : '')}><span>{l}</span>{e && <small>{fmt(e.at)}</small>}</li> })}</ol>
        {r.transmitted.length > 0 && <p className="small"><b>Передано:</b> {r.transmitted.join(', ')}</p>}
      </div>)}
    </section>
  </div>;
}

export function DrugSafety() {
  const [d, err, reload] = useLoad(() => get('/api/doctor/drug-safety'), []);
  const [ed, setEd] = useState(null);

  if (err) return <div className="wrap"><Err e={err} /></div>;
  if (d === null) return <div className="wrap"><Loading rows={3} /></div>;

  return <div className="wrap">
    <PageHead title="Лекарственная безопасность" />
    {d.map(p => <section className="card ds-card" key={p.patient_id}>
      <div className="row">
        <h3 style={{ margin: 0 }}>{p.code}</h3>
        <Pill tone={TONE[p.state] || 'green'} icon="pill">{p.state_label}</Pill>
        <span className="grow" />
        <button className="sec" aria-expanded={ed === p.patient_id} onClick={() => setEd(ed === p.patient_id ? null : p.patient_id)}>{ed === p.patient_id ? 'Скрыть' : 'Изменить'}</button>
      </div>
      {ed === p.patient_id && <DsEdit p={p} onSaved={reload} />}
      <div className="ds-grid">
        <div className="ds-sec">
          <h4>Текущие препараты и дозировки</h4>
          <ul className="ds-list">
            {p.order && <li><b>{p.order.drug}</b> — {p.order.regimen}, с {fmtDay(p.order.started_on)}</li>}
            {p.meds.map((m, k) => <li key={k}>{m.name}{m.dose ? ' — ' + m.dose : ''}{!m.confirmed && <span className="xs mute"> (не подтверждён врачом)</span>}</li>)}
            {!p.order && !p.meds.length && <li className="mute">нет</li>}
          </ul>
          {p.meds_from_intake && <p className="xs mute">Со слов пациента: {p.meds_from_intake}</p>}
        </div>
        <div className="ds-sec">
          <h4>Аллергии и нежелательные явления</h4>
          <p className="small">Аллергия на компоненты препарата: {p.allergy}{p.drug_allergies ? ' — ' + p.drug_allergies : ''}</p>
          {p.ae.length ? <ul className="ds-list">{p.ae.map((a, k) => <li key={k}>{a.symptom || 'нежелательное явление'} — {SEV[a.severity] || a.severity}{a.persists ? ', сохраняется' : ''} <span className="xs mute">{fmtDay(a.at)}</span></li>)}</ul> : <p className="small mute">Не отмечены</p>}
        </div>
        <div className="ds-sec">
          <h4>Недавние изменения терапии</h4>
          {p.changes.length ? <ul className="ds-list">{p.changes.map((c, k) => <li key={k}>{c.text} <span className="xs mute">{c.at ? fmtDay(c.at) : ''}</span></li>)}</ul> : <p className="small mute">Изменений нет</p>}
        </div>
        <div className="ds-sec">
          <h4>Взаимодействия и противопоказания</h4>
          {p.contraindications.map((c, k) => <p key={'c' + k} className="small"><Pill tone="red" icon="alert">Противопоказание</Pill> {c.text}{c.ohlp_section ? ' (ОХЛП ' + c.ohlp_section + ')' : ''}</p>)}
          {p.interactions.map((x, k) => <p key={'x' + k} className="small"><Pill tone={x.level === 'red' ? 'red' : 'amber'}>{x.title}</Pill> {x.med}{x.ohlp_section ? ' (ОХЛП ' + x.ohlp_section + ')' : ''}</p>)}
          {p.cautions.map((c, k) => <p key={'w' + k} className="small"><Pill tone="yellow">Осторожность</Pill> {c}</p>)}
          {(!p.contraindications.length && !p.interactions.length && !p.cautions.length) && <p className="small mute">Не выявлено по введённым данным</p>}
        </div>
        <div className="ds-sec">
          <h4>Нужна дополнительная проверка</h4>
          {p.needs_check.length ? <ul className="ds-list">{p.needs_check.map((n, k) => <li key={k}>{n}</li>)}</ul> : <p className="small mute">Не требуется</p>}
        </div>
      </div>
    </section>)}
  </div>;
}
