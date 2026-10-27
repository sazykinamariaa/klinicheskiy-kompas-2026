import './duty.css'
import React, { useState } from 'react'
import { get, post, put, api, download } from './api.js'
import { useLoad, Err, Level, fmt, Busy, Icon, Loading, PageLoading, Empty, Pill, PageHead, toast } from './common.jsx'
import { SlaTimer } from './SlaTimer.jsx'
import Why from './Why.jsx'
import { PsyBasis, PsyNotes } from './PsyNotes.jsx'
import { AlertContext } from './DutySections.jsx'

const EV = { created: 'Сигнал создан', notified: 'Уведомление отправлено', accepted: 'Принят врачом', escalated: 'Эскалация', contact_attempt: 'Попытка связи', status_changed: 'Статус изменён', closed: 'Закрыт' }
const STATUS = { new: 'Новый', accepted: 'Принят', contact_established_assessed: 'Контакт установлен, оценка проведена', handed_over_awaiting_confirmation: 'Передан, ждём подтверждения', emergency_help_arranged: 'Экстренная помощь организована', closed_with_documented_result: 'Закрыт с задокументированным результатом' }
const STONE = { new: 'amber', accepted: 'brand', contact_established_assessed: 'brand', handed_over_awaiting_confirmation: 'violet', emergency_help_arranged: 'violet', closed_with_documented_result: 'green' }
const REASON = { assessment_done_plan_agreed: 'Оценка проведена, план согласован', handed_to_other_specialist_confirmed: 'Передан другому специалисту, приём подтверждён', emergency_service_or_hospital_accepted: 'Экстренная служба или стационар приняли пациента', technical_or_duplicate: 'Техническое или дубль', clinical_basis_not_confirmed_after_assessment: 'После оценки клиническое основание не подтвердилось' }
const CH = { push: 'push', sms: 'SMS', in_app: 'в приложении' }
export const StatusPill = ({ s }) => <Pill tone={STONE[s] || 'gray'}>{STATUS[s] || s}</Pill>

export function AlertList() {
  const [open, setOpen] = useState(true)
  const [rows, err, reload] = useLoad(() => get('/api/alerts?open_only=' + open), [open])
  const nRed = rows ? rows.filter(a => a.level === 'red').length : 0
  return <div className="wrap">
    <PageHead title="Алерты" sub={rows ? <>{open ? 'Открытых' : 'Всего'}: <b>{rows.length}</b>{nRed ? <> · критических: <b style={{ color: 'var(--red)' }}>{nRed}</b></> : null}</> : 'Сигналы о состоянии пациентов'}>
      <div className="seg" role="group" aria-label="Показать"><button className={open ? 'on' : ''} aria-pressed={open} onClick={() => setOpen(true)}>Открытые</button><button className={open ? '' : 'on'} aria-pressed={!open} onClick={() => setOpen(false)}>Все</button></div>
      <button className="sec" onClick={reload}><Icon name="refresh" size={18} />Обновить</button>
    </PageHead>
    <Err e={err} />
    <div className="card flush al-list">
      {!rows && !err && <div style={{ padding: 20 }}><Loading rows={3} card={false} /></div>}
      {rows && rows.map(a => <a key={a.id} href={'#/alerts/' + a.id} className={'al-item ' + a.level}>
        <Level l={a.level} />
        <div className="al-main"><div className="al-title">{a.title}</div>
          <div className="al-meta"><span className="row tight"><Icon name="user" size={14} />Пациент {a.patient}</span><span className="row tight"><Icon name="clock" size={14} />{fmt(a.created_at)}</span>{a.after_hours && <span>вне рабочих часов</span>}</div></div>
        <div className="al-side"><StatusPill s={a.status} /><SlaTimer due={a.sla_due_at} level={a.level} compact /><Icon name="right" className="faint" /></div></a>)}
      {rows && !rows.length && <Empty icon="checkCircle" title={open ? 'Открытых алертов нет' : 'Алертов нет'} />}
    </div></div>
}

export function AlertView({ id }) {
  const [a, err, reload] = useLoad(() => get('/api/alerts/' + id), [id])
  const [ct, setCt] = useState({ result: 'reached', method: 'телефон', note: '' }), [st, setSt] = useState({ status: '', handed_to: '' })
  const [cl, setCl] = useState({ close_reason: 'assessment_done_plan_agreed', data: { safety_assessment: {} } }), [e2, setE2] = useState(null), [done, setDone] = useState(false)
  if (err) return <div className="wrap"><Err e={err} /><a href="#/alerts">К списку алертов</a></div>
  if (!a) return <PageLoading />
  const L = a.lifecycle, closed = !!a.closed_at, accepted = !!a.accepted_at
  const setD = (k, v) => setCl({ ...cl, data: { ...cl.data, [k]: v } })
  const setSA = (k, v) => setCl({ ...cl, data: { ...cl.data, safety_assessment: { ...cl.data.safety_assessment, [k]: v } } })
  const lab = Object.fromEntries(L.close_fields.map(f => [f.key, f.label]))
  const SA = [['thoughts', 'Мысли'], ['intent', 'Намерение'], ['plan', 'План'], ['behavior', 'Поведение'], ['can_stay_safe', 'Может оставаться в безопасности']]
  const stepIdx = closed ? 3 : (a.status !== 'new' && a.status !== 'accepted') ? 2 : accepted || a.status === 'accepted' ? 1 : 0
  const STEPS = ['Создан', 'Принят', 'Контакт и решение', 'Закрыт']
  return <div className="wrap">
    <nav className="crumbs" aria-label="Навигация"><a href="#/alerts"><Icon name="left" size={16} />Алерты</a><span aria-hidden="true">/</span><span>Пациент {a.patient}</span></nav>
    <div className={'card alert-head lvl-' + a.level} role="alert">
      <div className="ah-top">
        <span className={'ah-ico ' + a.level}><Icon name={a.level === 'red' ? 'alert' : 'bell'} size={24} /></span>
        <div className="grow" style={{ minWidth: 0 }}><Level l={a.level} /><h1>{a.title}</h1>
          <div className="small mute">Пациент <b>{a.patient}</b> · создан {fmt(a.created_at)} · статус: <b>{STATUS[a.status] || a.status}</b>{a.after_hours ? ' · вне рабочих часов' : ''}</div>{a.sla_due_at && <div style={{ marginTop: 8 }}><SlaTimer due={a.sla_due_at} level={a.level} /></div>}</div>
        {!closed && !accepted && <div className="ah-cta"><Busy onClick={async () => { await post(`/api/alerts/${id}/accept`); reload(); toast('Алерт принят') }}><Icon name="check" size={18} />Принять алерт</Busy></div>}
      </div>
      <div className="steps" aria-label="Этапы">{STEPS.map((s, i) => <React.Fragment key={s}>{i > 0 && <span className={'step-line' + (i <= stepIdx ? ' done' : '')} />}
        <span className={'step' + (i <= stepIdx ? ' done' : '') + (i === stepIdx + 1 ? ' cur' : '')}><span className="dot">{i <= stepIdx ? <Icon name="check" size={14} stroke={2.6} /> : i + 1}</span>{s}</span></React.Fragment>)}</div>
      {a.system_note && <p className="small mute" style={{ margin: '14px 0 0' }}><Icon name="info" size={15} /> {a.system_note}</p>}
    </div>
    <AlertContext id={id} key={a.status + (a.accepted_at || '')} />
    <div className="split">
      <div>
        {!closed && <>
          <div className="card"><div className="card-head"><span className="ico-bubble"><Icon name="phone" size={18} /></span><h3>Попытка связи</h3></div>
            <div className="row"><select value={ct.result} onChange={e => setCt({ ...ct, result: e.target.value })} style={{ flex: '1 1 200px', width: 'auto' }} aria-label="Результат"><option value="reached">Дозвонились</option><option value="unreachable">Не удалось связаться</option></select>
              <input style={{ flex: '1 1 160px', width: 'auto' }} value={ct.method} onChange={e => setCt({ ...ct, method: e.target.value })} aria-label="Способ" /><Busy onClick={async () => { await post(`/api/alerts/${id}/contact`, ct); reload(); toast('Попытка связи записана') }}>Записать</Busy></div>
            {a.level === 'red' && <p className="xs mute" style={{ margin: '10px 0 0' }}>«Не удалось связаться» красный алерт не закрывает: он остаётся нерешённым и идёт по цепочке эскалации.</p>}</div>
          <div className="card"><div className="card-head"><span className="ico-bubble"><Icon name="activity" size={18} /></span><h3>Сменить статус</h3></div>
            <div className="row"><select value={st.status} onChange={e => setSt({ ...st, status: e.target.value })} style={{ flex: '1 1 260px', width: 'auto' }} aria-label="Статус"><option value="">Выберите</option>{L.statuses.filter(s => s !== 'closed_with_documented_result' && s !== 'new').map(s => <option key={s} value={s}>{STATUS[s]}</option>)}</select>
              {st.status === 'handed_over_awaiting_confirmation' && <input style={{ flex: '1 1 200px', width: 'auto' }} placeholder="Кому передан" value={st.handed_to} onChange={e => setSt({ ...st, handed_to: e.target.value })} />}
              <Busy disabled={!st.status} onClick={async () => { await post(`/api/alerts/${id}/status`, st); reload(); toast('Статус изменён') }}>Применить</Busy></div></div>
          <details className="card close-box"><summary>Закрыть алерт</summary>
            <label>Причина закрытия</label><select value={cl.close_reason} onChange={e => setCl({ ...cl, close_reason: e.target.value })}>{L.close_reasons.map(r => <option key={r} value={r}>{REASON[r] || r}</option>)}</select>
            {!L.relaxed_reasons.includes(cl.close_reason) && <>
              <label>{lab.contact_method}</label><input onChange={e => setD('contact_method', e.target.value)} />
              <fieldset><legend>{lab.safety_assessment}</legend><div className="grid2" style={{ gap: '0 14px' }}>{SA.map(([k, l]) => <div key={k}><label>{l}</label><input onChange={e => setSA(k, e.target.value)} /></div>)}</div></fieldset>
              <div className="grid2" style={{ gap: '0 14px' }}><div><label>{lab.decision}</label><input onChange={e => setD('decision', e.target.value)} /></div><div><label>{lab.handed_to}</label><input onChange={e => setD('handed_to', e.target.value)} /></div></div>
              <label>{lab.next_contact_due}</label><input onChange={e => setD('next_contact_due', e.target.value)} /></>}
            <label>{lab.comment}</label><textarea onChange={e => setD('comment', e.target.value)} /><p className="xs mute">Кто и когда оценивал, и исходное основание сигнала заполняются автоматически.</p>
            <Err e={e2} /><p style={{ margin: 0 }}><button onClick={async () => { setE2(null); try { await post(`/api/alerts/${id}/close`, cl); setDone(true); reload(); toast('Алерт закрыт') } catch (x) { setE2(x.message) } }}><Icon name="checkCircle" size={18} />Закрыть алерт</button></p></details></>}
        {closed && <div className="card"><div className="card-head"><span className="ico-bubble"><Icon name="checkCircle" size={18} /></span><h2>Закрыт</h2><span style={{ marginLeft: 'auto' }}><Pill tone="green">{fmt(a.closed_at)}</Pill></span></div>
          {a.close_data ? <pre>{JSON.stringify(a.close_data, null, 1)}</pre> : <p className="mute small">Результат записан.</p>}</div>}
      </div>
      <div>
        <div className="card"><div className="card-head"><span className="ico-bubble"><Icon name="list" size={18} /></span><h3>Подсказка (решение за врачом)</h3></div>
          <ul className="checklist">{L.checklist_hint.map(h => <li key={h}>{h}</li>)}</ul>
          <Why ruleId={a.rule_id} title={a.title} facts={a.facts} basis={a.basis} raw={{ basis: a.basis, facts: a.facts }} /></div>
        <div className="card"><div className="card-head"><span className="ico-bubble"><Icon name="clock" size={18} /></span><h3>Журнал</h3><span className="pill pill-gray" style={{ marginLeft: 'auto' }}>{a.events.length}</span></div>
          <ol className="tl">{a.events.map((ev, i) => <li key={i} className={'k-' + ev.kind}><div className="tl-what">{EV[ev.kind] || ev.kind}
            {ev.kind === 'notified' && ev.data ? <span className="mute" style={{ fontWeight: 500 }}> · {ev.data.user}{ev.data.channel ? ' · ' + (CH[ev.data.channel] || ev.data.channel) : ''}</span> : null}
            {ev.kind === 'escalated' && ev.data && ev.data.recipients ? <span className="mute" style={{ fontWeight: 500 }}> → {ev.data.recipients.join(', ')}</span> : null}
            {ev.kind === 'contact_attempt' && ev.data && ev.data.note ? <span className="mute" style={{ fontWeight: 500 }}>: {ev.data.note}</span> : null}</div>
            <div className="tl-time">{fmt(ev.ts)}</div></li>)}</ol>
          <details><summary>Технические данные журнала</summary><pre>{JSON.stringify(a.events, null, 1)}</pre></details></div>
      </div>
    </div></div>
}

const TIMING = { urgent: 'срочно', soon: 'в ближайшие дни' }
const TIER = t => t === 'mandatory' ? <span className="tier tier-must">Обязательно</span> : t === 'desirable' ? <span className="tier tier-want">Желательно</span> : t ? <Pill tone="gray">{t}</Pill> : null

export function Referrals() {
  const [rows, err, reload] = useLoad(() => get('/api/psychiatrist/referrals'), [])
  const [sel, setSel] = useState(null), [d, setD] = useState(null)
  const open = async r => { setSel(r); setD(await get('/api/psychiatrist/referrals/' + r.id)) }
  const S = d && d.summary
  return <div className="wrap"><PageHead title="Направления" sub="Пациенты, направленные к психиатру после подтверждения лечащего врача" />
    <Err e={err} />
    <div className={'md' + (sel ? ' has-sel' : '')}>
      <div className="card flush al-list">
        {!rows && !err && <div style={{ padding: 20 }}><Loading rows={3} card={false} /></div>}
        {rows && rows.map(r => <div key={r.id} role="button" tabIndex={0} className={'al-item clickable' + (sel && sel.id === r.id ? ' sel' : '')} onClick={() => open(r)} onKeyDown={e => e.key === 'Enter' && open(r)}>
          <div className="al-main"><div className="row tight">{TIER(r.kind)}<span className="al-title">Пациент {r.patient}</span>{r.tier && <Pill tone={r.tier === 'urgent' ? 'amber' : 'gray'} icon="clock">{TIMING[r.tier] || r.tier}</Pill>}</div>
            <div className="al-meta"><span>{r.rule_id}</span>{r.due_at && <span className="row tight"><Icon name="clock" size={14} />до {fmt(r.due_at)}</span>}<span>подтверждено врачом {fmt(r.confirmed_at)}</span></div></div>
          <div className="al-side"><Pill tone={r.status === 'awaiting_acceptance' ? 'amber' : 'green'}>{r.status === 'awaiting_acceptance' ? 'ждёт принятия' : 'принято'}</Pill><Icon name="right" className="faint" /></div></div>)}
        {rows && !rows.length && <Empty icon="inbox" title="Направлений нет">Здесь появятся пациенты после того, как лечащий врач подтвердит направление</Empty>}
      </div>
      {sel && <div className="card">{!S && <Loading rows={4} card={false} />}
        {S && <><div className="card-head" style={{ flexWrap: 'wrap' }}><span className="ico-bubble"><Icon name="file" size={18} /></span><h2>Сводка · {d.patient}</h2></div>
          <div className="row" style={{ marginBottom: 8 }}><Busy onClick={async () => { await post(`/api/psychiatrist/referrals/${sel.id}/accept`); reload(); open(sel); toast('Получение подтверждено') }} disabled={d.status !== 'awaiting_acceptance'}><Icon name="check" size={18} />Подтвердить получение</Busy>
            <Busy cls="sec" onClick={() => download(`/api/psychiatrist/referrals/${sel.id}/summary.pdf`, 'summary.pdf')}><Icon name="download" size={18} />PDF</Busy>
            <Busy cls="sec" onClick={async () => { const j = await get(`/api/psychiatrist/referrals/${sel.id}/summary.fhir`); const b = new Blob([JSON.stringify(j, null, 2)], { type: 'application/json' }); const a = document.createElement('a'); a.href = URL.createObjectURL(b); a.download = 'summary-fhir.json'; a.click() }}>Структурированный экспорт</Busy></div>
          <PsyBasis rid={sel.id} />{(S.readable || []).map(b => <div key={b.title} className="sum-block"><h3>{b.title}</h3>{b.lines.map((l, i) => <p key={i}>{l}</p>)}</div>)}<p className="xs mute">{S.disclaimer}</p><PsyNotes rid={sel.id} /></>}</div>}
    </div></div>
}

export function Sources({ focus }) {
  const [s] = useLoad(() => get('/api/sources'), []), [sc] = useLoad(() => get('/api/scales/registry'), [])
  React.useEffect(() => { if (s && focus) { const el = document.getElementById('src-' + focus); if (el) el.scrollIntoView({ block: 'center' }) } }, [s, focus])
  const T = { confirmed: 'green', verify: 'amber', waiting: 'gray', other: 'gray' }, N = { confirmed: 'подтверждено', verify: 'проверить', waiting: 'ждём данных', other: 'другое' }
  const cnt = k => s ? s.sources.filter(x => x.bucket === k).length : 0
  return <div className="wrap"><PageHead title="Источники" sub="Статусы показываются как есть: что не подтверждено, так и помечено." />
    {s && <div className="row" style={{ marginBottom: 16 }}>{['confirmed', 'verify', 'waiting', 'other'].filter(k => cnt(k)).map(k => <Pill key={k} tone={T[k]}>{N[k]}: {cnt(k)}</Pill>)}</div>}
    <div className="card flush"><div className="table-scroll"><table><thead><tr><th>Источник</th><th>Роль</th><th>Статус</th><th>Шкалы</th></tr></thead><tbody>
      {!s && <tr><td colSpan="4"><Loading rows={3} card={false} /></td></tr>}
      {s && s.sources.map(x => <tr key={x.id} id={'src-' + x.id} className={focus === x.id ? 'src-hl' : ''}><td style={{ minWidth: 240 }}><span className="xs faint" style={{ fontFamily: 'var(--mono)' }}>{x.id}</span><div style={{ fontWeight: 600 }}>{x.title}</div></td><td style={{ minWidth: 220 }}>{x.ui_label && <span className="pill pill-intl" style={{ marginBottom: 4 }}>{x.ui_label}</span>}<div>{x.role}</div><div className="xs mute">{x.note}</div>{x.restriction && <div className="xs" style={{ marginTop: 4, color: 'var(--warn-ink)' }}>{x.restriction}</div>}{x.use && <div className="xs mute">{x.use}</div>}</td>
        <td><Pill tone={T[x.bucket] || 'gray'}>{N[x.bucket] || x.bucket}</Pill><div className="xs mute" style={{ marginTop: 4 }}>{x.status}</div></td><td className="small">{x.scales.join(', ') || '—'}</td></tr>)}</tbody></table></div></div>
    <div className="section-title"><h2>Шкалы и условия использования</h2>{sc && <span className="count">{sc.length}</span>}</div>
    <div className="card flush"><div className="table-scroll"><table><thead><tr><th>Шкала</th><th>Включена</th><th>Русская версия</th><th>Лицензия</th></tr></thead><tbody>
      {!sc && <tr><td colSpan="4"><Loading rows={3} card={false} /></td></tr>}
      {sc && sc.map(x => <tr key={x.id}><td style={{ fontWeight: 600 }}>{x.title}</td><td>{x.enabled ? <Pill tone="green" icon="check">да</Pill> : <Pill tone="gray">нет</Pill>}</td><td className="small" style={{ minWidth: 220 }}>{x.version_ru || '—'}</td><td className="small" style={{ minWidth: 220 }}>{x.restriction || x.license_status || '—'}</td></tr>)}</tbody></table></div></div></div>
}

export function Admin() {
  const [t, setT] = useState('summary')
  const [sum] = useLoad(() => get('/api/admin/config/summary'), []), [w] = useLoad(() => get('/api/admin/config/waiting'), [])
  const [rules] = useLoad(() => get('/api/admin/config/rules'), []), [q, , rq] = useLoad(() => get('/api/admin/queue'), [t === 'queue'])
  const [au] = useLoad(() => get('/api/admin/audit?limit=100'), [t === 'audit']), [us, , ru] = useLoad(() => get('/api/admin/users'), [])
  const [nu, setNu] = useState({ login: '', password: '', role: 'doctor', name: '' }), [e, setE] = useState(null)
  const tabs = [['summary', 'Конфигурация'], ['waiting', 'Ждём данных', w && w.count], ['rules', 'Правила', rules && rules.length], ['queue', 'Очередь'], ['users', 'Пользователи', us && us.length], ['audit', 'Журнал']]
  return <div className="wrap"><PageHead title="Администрирование" sub="Конфигурация, правила, очередь уведомлений, пользователи и журнал аудита" />
    <div className="banner b-info banner-ico"><Icon name="lock" size={20} /><span>Клинические данные пациентов администратору недоступны.</span></div>
    <div className="tabs" role="tablist">{tabs.map(([k, l, n]) => <button key={k} role="tab" aria-selected={t === k} className={t === k ? 'on' : ''} onClick={() => setT(k)}>{l}{n ? <span className="tab-count">{n}</span> : null}</button>)}</div>
    {t === 'summary' && !sum && <Loading rows={4} />}
    {t === 'summary' && sum && <>
      <div className="stats" style={{ gridTemplateColumns: 'repeat(3, minmax(0, 1fr))' }}>
        <div className="stat"><span className="s-label">Правил в конфигурации</span><span className="s-val">{sum.rules_total}</span></div>
        <div className="stat"><span className="s-label">Исполняются</span><span className="s-val" style={{ color: 'var(--green-ink)' }}>{sum.rules_executable}</span></div>
        <div className="stat"><span className="s-label">Не исполняются</span><span className="s-val">{sum.rules_not_executable.length}</span></div></div>
      {sum.rules_not_executable.map(r => <p key={r.id} className="banner b-warn"><b>{r.id}</b>: {r.why}</p>)}
      <div className="card"><div className="card-head"><span className="ico-bubble"><Icon name="list" size={18} /></span><h3>Статусы значений</h3></div>
        <div className="row">{Object.entries(sum.statuses.total || {}).map(([k, v]) => <Pill key={k} tone={k === 'confirmed' || k === 'approved_by_physician' ? 'green' : k === 'waiting' ? 'gray' : k === 'verify' ? 'amber' : 'brand'}>{k}: {v}</Pill>)}</div>
        <details style={{ marginTop: 10 }}><summary>По файлам</summary><pre>{JSON.stringify(sum.statuses.per_file, null, 1)}</pre></details>
        <div style={{ marginTop: 12 }}><Busy cls="sec" onClick={async () => { await post('/api/admin/config/reload'); toast('Конфигурация перечитана') }}><Icon name="refresh" size={18} />Перечитать конфигурацию</Busy></div></div></>}
    {t === 'waiting' && w && <div className="card flush"><div style={{ padding: '14px 18px' }}>Всего позиций: <strong>{w.count}</strong></div><div className="table-scroll"><table><thead><tr><th>Файл</th><th>Статус</th><th>Что ждём</th></tr></thead><tbody>{w.items.map((i, k) => <tr key={k}><td className="small" style={{ fontFamily: 'var(--mono)' }}>{i.file}</td><td><Pill tone={i.status === 'waiting' ? 'gray' : 'amber'}>{i.status}</Pill></td><td className="small">{i.what}</td></tr>)}</tbody></table></div></div>}
    {t === 'rules' && rules && <div className="card flush"><div className="table-scroll"><table><thead><tr><th>Правило</th><th>Тип</th><th>Исполняется</th><th>Условие</th></tr></thead><tbody>{rules.map(r => <tr key={r.id}><td style={{ minWidth: 220 }}><b style={{ fontFamily: 'var(--mono)', fontSize: '.85rem' }}>{r.id}</b><div className="small">{r.title}</div></td><td className="small">{r.kind}</td><td>{r.executable ? <Pill tone="green" icon="check">да</Pill> : <><Pill tone="amber">нет</Pill><div className="xs mute">{r.why_not}</div></>}</td><td className="small"><code>{r.expr}</code>{r.overridden ? ' (привязка)' : ''}</td></tr>)}</tbody></table></div></div>}
    {t === 'queue' && q && <div className="card"><div className="row" style={{ marginBottom: 12 }}>{Object.entries(q.by_status || {}).map(([k, v]) => <Pill key={k} tone={k === 'sent' ? 'green' : 'amber'}>{k}: {v}</Pill>)}</div><pre>{JSON.stringify(q, null, 1)}</pre><div className="row" style={{ marginTop: 12 }}><button className="sec" onClick={rq}><Icon name="refresh" size={18} />Обновить</button><Busy onClick={async () => { await post('/api/admin/queue/run'); rq() }}>Обработать сейчас</Busy></div></div>}
    {t === 'users' && <><div className="card flush"><div className="table-scroll"><table><thead><tr><th>Логин</th><th>Роль</th><th>Имя</th><th>Состояние</th><th /></tr></thead><tbody>{(us || []).map(u => <tr key={u.id}><td style={{ fontFamily: 'var(--mono)', fontSize: '.875rem' }}>{u.login}</td><td>{u.role}{u.duty_role ? ' · ' + u.duty_role : ''}</td><td>{u.name}</td><td>{u.active ? <Pill tone="green">активен</Pill> : <Pill tone="gray">отключён</Pill>}</td>
      <td><Busy cls="sec sm" onClick={async () => { await post(`/api/admin/users/${u.id}/active?active=${!u.active}`); ru() }}>{u.active ? 'Отключить' : 'Включить'}</Busy></td></tr>)}</tbody></table></div></div>
      <div className="card"><div className="card-head"><span className="ico-bubble"><Icon name="plus" size={18} /></span><h3>Новый пользователь</h3></div><div className="grid2" style={{ gap: 12 }}><input placeholder="Логин" value={nu.login} onChange={x => setNu({ ...nu, login: x.target.value })} /><input placeholder="Пароль (от 8)" type="password" value={nu.password} onChange={x => setNu({ ...nu, password: x.target.value })} />
        <input placeholder="Имя" value={nu.name} onChange={x => setNu({ ...nu, name: x.target.value })} /><select value={nu.role} onChange={x => setNu({ ...nu, role: x.target.value })}>{['doctor', 'duty', 'psychiatrist', 'admin'].map(r => <option key={r}>{r}</option>)}</select></div>
        <Err e={e} /><div style={{ marginTop: 14 }}><button onClick={async () => { setE(null); try { await post('/api/admin/users', nu); ru() } catch (x) { setE(x.message) } }}>Создать</button></div></div></>}
    {t === 'audit' && au && <div className="card flush"><div className="table-scroll"><table><thead><tr><th>Время</th><th>Роль</th><th>Действие</th><th>Объект</th></tr></thead><tbody>{au.map(r => <tr key={r.id}><td className="small num">{fmt(r.ts)}</td><td className="small">{r.actor_role}</td><td className="small" style={{ fontFamily: 'var(--mono)' }}>{r.action}</td><td className="small">{r.entity}</td></tr>)}</tbody></table></div></div>}
  </div>
}
