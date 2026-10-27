import React, { useState } from 'react'
import { get, post } from './api.js'
import { useLoad, Err, Level, fmt, fmtTime, Busy, Icon, Loading, Empty, Pill, PageHead, toast } from './common.jsx'

// Новые пациенты, зарегистрированные по ссылке-приглашению: только факт регистрации, без медицинских данных
function NewPatients() {
  const [d] = useLoad(() => get('/api/duty/new-patients'))
  if (!d || !d.length) return null
  return <section className="card np-card" aria-label="Новые пациенты">
    <div className="card-head"><span className="ico-bubble"><Icon name="users" size={18} /></span><h3>Новые пациенты</h3><span className="dc-cnt">{d.length}</span></div>
    {d.map(p => <div key={p.patient_id} className="np-row">
      <b>{p.patient}</b>
      <Pill tone="brand">{p.status_label}</Pill>
      <span className="xs mute"><Icon name="clock" size={14} /> {fmt(p.registered_at)}</span>
      {p.doctor && <span className="xs mute">лечащий врач: {p.doctor}</span>}
    </div>)}
    <p className="xs mute">Медицинских данных пока нет: анкета и опросники ещё не заполнены.</p>
  </section>
}

export function DutyCenter() {
  const [sel, setSel] = useState('critical')
  const [d, err] = useLoad(() => get('/api/duty/center'))
  const ICON = {
    critical: 'alert',
    urgent_requests: 'heart',
    deterioration: 'activity',
    adverse_events: 'pill',
    unconfirmed: 'bell',
    no_action: 'clock'
  }

  if (err) return <div className="wrap"><Err e={err} /></div>
  if (!d) return <div className="wrap"><Loading rows={3} /></div>

  const cur = d.categories.find(c => c.id === sel) || d.categories[0]

  return <div className="wrap">
    <PageHead title="Центр оповещений" sub="Сигналы по категориям: время, пациент, основание, ответственный, статус." />
    <NewPatients />
    <div className="dc-tabs" role="tablist">
      {d.categories.map(c => <button key={c.id} role="tab" aria-selected={sel === c.id} className={'dc-tab' + (sel === c.id ? ' on' : '')} onClick={() => setSel(c.id)}>
        <Icon name={ICON[c.id] || 'bell'} size={18} /><span>{c.title}</span><span className="dc-cnt">{c.items.length}</span>
      </button>)}
    </div>
    {cur.items.length === 0 ? <div className="card"><Empty icon="checkCircle" title="Сигналов нет">В этой категории сейчас нет сигналов</Empty></div> : <div className="dc-list">
      {cur.items.map(a => <a key={a.id} className="card dc-card" href={'#/alerts/' + a.id}>
        <div className="dc-top">
          <Level l={a.level} />
          <b>{a.patient}</b>
          <span className="grow">{a.title}</span>
          <Icon name="right" size={18} />
        </div>
        {a.basis.length > 0 && <p className="dc-basis small">Основание: {a.basis.join('; ')}</p>}
        <div className="dc-meta xs">
          <span><Icon name="clock" size={14} /> {fmt(a.created_at)}</span>
          <span><Icon name="users" size={14} /> {a.responsible.name} ({a.responsible.how})</span>
          <Pill tone={a.accepted ? 'green' : 'amber'}>{a.status_label}</Pill>
          {a.sla.minutes_left != null && <span className={'dc-sla' + (a.sla.overdue ? ' over' : '')}>{a.sla.overdue ? 'срок подтверждения прошёл ' + Math.abs(a.sla.minutes_left) + ' мин назад' : 'подтвердить в течение ' + a.sla.minutes_left + ' мин'}</span>}
        </div>
      </a>)}
    </div>}
  </div>
}

export function AlertContext({ id }) {
  const [d, err] = useLoad(() => get('/api/duty/alerts/' + id + '/context'), [id])
  const TO = {
    duty_doctor: 'дежурному врачу',
    clinic_admin_on_duty: 'администратору смены'
  }

  if (err) return <Err e={err} />
  if (!d) return <div className="card"><Loading rows={2} /></div>

  return <section className="card ax" aria-label="Сигнал: контекст и хронология">
    <ol className="ax-tl">
      {d.timeline.map(s => <li key={s.step} className={'ax-step' + (s.done ? ' done' : '')}>
        <span className="ax-dot">{s.done ? <Icon name="check" size={14} /> : null}</span>
        <b>{s.label}</b>
        <small>{s.at ? fmt(s.at) : 'ещё нет'}</small>
      </li>)}
    </ol>
    <div className="ax-grid">
      <div className="ax-sec">
        <h4>Что сообщил пациент</h4>
        {d.reported.length ? <ul>{d.reported.map((r, i) => <li key={i}>{r}</li>)}</ul> : <p className="small mute">{d.alert.title}</p>}
        {d.source && <p className="xs mute">Источник: <a href={'#/sources/' + d.source.id}>{d.source.title}</a></p>}
      </div>
      <div className="ax-sec">
        <h4>Когда поступил и какие данные есть</h4>
        <p className="small">Поступил: {fmt(d.alert.created_at)}</p>
        {d.data.last_scale && <p className="small">Последняя шкала: {d.data.last_scale.scale.toUpperCase()} = {d.data.last_scale.total}, {fmt(d.data.last_scale.at)}</p>}
        <p className="small">Последний чек-ин: {d.data.last_checkin || 'нет'} </p>
        <p className="small">Ответов в анкете: {d.data.intake_answers}</p>
      </div>
      <div className="ax-sec">
        <h4>Приоритет по протоколу</h4>
        <p className="small"><b>{d.priority.label}</b></p>
        {d.priority.ack_minutes && <p className="small">Подтвердить получение: в течение {d.priority.ack_minutes} мин</p>}
        {d.priority.escalation.map((e, i) => <p key={i} className="xs mute">Нет ответа {e.after_minutes} мин — эскалация {TO[e.to] || e.to}</p>)}
        <p className="small">Ответственный: {d.alert.responsible.name} ({d.alert.responsible.how})</p>
      </div>
      <div className="ax-sec">
        <h4>Предыдущие значимые события</h4>
        {d.previous.length ? <ul>{d.previous.map(p => <li key={p.id} className="small"><Level l={p.level} /> {p.title} <span className="xs mute">{fmt(p.created_at)} · {p.status_label}</span></li>)}</ul> : <p className="small mute">Других сигналов нет</p>}
      </div>
    </div>
    {d.protocol && <div className="ax-proto">
      <h4><Icon name="clipboard" size={16} /> Инструкции по реагированию: {d.protocol.title}</h4>
      <ol>{d.protocol.algorithm.map((s, i) => <li key={i}>{s}</li>)}</ol>
      {d.protocol.emergency && d.protocol.emergency.show && <div className="ax-em">{d.protocol.emergency.numbers.map(n => <a key={n.tel} href={'tel:' + n.tel}><button className="sec"><Icon name="phone" size={16} />{n.tel} — {n.label}</button></a>)}</div>}
      <p className="xs mute">{d.system_note}</p>
    </div>}
  </section>
}

export function Protocols() {
  const [d, err] = useLoad(() => get('/api/duty/protocols'))
  if (err) return <div className="wrap"><Err e={err} /></div>
  if (!d) return <div className="wrap"><Loading rows={3} /></div>

  return <div className="wrap">
    <PageHead title="Протоколы реагирования" />
    {d.protocols.map(p => <section key={p.id} className="card pr-card">
      <div className="row">
        <Level l={p.level} />
        <h3 style={{ margin: 0 }}>{p.title}</h3>
      </div>
      <div className="ax-grid">
        <div className="ax-sec">
          <h4>Алгоритм</h4>
          <ol>{p.algorithm.map((s, i) => <li key={i}>{s}</li>)}</ol>
        </div>
        <div className="ax-sec">
          <h4>Необходимые действия</h4>
          <ul>{p.actions.map((s, i) => <li key={i}>{s}</li>)}</ul>
          <h4>Ответственный</h4>
          <p className="small">{p.responsible}</p>
          <h4>Условия эскалации</h4>
          <p className="small">{p.escalation}</p>
          {p.patient_side && <>
            <h4>Что видит пациент</h4>
            <p className="small">{p.patient_side}</p>
  </>}
        </div>
      </div>
      {p.emergency && p.emergency.show && <div className="ax-em">
        <b className="small">При непосредственной угрозе:</b>
        {p.emergency.numbers.map(n => <a key={n.tel} href={'tel:' + n.tel}><button className="sec"><Icon name="phone" size={16} />{n.tel} — {n.label}</button></a>)}
      </div>}
    </section>)}
  </div>
}

export function DutyRouting() {
  const [dr, err, reload] = useLoad(() => get('/api/duty/routing'), []);
  const [staff, err2] = useLoad(() => get('/api/duty/staff'), []);

  const [form, setForm] = useState({});

  const fv = (id, k) => (form[id] || {})[k] || '';
  const setFv = (id, k, v) => setForm({ ...form, [id]: { ...(form[id] || {}), [k]: v } });

  if (err || err2) return <div className="wrap"><Err e={err || err2} /></div>;
  if (!dr || !staff) return <div className="wrap"><Loading rows={3} /></div>;

  return <div className="wrap">
    <PageHead title="Маршрутизация и эскалация" sub="Назначение ответственного, передача специалисту, контроль срока и эскалация" />
    {dr.levels.map(L => <section key={L.id} className="rt-level">
      <div className="row">
        <Level l={L.id} />
        <h2 style={{ margin: 0 }}>{L.label}</h2>
        <span className="pill pill-gray">{L.items.length}</span>
      </div>
      {L.items.length === 0 ? <p className="small mute">Открытых сигналов нет</p> : L.items.map(a => <div key={a.id} className="card rt-card">
        <div className="row">
          <b>{a.patient}</b>
          <span className="grow">{a.title}</span>
          <Pill tone={a.accepted ? 'green' : 'amber'}>{a.status_label}</Pill>
          <a className="link" href={'#/alerts/' + a.id}>Открыть сигнал</a>
        </div>
        <div className="rt-grid">
          <div className="rt-sec">
            <h5>Ответственный</h5>
            <p className="small">{a.responsible.name} <span className="xs mute">({a.responsible.how})</span></p>
            <div className="row">
              <select aria-label="Назначить ответственного" value={fv(a.id, 'assign')} onChange={e => setFv(a.id, 'assign', e.target.value)}>
                <option value="">— выберите сотрудника —</option>
                {staff.map(s => <option key={s.id} value={s.id}>{s.name} — {s.role_label}</option>)}
              </select>
              <Busy cls="sec" disabled={!fv(a.id, 'assign')} onClick={async () => { await post('/api/duty/alerts/' + a.id + '/assign', { user_id: Number(fv(a.id, 'assign')) }); reload(); toast('Ответственный назначен') }}>Назначить</Busy>
            </div>
          </div>
          <div className="rt-sec">
            <h5>Передача психиатру или другой службе</h5>
            {a.handover.to ? <p className="small">Передан: {a.handover.to} · {fmt(a.handover.at)}</p> : <div className="row">
              <input aria-label="Кому передан" placeholder="Например: психиатр" value={fv(a.id, 'handed')} onChange={e => setFv(a.id, 'handed', e.target.value)} />
              <Busy cls="sec" disabled={!fv(a.id, 'handed')} onClick={async () => { await post('/api/alerts/' + a.id + '/status', { status: 'handed_over_awaiting_confirmation', handed_to: fv(a.id, 'handed') }); reload(); toast('Случай передан, ждёт подтверждения') }}>Передать</Busy>
            </div>}
            {a.handover.to && (a.handover.confirmed_at ? <p className="small"><Icon name="checkCircle" size={16} /> Получение подтверждено: {a.handover.confirmed_by} · {fmt(a.handover.confirmed_at)}</p> : <div className="row"><input aria-label="Кто подтвердил получение" placeholder="Кто подтвердил получение" value={fv(a.id, 'by')} onChange={e => setFv(a.id, 'by', e.target.value)} /><Busy cls="sec" disabled={fv(a.id, 'by').length < 2} onClick={async () => { await post('/api/duty/alerts/' + a.id + '/handover-confirm', { by: fv(a.id, 'by') }); reload(); toast('Получение подтверждено') }}>Подтверждено</Busy></div>)
}
          </div>
          <div className="rt-sec">
            <h5>Контроль срока</h5>
            {a.sla.minutes == null ? <p className="small mute">Срок подтверждения для этого уровня не задан</p> : a.accepted ? <p className="small">{a.sla.met ? 'Подтверждён в срок' : 'Подтверждён с опозданием'} (срок {a.sla.minutes} мин)</p> : <p className={'small' + (a.sla.overdue ? ' rt-over' : '')}>{a.sla.overdue ? 'Нет ответа: срок ' + a.sla.minutes + ' мин прошёл' : 'Осталось ' + a.sla.minutes_left + ' мин из ' + a.sla.minutes}</p>}
            <p className="xs mute rt-chain">Цепочка: {a.chain.length ? a.chain.map(c => c.after_minutes + ' мин → ' + c.to_label).join(', ') : 'не предусмотрена'}</p>
          </div>
          <div className="rt-sec">
            <h5>Эскалация</h5>
            {a.escalations.length ? <ul className="small">{a.escalations.map((e, i) => <li key={i}>{fmt(e.at)} → {e.to_label}{e.manual ? ' (вручную)' : ''}{e.note ? ': ' + e.note : ''}</li>)}</ul> : <p className="small mute">Эскалаций не было</p>}
            <div className="row rt-esc">
              <Busy cls="sec" onClick={async () => { await post('/api/duty/alerts/' + a.id + '/escalate', { to: 'duty_doctor', note: 'ответственный не реагирует' }); reload(); toast('Эскалация дежурному врачу') }}>Дежурному врачу</Busy>
              <Busy cls="sec" onClick={async () => { await post('/api/duty/alerts/' + a.id + '/escalate', { to: 'clinic_admin_on_duty', note: 'ответственный не реагирует' }); reload(); toast('Эскалация администратору смены') }}>Администратору смены</Busy>
            </div>
          </div>
        </div>
        <p className="xs mute">Результат передачи фиксируется при закрытии сигнала: <a className="link" href={'#/alerts/' + a.id}>закрыть с обязательными полями</a></p>
      </div>)}
    </section>)}
  </div>;
}

export function Handover() {
  const [dr, err] = useLoad(() => get('/api/duty/handover/draft'), []);
  const [hs, err2, r2] = useLoad(() => get('/api/duty/handovers'), []);
  const [staff, err3] = useLoad(() => get('/api/duty/staff'), []);

  const [f, setF] = useState({ open_cases_note: '', waiting_note: '', done_actions: '', next_steps: '', next_responsible_id: '' });

  if (err || err2 || err3) return <div className="wrap"><Err e={err || err2 || err3} /></div>;
  if (!dr || !staff || !hs) return <div className="wrap"><Loading rows={3} /></div>;

  return <div className="wrap">
    <PageHead title="Передача смены" sub="В конце смены: незакрытые случаи, ожидающие ответа, сделанное, следующие шаги и кто принимает." />
    <section className="card ho-form">
      <h3>Анкета передачи смены</h3>
      <div className="ho-sec">
        <h5>Незакрытые критические и срочные случаи</h5>
        {dr.open_cases.length ? <ul className="ho-list">{dr.open_cases.map(c => <li key={c.id}><Level l={c.level} /> {c.patient}: {c.title} <span className="xs mute">{c.status_label}</span></li>)}</ul> : <p className="small mute">Нет</p>}
        <textarea aria-label="Комментарий к незакрытым случаям" placeholder="Комментарий" value={f.open_cases_note} onChange={e => setF({ ...f, open_cases_note: e.target.value })} />
      </div>
      <div className="ho-sec">
        <h5>Ожидается ответ специалиста</h5>
        {dr.waiting.length ? <ul className="ho-list">{dr.waiting.map((c, i) => <li key={i}>{c.patient}: {c.title}</li>)}</ul> : <p className="small mute">Нет</p>}
        <textarea aria-label="Комментарий к ожидающим" placeholder="Комментарий" value={f.waiting_note} onChange={e => setF({ ...f, waiting_note: e.target.value })} />
      </div>
      <div className="ho-sec">
        <h5>Уже выполненные действия</h5>
        {dr.done.length ? <ul className="ho-list">{dr.done.map((c, i) => <li key={i}>{c}</li>)}</ul> : <p className="small mute">По журналу за 12 часов действий нет</p>}
        <textarea aria-label="Что ещё сделано" placeholder="Что ещё сделано" value={f.done_actions} onChange={e => setF({ ...f, done_actions: e.target.value })} />
      </div>
      <div className="ho-sec">
        <h5>Следующие необходимые шаги</h5>
        <textarea aria-label="Следующие шаги" value={f.next_steps} onChange={e => setF({ ...f, next_steps: e.target.value })} />
      </div>
      <div className="ho-sec">
        <h5>Ответственный за дальнейшее наблюдение</h5>
        <select aria-label="Кто принимает смену" value={f.next_responsible_id} onChange={e => setF({ ...f, next_responsible_id: e.target.value })}>
          <option value="">— выберите —</option>
          {staff.map(s => <option key={s.id} value={s.id}>{s.name} — {s.role_label}</option>)}
        </select>
      </div>
      <Busy disabled={f.next_steps.trim().length < 3 || !f.next_responsible_id} onClick={async () => { await post('/api/duty/handover', { ...f, next_responsible_id: Number(f.next_responsible_id) }); setF({ open_cases_note: '', waiting_note: '', done_actions: '', next_steps: '', next_responsible_id: '' }); r2(); toast('Смена передана — ждёт подтверждения принимающего') }}>Передать смену</Busy>
    </section>
    <section className="card">
      <h3>Журнал передач</h3>
      {hs.length === 0 ? <Empty icon="clipboard" title="Передач пока нет" /> : hs.map(h => <div key={h.id} className="ho-item">
        <div className="row">
          <b>{fmt(h.created_at)}</b>
          <span>{h.author} → {h.next_responsible}</span>
          <span className="grow" />
          {h.confirmed_at ? <Pill tone="green" icon="checkCircle">Подтверждено: {h.confirmed_by}, {fmt(h.confirmed_at)}</Pill> : <Busy cls="sec" onClick={async () => { await post('/api/duty/handover/' + h.id + '/confirm', {}); r2(); toast('Приём смены подтверждён') }}>Подтвердить приём смены</Busy>}
        </div>
        <p className="small"><b>Следующие шаги:</b> {h.data.next_steps}</p>
        {h.data.open_cases_note && <p className="small">Незакрытые случаи: {h.data.open_cases_note}</p>}
        {h.data.done_actions && <p className="small">Сделано: {h.data.done_actions}</p>}
      </div>)}
    </section>
  </div>;
}
