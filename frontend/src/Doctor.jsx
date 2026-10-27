import React, { useState } from 'react'
import { get, post, put, api, download, ORIGIN } from './api.js'
import { useLoad, Err, Level, fmt, Busy, go, Icon, Loading, PageLoading, Empty, Pill, Avatar, PageHead, toast } from './common.jsx'
import Why from './Why.jsx'
import DrugFindings from './DrugFindings.jsx'
import CardSummary from './CardSummary.jsx'
import Templates from './Templates.jsx'
import { DoctorPsyNotes } from './PsyNotes.jsx'
import { StatusPill } from './Staff.jsx'
import { Buckets } from './DoctorSections.jsx'

const TONE = { red: 'red', orange: 'orange', yellow: 'yellow', green: 'green' }
const LEVELS = [['', 'Все пациенты'], ['red', 'Критический'], ['orange', 'Оперативная оценка'], ['yellow', 'Плановая оценка'], ['green', 'Наблюдение']]
const DOT = { red: 'var(--red)', orange: 'var(--orange)', yellow: 'var(--yellow)', green: 'var(--green)' }
const activity = p => p.days_since_activity == null ? 'данных нет' : p.days_since_activity === 0 ? 'сегодня' : p.days_since_activity + ' дн. назад'

const NEW = { code: '', sex: 'ж', birth_date: '' }
export function NewPatient() {
  const [nw, setNw] = useState(NEW), [inv, setInv] = useState(null)
  const create = async () => { setInv(await post('/api/doctor/patients', { ...nw, origin: ORIGIN })); toast('Приглашение создано и сохранено') }
  return <div className="wrap">
    <PageHead title="Новый пациент"><a className="link" href="#/doctor">К списку пациентов</a></PageHead>
    {!inv ? <div className="card"><div className="grid3"><div><label htmlFor="np-c">Код или псевдоним</label><input id="np-c" value={nw.code} onChange={e => setNw({ ...nw, code: e.target.value })} /></div>
      <div><label htmlFor="np-s">Пол</label><select id="np-s" value={nw.sex} onChange={e => setNw({ ...nw, sex: e.target.value })}><option>ж</option><option>м</option></select></div>
      <div><label htmlFor="np-b">Дата рождения</label><input id="np-b" type="date" value={nw.birth_date} onChange={e => setNw({ ...nw, birth_date: e.target.value })} /></div></div>
      <div className="row" style={{ marginTop: 16 }}><Busy onClick={create} disabled={!nw.code.trim() || !nw.birth_date}>Создать приглашение</Busy><button className="sec" onClick={() => go('#/doctor')}>Отмена</button></div></div>
    : <div className="card"><div className="card-head"><span className="ico-bubble"><Icon name="checkCircle" size={18} /></span><h2>Приглашение для {nw.code}</h2></div>
      <div className="row" style={{ alignItems: 'flex-start', gap: 20 }}><div dangerouslySetInnerHTML={{ __html: inv.qr_svg }} style={{ width: 180, maxWidth: '100%' }} />
        <div className="grow"><p>Покажите пациенту QR-код или назовите код:</p><p className="inv-code">{inv.invite_code}</p>
          <p className="small mute">Ссылка: {ORIGIN}{inv.invite_url_path} · действует до {fmt(inv.expires_at)}</p>
          <div className="row"><button onClick={() => go('#/doctor/patient/' + inv.patient_id)}>Открыть карточку</button><button className="sec" onClick={() => { setInv(null); setNw(NEW) }}>Ещё приглашение</button></div></div></div></div>}
  </div>
}

export function DoctorHome() {
  const [q, setQ] = useState(''), [lv, setLv] = useState('')
  const [pats, e1, reload] = useLoad(() => get('/api/doctor/patients?' + new URLSearchParams({ ...(q ? { q } : {}), ...(lv ? { level: lv } : {}) })), [q, lv])
  const [all, , reloadAll] = useLoad(() => get('/api/doctor/patients?'), [])
  const count = k => !all ? '—' : k ? all.filter(p => p.level === k).length : all.length
  const pending = all ? all.reduce((s, p) => s + (p.pending_proposals || 0), 0) : 0
  return <div className="wrap">
    <PageHead title="Мои пациенты" sub={<>Сверху те, кому нужно внимание в первую очередь{all && pending > 0 ? <> · ждут вашего решения: <b>{pending}</b></> : null}</>}>
      <button onClick={() => go('#/doctor/new')}><Icon name="plus" size={18} />Новый пациент</button>
    </PageHead>

    <Buckets />

    <div className="stats" role="group" aria-label="Фильтр по уровню">
      {LEVELS.map(([k, l]) => {
        const val = count(k), on = lv === k
        return <button key={k} className={'stat' + (on ? ' on' : '') + (k === 'red' && val > 0 ? ' red' : '')} aria-pressed={on} onClick={() => setLv(k)}>
          <span className="s-label">{k && <span className="s-dot" style={{ background: DOT[k] }} />}{l}</span>
          <span className="s-val">{val}</span></button>
      })}
    </div>

    <div className="toolbar">
      <div className="field-search"><Icon name="search" size={18} /><input placeholder="Поиск по коду пациента" aria-label="Поиск" value={q} onChange={e => setQ(e.target.value)} /></div>
      <select aria-label="Уровень" value={lv} onChange={e => setLv(e.target.value)}>{LEVELS.map(([k, l]) => <option key={k} value={k}>{k ? l : 'Все уровни'}</option>)}</select>
    </div>
    <Err e={e1} />
    <div className="card flush">
      {!pats && !e1 && <div style={{ padding: 20 }}><Loading rows={4} card={false} /></div>}
      {pats && pats.length > 0 && <>
        <div className="pt-table table-scroll"><table className="queue"><thead><tr><th>Пациент</th><th>Что требует внимания</th><th>Активность</th><th>Ждут решения</th><th aria-label="Открыть" /></tr></thead>
          <tbody>{pats.map(p => <tr key={p.id} className="clk" tabIndex={0} onClick={() => go('#/doctor/patient/' + p.id)} onKeyDown={e => e.key === 'Enter' && go('#/doctor/patient/' + p.id)}>
            <td><div className="pt-cell"><Avatar text={p.code} size={38} tone={TONE[p.level]} /><div><a href={'#/doctor/patient/' + p.id} style={{ textDecoration: 'none', color: 'inherit' }}><b>{p.code}</b></a><small>{p.sex}</small></div></div></td>
            <td style={{ maxWidth: 460 }}><Level l={p.level} /><div className="reason">{p.reason}</div></td>
            <td className="small">{activity(p)}</td>
            <td>{p.pending_proposals ? <span className="dec has"><Icon name="clipboard" size={16} />{p.pending_proposals}</span> : <span className="faint">—</span>}</td>
            <td style={{ width: 44, color: 'var(--faint)' }}><Icon name="right" /></td></tr>)}</tbody></table></div>
        <div className="pt-cards">{pats.map(p => <a className="pt-card" key={p.id} href={'#/doctor/patient/' + p.id}>
          <div className="top-line"><Avatar text={p.code} size={40} tone={TONE[p.level]} /><div className="grow"><b>{p.code}</b> <span className="mute small">{p.sex}</span></div><Level l={p.level} /></div>
          <div className="reason">{p.reason}</div>
          <div className="meta"><span className="row tight"><Icon name="clock" size={14} />{activity(p)}</span><span className="row tight"><Icon name="clipboard" size={14} />ждут решения: {p.pending_proposals || 0}</span></div></a>)}</div></>}
      {pats && !pats.length && <Empty icon="users" title="Пациентов нет">{q || lv ? 'Измените поиск или фильтр' : 'Добавьте пациента кнопкой «Новый пациент»'}</Empty>}
    </div>
  </div>
}

function Scales({ c }) {
  const s = Object.entries(c.dynamics.series)
  const [reg] = useLoad(() => get('/api/scales/registry'), [])
  const ver = k => { const r = reg && reg.find(x => x.id === k); return r && r.version_ru ? r.version_ru.split(',').slice(0, 2).join(',') : null }
  return <div className="card"><div className="card-head"><span className="ico-bubble"><Icon name="list" size={18} /></span><h3>Шкалы</h3><span className="xs mute" style={{ marginLeft: 'auto' }}>последнее заполнение</span></div>
    {s.length === 0 && <p className="mute">Завершённых шкал пока нет.</p>}
    {s.map(([k, v]) => <div key={k} className="scale-row"><div className="sr-top"><span className="sr-name">{v.title}</span><span className="sr-val">{v.latest}</span>{v.max ? <span className="sr-max">/ {v.max}</span> : null}</div>
      <div className="meter" role="img" aria-label={v.title + ': ' + v.latest + (v.max ? ' из ' + v.max : '')}><div style={{ width: Math.min(100, 100 * v.latest / (v.max || 27)) + '%' }} /></div>
      <div className="small mute">{v.latest_label || ''}{v.previous != null ? ' · предыдущее: ' + v.previous : ''}</div>{ver(k) && <div className="xs faint" title="Валидированная русская версия">рус. версия: {ver(k)}</div>}</div>)}
    <p className="xs mute" style={{ margin: '14px 0 0' }}>Баллы и пороги из конфигурации шкал.</p></div>
}

const DRUG = { indicated_pending_doctor: ['Показан, ждёт решения врача', 'info', 'pill'], contraindicated: ['Противопоказан', 'red', 'alert'], interaction_requires_decision: ['Взаимодействие: нужно решение врача', 'orange', 'alert'],
  out_of_indication: ['Вне показаний', 'warn', 'info'], safety_check_incomplete: ['Проверка безопасности не завершена', 'warn', 'info'] }

function Drug({ d }) {
  if (d.state === 'indicated_pending_doctor' && !d.gating.show_positive) return <div className="drug st-warn"><div className="drug-head"><span className="d-ico"><Icon name="shield" size={22} /></span>
    <div className="grow"><div className="xs mute">Терапия</div><h3>Предложение по терапии скрыто</h3></div></div>
    <div className="drug-body"><p>Есть критический сигнал: сначала оценка безопасности пациента. {d.gating.note || ''}</p>{(d.gating.reasons || []).map((r, i) => <p key={i} className="small mute" style={{ margin: 0 }}>{r}</p>)}</div></div>
  const [label, tone, ic] = DRUG[d.state] || [d.state, 'info', 'pill']
  const nClar = d.to_clarify.length + d.incomplete_items.length
  return <div className={'drug st-' + tone}><div className="drug-head"><span className="d-ico"><Icon name={ic} size={22} /></span>
    <div className="grow"><div className="xs mute">Терапия · проверка препарата</div><h3>Препарат: {label}</h3></div></div>
    <div className="drug-body"><DrugFindings d={d} />{d.texts.map((t, i) => <p key={i}>{t}</p>)}
      {nClar > 0 && <details><summary>Что уточнить и каких данных не хватает ({nClar})</summary>
        {d.to_clarify.length > 0 && <><p style={{ margin: '10px 0 4px' }}><strong>Уточнить</strong></p><ul>{d.to_clarify.map((x, i) => <li key={i}>{x.text || x}</li>)}</ul></>}
        {d.incomplete_items.length > 0 && <><p style={{ margin: '10px 0 4px' }}><strong>Не хватает данных</strong></p><ul>{d.incomplete_items.map((x, i) => <li key={i}>{x}</li>)}</ul></>}</details>}
      <details><summary>Подробности проверки</summary><pre>{JSON.stringify({ indication: d.indication, contraindications: d.contraindications, interactions: d.interactions, meds: d.meds, gating: d.gating }, null, 1)}</pre></details></div></div>
}

const KIND = { therapy: ['Терапия', 'pill'], routing: ['Направление к психиатру', 'users'], status: ['Статус', 'activity'] }

function Proposal({ p, onDone }) {
  const [reason, setReason] = useState(''), [mode, setMode] = useState(null), [chg, setChg] = useState('')
  const pl = p.payload
  const tier = p.kind === 'routing' ? pl.kind : null
  const decide = async (decision) => {
    const body = { decision }
    if (decision === 'reject') body.reason = reason
    if (decision === 'modify') { body.changes = { note: chg }; body.reason = reason || undefined }
    await post('/api/doctor/proposals/' + p.id + '/decision', body)
    toast(decision === 'confirm' ? 'Решение сохранено: подтверждено' : decision === 'reject' ? 'Предложение отклонено' : 'Изменение сохранено'); onDone()
  }
  const [kl, ki] = KIND[p.kind] || ['Статус', 'activity']
  const src = pl.basis || p.basis
  return <div className={'prop' + (tier === 'mandatory' ? ' must' : tier === 'desirable' ? ' want' : '')}>
    <div className="prop-top">
      {tier === 'mandatory' && <span className="tier tier-must"><Icon name="alert" size={14} stroke={2.2} />Обязательно</span>}
      {tier === 'desirable' && <span className="tier tier-want">Желательно</span>}
      <Pill tone="gray" icon={ki}>{kl}</Pill>{pl.rule_id && <span className="xs faint">{pl.rule_id}</span>}
      <span className="grow" /><Pill tone="amber" icon="clock">ожидает вашего решения</Pill></div>
    <h3>{pl.title || (pl.drug && pl.drug.trade_name) || p.key}</h3>
    {pl.text && <p>{pl.text}</p>}{pl.note && <p className="mute">{pl.note}</p>}
    {pl.timing_text && <div className="timing"><Icon name="clock" size={18} /><span><b>Срок:</b> {pl.timing_text}{pl.timing_override_text ? ' · ' + pl.timing_override_text : ''}</span></div>}
    {pl.status && <p>Предлагаемый статус: <strong>{pl.status}</strong> {pl.reason || ''}</p>}
    <Why ruleId={pl.rule_id || p.key} title={pl.title || (pl.drug && pl.drug.trade_name)} facts={pl.facts_used} basis={src} raw={{ basis: p.basis, facts: pl.facts_used }} />
    {mode === 'reject' && <><label>Причина отклонения (обязательна)</label><textarea value={reason} onChange={e => setReason(e.target.value)} /></>}
    {mode === 'modify' && <><label>Что изменить</label><textarea value={chg} onChange={e => setChg(e.target.value)} /></>}
    <div className="prop-actions">
      {mode ? <><Busy onClick={() => decide(mode)} cls={mode === 'reject' ? 'danger' : ''} disabled={mode === 'reject' && !reason.trim()}>Подтвердить действие: {mode === 'reject' ? 'отклонить' : 'изменить'}</Busy><button className="sec" onClick={() => setMode(null)}>Назад</button></>
        : <><Busy onClick={() => decide('confirm')}><Icon name="check" size={18} />Подтвердить</Busy><button className="sec" onClick={() => setMode('modify')}><Icon name="edit" size={17} />Изменить</button><button className="sec" onClick={() => setMode('reject')}><Icon name="x" size={17} />Отклонить</button></>}</div></div>
}

const DAY = 86400000
export const COL = ['#1B6A70', '#6A4C9C', '#5D6B70'], DASH = ['', '7 5', '2 4'], DASHN = ['solid', 'dashed', 'dotted']
export function TimeChart({ series, events, range }) {
  const W = 760, H = 280, L = 40, R = 22, T = 26, B = 36
  const all = series.flatMap(([, v]) => v.points.map(p => +new Date(p.at)))
  const ev = events.map(e => ({ ...e, t: +new Date(e.at) }))
  const end = Math.max(...all, ...ev.map(e => e.t), Date.now() - 0)
  const start0 = Math.min(...all, ...ev.map(e => e.t))
  const start = range ? Math.max(start0, end - range * 7 * DAY) : start0
  const span = Math.max(end - start, DAY)
  const mx = Math.max(27, ...series.flatMap(([, v]) => v.points.map(p => p.total)))
  const X = t => L + (t - start) / span * (W - L - R), Y = v => H - B - v / mx * (H - B - T)
  const ticks = [0, 5, 10, 15, 20, 25].filter(v => v <= mx)
  const day = t => new Date(t).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })
  const nX = Math.min(5, Math.max(2, Math.round(span / (7 * DAY)) + 1)), xt = Array.from({ length: nX }, (_, i) => start + span * i / (nX - 1))
  // подпись точки ниже, если в тот же день у другой шкалы значение выше или такое же (чтобы подписи не налезали)
  const pts = series.map(([, v]) => v.points.filter(p => +new Date(p.at) >= start).map(p => ({ t: +new Date(p.at), v: p.total })))
  const below = (si, p) => pts.some((o, oi) => oi !== si && o.some(q => Math.abs(q.t - p.t) < DAY && (q.v > p.v || (q.v === p.v && oi < si))))
  return <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', display: 'block' }} role="img" aria-label={'График: ' + series.map(([, v]) => v.title + ' ' + v.points.map(p => p.total).join(', ')).join('; ')}>
    <defs><linearGradient id="kk-area" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={COL[0]} stopOpacity=".16" /><stop offset="100%" stopColor={COL[0]} stopOpacity="0" /></linearGradient></defs>
    {ticks.map(v => <g key={v}><line x1={L} x2={W - R} y1={Y(v)} y2={Y(v)} stroke="#E8EDEF" strokeDasharray={v ? '3 4' : ''} /><text x={L - 10} y={Y(v) + 4} fontSize="11" textAnchor="end" fill="#5D6B70">{v}</text></g>)}
    <line x1={L} x2={W - R} y1={H - B} y2={H - B} stroke="#CFD8DB" />
    {xt.map((t, i) => <text key={i} x={X(t)} y={H - 12} fontSize="11" fill="#5D6B70" textAnchor={i === 0 ? 'start' : i === xt.length - 1 ? 'end' : 'middle'}>{day(t)}</text>)}
    {ev.filter(e => e.t >= start).map((e, i) => e.kind === 'therapy'
      ? <g key={i}><line x1={X(e.t)} x2={X(e.t)} y1={T} y2={H - B} stroke="#1B6A70" strokeOpacity=".5" strokeWidth="2" strokeDasharray="4 3" /><text x={X(e.t) + 6} y={T + 10} fontSize="11" fill="#1B6A70">{e.label}</text></g>
      : <g key={i}><title>{e.label}</title><path d={`M${X(e.t)} ${H - B - 13} l6 10.5 l-12 0 z`} fill={e.level === 'red' ? '#9B3B36' : e.level === 'orange' ? '#B4630A' : '#C9A227'} stroke="#fff" strokeWidth="1.2" strokeLinejoin="round" /></g>)}
    {series.map(([k, v], si) => {
      const P = pts[si], line = P.map(p => X(p.t) + ',' + Y(p.v)).join(' ')
      return <g key={k}>
        {si === 0 && P.length > 1 && <polygon fill="url(#kk-area)" points={`${X(P[0].t)},${H - B} ${line} ${X(P[P.length - 1].t)},${H - B}`} />}
        <polyline fill="none" stroke={COL[si % 3]} strokeWidth="2.4" strokeLinejoin="round" strokeLinecap="round" strokeDasharray={DASH[si % 3]} points={line} />
        {P.map((p, i) => { const dn = below(si, p); return <g key={i}><circle cx={X(p.t)} cy={Y(p.v)} r="4.5" fill="#fff" stroke={COL[si % 3]} strokeWidth="2.2" />
          <text x={X(p.t)} y={Y(p.v) + (dn ? 20 : -10)} fontSize="11.5" fontWeight="650" textAnchor="middle" fill={COL[si % 3]}>{p.v}</text></g> })}</g>
    })}
  </svg>
}

function Summary({ c, reload }) {
  const a = c.assessment, d = a.drug_check
  const red = c.alerts.filter(x => x.level === 'red'), other = c.alerts.filter(x => x.level !== 'red')
  const nUn = a.unevaluated.length + a.routing.pending_data.length
  return <>
    {red.map(x => <div key={x.id} className="urgent" role="alert"><span className="u-ico"><Icon name="alert" size={22} /></span>
      <div className="grow"><div className="u-kicker">Срочный сигнал</div><div className="u-title">{x.title}</div><div className="small mute">{fmt(x.created_at)}</div><div style={{ marginTop: 6 }}><StatusPill s={x.status} /></div></div>
      <a className="btn" href={'#/alerts/' + x.id}>Открыть алерт<Icon name="right" size={18} /></a></div>)}
    <div className="split">
      <div>
        <Drug d={d} />
        <div className="section-title" style={{ marginTop: 8 }}><h2>Предложения системы — решение за вами</h2><span className="count">{c.proposals.length}</span></div>
        {c.proposals.length === 0 && <div className="card"><Empty icon="checkCircle" title="Нет предложений, ожидающих решения" /></div>}
        {c.proposals.map(p => <Proposal key={p.id} p={p} onDone={reload} />)}
        {a.status_suggestions.length > 0 && <div className="card"><h3>Динамика: предложения статуса</h3>{a.status_suggestions.map((s, i) => <p key={i}>{s.status}: {s.reason || s.text} <span className="small mute">· ожидает вашего решения</span></p>)}</div>}
        {c.orders.length > 0 && <div className="card"><div className="card-head"><span className="ico-bubble"><Icon name="pill" size={18} /></span><h3>Назначения (подтверждены врачом)</h3></div>{c.orders.map(o => <p key={o.id}>{o.drug} · с {o.started_on}</p>)}</div>}
        <DoctorPsyNotes pid={c.patient.id} />
        {c.referrals.length > 0 && <div className="card"><div className="card-head"><span className="ico-bubble"><Icon name="users" size={18} /></span><h3>Направления к психиатру</h3></div>{c.referrals.map(r => <div key={r.id} className="row" style={{ padding: '6px 0' }}>{r.kind === 'mandatory' ? <span className="tier tier-must">Обязательно</span> : r.kind === 'desirable' ? <span className="tier tier-want">Желательно</span> : null}<span className="xs faint">{r.rule_id}</span>{r.due_at && <span className="small mute">до {fmt(r.due_at)}</span>}<span className="grow" /><Pill tone={r.status === 'awaiting_acceptance' ? 'amber' : 'green'}>{r.status === 'awaiting_acceptance' ? 'ждёт принятия' : 'принято психиатром'}</Pill></div>)}</div>}
        {nUn > 0 && <details className="card"><summary>Что система не смогла оценить (нет данных): {nUn}</summary>
          <div style={{ marginTop: 10 }}>{a.unevaluated.map(u => <p key={u.rule_id} className="small">{u.title}: {u.reason}{u.missing_facts.length ? ' — нужны: ' + u.missing_facts.join(', ') : ''}</p>)}
            {a.routing.pending_data.map(u => <p key={u.rule_id} className="small">{u.title}: {u.why}</p>)}</div></details>}
      </div>
      <div>
        {other.length > 0 && <div className="card"><div className="card-head"><span className="ico-bubble"><Icon name="bell" size={18} /></span><h3>Сигналы</h3><span className="pill pill-gray" style={{ marginLeft: 'auto' }}>{other.length}</span></div>
          {other.map(x => <a key={x.id} className="sig" href={'#/alerts/' + x.id}><Level l={x.level} /><span className="sig-t">{x.title}</span>{x.after_hours && <span className="xs mute">вне рабочего времени</span>}</a>)}</div>}
        <Scales c={c} />
        <div className="card"><div className="card-head"><span className="ico-bubble"><Icon name="activity" size={18} /></span><h3>Гипотеза профиля симптомов</h3></div>
          {a.hypothesis.lines.map((l, i) => <p key={i}>{l}</p>)}
          {a.amplifiers.length > 0 && <p style={{ marginBottom: 0 }}><strong>Усилители:</strong> {a.amplifiers.join('; ')}</p>}</div>
        <p className="xs mute">Диагноз устанавливает врач. Система скорую помощь не вызывает.</p>
      </div>
    </div></>
}

function Dynamics({ c }) {
  const s = Object.entries(c.dynamics.series), [range, setRange] = useState(12)
  const sch = c.schedule || {}, adh = c.adherence || {}
  return <div>
    {s.length === 0 && <div className="card"><Empty icon="trend" title="Завершённых шкал пока нет" /></div>}
    {s.length > 0 && <div className="card"><div className="card-head" style={{ flexWrap: 'wrap' }}><span className="ico-bubble"><Icon name="trend" size={18} /></span><h3>Баллы по шкалам</h3><span className="grow" />
      <div className="seg" role="group" aria-label="Период">{[[6, '6 нед'], [12, '12 нед'], [0, 'Всё время']].map(([k, l]) => <button key={k} className={range === k ? 'on' : ''} aria-pressed={range === k} onClick={() => setRange(k)}>{l}</button>)}</div></div>
      <div className="chart-legend">{s.map(([k, v], i) => <span key={k}><i style={{ borderTopColor: COL[i % 3], borderTopStyle: DASHN[i % 3] }} />{v.title}</span>)}
        <span><svg width="12" height="10" viewBox="0 0 12 10"><path d="M6 0l6 10H0z" fill="#9B3B36" /></svg>сигнал</span><span><i style={{ borderTopColor: '#1B6A70', borderTopStyle: 'dashed', width: 14 }} />начало терапии</span></div>
      <TimeChart series={s} events={c.timeline_events || []} range={range} /></div>}
    <div className="cols">{s.map(([k, v], i) => <div className="card stat-card" key={k}>
      <div className="row"><span className="xs mute" style={{ fontWeight: 700, letterSpacing: '.04em', textTransform: 'uppercase' }}>{v.title}</span><span className="grow" /><i style={{ display: 'inline-block', width: 22, borderTop: `2.5px ${DASHN[i % 3]} ${COL[i % 3]}` }} /></div>
      <div className="row" style={{ alignItems: 'baseline', gap: 8, marginTop: 6 }}><span className="big">{v.latest}</span>{v.max ? <span className="mute small">из {v.max}</span> : null}</div>
      <p className="small" style={{ margin: '6px 0 0' }}>Исходно {v.baseline} → сейчас {v.latest} <strong>({v.change > 0 ? '+' : ''}{v.change}{v.change_pct != null ? ', ' + v.change_pct + '%' : ''})</strong></p>
      {v.significant_improvement_hint && <p className="lv lv-green">значимое улучшение по ориентиру ≥{v.hint_points} баллов</p>}{v.significant_worsening_hint && <p className="lv lv-orange">значимое ухудшение по ориентиру ≥{v.hint_points} баллов</p>}</div>)}</div>
    {c.dynamics.notes.map((n, i) => <p key={i} className="small mute"><Icon name="info" size={15} /> Ориентир: {n}</p>)}
    <div className="grid2" style={{ marginTop: 12 }}>
      <div className="card"><div className="card-head"><span className="ico-bubble"><Icon name="calendar" size={18} /></span><h3>Расписание измерений</h3></div>
        <dl className="kv small"><dt>Стадия</dt><dd>{sch.stage || '—'}</dd><dt>Инструменты</dt><dd>{(sch.instruments || []).join(', ') || '—'}</dd><dt>Следующие шкалы</dt><dd>{sch.next_scales_due ? fmt(sch.next_scales_due) : 'не запланированы'}</dd></dl></div>
      <div className="card"><div className="card-head"><span className="ico-bubble"><Icon name="checkCircle" size={18} /></span><h3>Приверженность</h3><span style={{ marginLeft: 'auto' }}>{adh.active ? <Pill tone="green">учёт включён</Pill> : <Pill tone="gray">учёт не активен</Pill>}</span></div>
        <p className="small" style={{ marginBottom: 0 }}>{adh.note || (adh.active ? 'Данные о приёме собираются из ежедневного чек-ина.' : '—')}</p></div>
    </div>
    <details className="card"><summary>Расписание и приверженность (технические данные)</summary><pre>{JSON.stringify({ schedule: c.schedule, adherence: c.adherence }, null, 1)}</pre></details></div>
}

function Field({ f, pid, reload }) {
  const [v, setV] = useState(f.value ?? ''), [e, setE] = useState(null), [ok, setOk] = useState(false)
  const save = async () => { setE(null); setOk(false); try { await put(`/api/doctor/patients/${pid}/profile/${f.id}`, { value: v === '' ? null : v }); setOk(true); reload() } catch (x) { setE(x.message) } }
  const head = <div className="f-label"><strong>{f.label}</strong>{f.note && <div className="xs mute">{f.note}</div>}</div>
  if (f.type === 'system_generated') return <div className="f-row">{head}<div className="mute small">формируется системой</div><div /></div>
  let input
  if (f.type === 'tri_state') input = <select value={v || 'unknown'} onChange={x => setV(x.target.value)} aria-label={f.label}><option value="unknown">неизвестно</option><option value="yes">да</option><option value="no">нет</option></select>
  else if (f.options) input = <select value={v} onChange={x => setV(x.target.value)} aria-label={f.label}><option value="">—</option>{f.options.map(o => <option key={o}>{o}</option>)}</select>
  else input = <input value={v} onChange={x => setV(x.target.value)} aria-label={f.label} />
  return <div className="f-row">{head}<div>{input}<Err e={e} />{ok && <span className="xs" style={{ color: 'var(--green-ink)', fontWeight: 600 }}><Icon name="check" size={14} /> сохранено</span>}</div><div><button className="sec" onClick={save}>Сохранить</button></div></div>
}

function Profile({ c, reload }) {
  const pid = c.patient.id
  const [meds, , rm] = useLoad(() => get(`/api/doctor/patients/${pid}/meds`), [pid])
  const [cat] = useLoad(() => get('/api/doctor/symptom-catalog'), [])
  const [nm, setNm] = useState(''), [dose, setDose] = useState(''), [sym, setSym] = useState({ name: '', present: 'yes', duration_weeks: '' }), [msg, setMsg] = useState(null), [e, setE] = useState(null)
  const flags = [['immediate_threat', 'Непосредственная угроза себе или окружающим'], ['secondary_cause_suspected', 'Подозрение на вторичную причину']]
  const run = async f => { setE(null); try { await f(); reload() } catch (x) { setE(x.message) } }
  return <div>
    <Err e={e} />
    <div className="split">
      <div>
        <div className="card"><div className="card-head"><span className="ico-bubble"><Icon name="user" size={18} /></span><h2>Клинический профиль</h2></div>
          <p className="small mute">Три состояния: да / нет / неизвестно. «Неизвестно» не равно «нет»: проверка безопасности останется незавершённой.</p>
          <div className="f-list">{c.profile_fields.map(f => <Field key={f.id} f={f} pid={pid} reload={reload} />)}</div></div>
        <div className="card"><div className="card-head"><span className="ico-bubble"><Icon name="clipboard" size={18} /></span><h2>Ответы анкеты</h2></div>
          {c.intake.map(q => <div key={q.id} className="qa"><div className="xs mute">{q.text}</div><div>{Array.isArray(q.answer) ? q.answer.join('; ') : JSON.stringify(q.answer)}</div>{(q.details || []).map((x, i) => <div key={i} className="xs mute">{x.q}: {x.a}</div>)}</div>)}{!c.intake.length && <Empty icon="clipboard" title="Анкета не заполнена" />}</div>
      </div>
      <div>
        <div className="card"><div className="card-head"><span className="ico-bubble"><Icon name="pill" size={18} /></span><h2>Принимаемые препараты</h2></div>
          {meds && meds.length === 0 && <p className="mute small">Список пуст.</p>}
          {meds && meds.map(m => <div className="med" key={m.id}><div className="grow"><b>{m.name}</b> {m.dose || ''}<div className="xs mute">{m.source}</div></div><button className="ghost sm" onClick={() => run(async () => { await api_del(pid, m.id); rm() })}>Убрать</button></div>)}
          <div className="stack" style={{ marginTop: 12 }}><input placeholder="Название (МНН)" value={nm} onChange={x => setNm(x.target.value)} /><div className="row"><input className="grow" placeholder="Доза" value={dose} onChange={x => setDose(x.target.value)} style={{ width: 'auto' }} />
            <button onClick={() => run(async () => { const r = await post(`/api/doctor/patients/${pid}/meds`, { name: nm, dose: dose || null }); setMsg(r.note); setNm(''); setDose(''); rm(); toast('Препарат добавлен') })}><Icon name="plus" size={18} />Добавить</button></div></div>
          {msg && <p className="banner b-warn small" style={{ marginTop: 12 }}>{msg}</p>}</div>
        <div className="card"><div className="card-head"><span className="ico-bubble"><Icon name="activity" size={18} /></span><h2>Симптомы и длительность</h2></div>
          {cat && <div className="stack"><select value={sym.name} onChange={x => setSym({ ...sym, name: x.target.value })} aria-label="Симптом"><option value="">Выберите симптом</option>{[...cat.depressive.main, ...cat.depressive.additional, ...cat.gad.autonomic, ...cat.gad.other].map(s => <option key={s}>{s}</option>)}</select>
            <div className="row"><select value={sym.present} onChange={x => setSym({ ...sym, present: x.target.value })} style={{ flex: 1 }} aria-label="Наличие"><option value="yes">есть</option><option value="no">нет</option><option value="unknown">неизвестно</option></select>
              <input style={{ width: 120 }} type="number" min="0" placeholder="недель" aria-label="Длительность, недель" value={sym.duration_weeks} onChange={x => setSym({ ...sym, duration_weeks: x.target.value })} /></div>
            <button disabled={!sym.name} onClick={() => run(() => put(`/api/doctor/patients/${pid}/symptoms`, { name: sym.name, present: sym.present, duration_weeks: sym.duration_weeks === '' ? null : Number(sym.duration_weeks) }))}>Записать</button></div>}</div>
        <div className="card"><div className="card-head"><span className="ico-bubble"><Icon name="shield" size={18} /></span><h2>Клинические флаги</h2></div>
          {flags.map(([k, l]) => <div className="flag" key={k}><span className="grow">{l}</span><div className="row tight"><button className="sec sm" onClick={() => run(() => put(`/api/doctor/patients/${pid}/flags/${k}`, { value: true }))}>Установить</button><button className="ghost sm" onClick={() => run(() => put(`/api/doctor/patients/${pid}/flags/${k}`, { value: false }))}>Снять</button></div></div>)}</div>
      </div>
    </div></div>
}
const api_del = (pid, id) => api('DELETE', `/api/doctor/patients/${pid}/meds/${id}`)

function Contact({ c, reload }) {
  const pid = c.patient.id
  const [plan, , rp] = useLoad(() => get(`/api/doctor/patients/${pid}/plan`), [pid])
  const [msgs, , rm] = useLoad(() => get(`/api/doctor/patients/${pid}/messages`), [pid])
  const [t, setT] = useState(''), [goal, setGoal] = useState(c.goal || ''), [pl, setPl] = useState({}), [mis, setMis] = useState(null)
  return <div className="split">
    <div>
      <div className="card"><div className="card-head"><span className="ico-bubble"><Icon name="message" size={18} /></span><h2>Сообщения</h2></div>
        {msgs && msgs.length === 0 && <Empty icon="message" title="Переписки пока нет">Пациент получит сообщение в своём приложении</Empty>}
        {msgs && msgs.length > 0 && <div className="chat">{msgs.map(m => <div key={m.id} className={'bubble ' + (m.from_patient ? 'in' : 'out') + (m.kind === 'appointment_request' ? ' req' : '')}>
          {m.kind === 'appointment_request' && <div className="xs" style={{ fontWeight: 700, color: m.from_patient ? 'var(--violet)' : 'inherit', marginBottom: 2 }}>Запрос приёма</div>}{m.body}
          <span className="b-meta">{m.from_patient ? 'пациент' : 'вы'} · {fmt(m.ts)}</span></div>)}</div>}
        {!msgs && <Loading rows={2} card={false} />}
        <div className="composer"><textarea value={t} onChange={e => setT(e.target.value)} aria-label="Сообщение" placeholder="Сообщение пациенту" />
          <Templates onPick={setT} />
          <Busy onClick={async () => { await post(`/api/doctor/patients/${pid}/messages`, { body: t }); setT(''); rm(); toast('Сообщение отправлено') }} disabled={!t.trim()}><Icon name="send" size={18} />Отправить</Busy></div></div>
      <div className="card"><div className="card-head"><span className="ico-bubble"><Icon name="shield" size={18} /></span><h2>Мой план действий</h2><span style={{ marginLeft: 'auto' }}>{plan && (plan.confirmed_by_doctor ? <Pill tone="green" icon="check">подтверждён</Pill> : <Pill tone="amber">не подтверждён</Pill>)}</span></div>
        {plan && plan.sections.map(s => <div key={s.id}><label>{s.label}</label><textarea defaultValue={s.text} onChange={e => setPl({ ...pl, [s.id]: e.target.value })} style={{ minHeight: 72 }} /></div>)}
        {!plan && <Loading rows={3} card={false} />}
        <div className="row" style={{ marginTop: 14 }}><Busy onClick={async () => { await put(`/api/doctor/patients/${pid}/plan`, { sections: pl }); setPl({}); rp(); toast('План сохранён') }} disabled={!Object.keys(pl).length}>Сохранить изменения</Busy>
          <Busy cls="sec" onClick={async () => { await post(`/api/doctor/patients/${pid}/plan/confirm`); rp(); toast('План подтверждён') }}><Icon name="checkCircle" size={18} />Подтвердить план</Busy></div></div>
    </div>
    <div>
      <div className="card"><div className="card-head"><span className="ico-bubble"><Icon name="calendar" size={18} /></span><h3>Ежедневный чек-ин</h3></div>
        <p className="small">{c.patient.checkin_enabled_on ? <>Включён с {c.patient.checkin_enabled_on}</> : 'Выключен'}</p>
        <Busy cls={c.patient.checkin_enabled_on ? 'sec block' : 'block'} onClick={async () => { await put(`/api/doctor/patients/${pid}/checkin`, { enabled: !c.patient.checkin_enabled_on }); reload(); toast(c.patient.checkin_enabled_on ? 'Чек-ин выключен' : 'Чек-ин включён') }}>{c.patient.checkin_enabled_on ? 'Выключить' : 'Включить'}</Busy></div>
      <div className="card"><div className="card-head"><span className="ico-bubble"><Icon name="sparkle" size={18} /></span><h3>Цель пациента</h3></div>
        <input value={goal} onChange={e => setGoal(e.target.value)} aria-label="Цель" /><div style={{ marginTop: 10 }}><Busy cls="sec block" onClick={async () => { await put(`/api/doctor/patients/${pid}/goal`, { text: goal }); reload(); toast('Цель сохранена') }}>Сохранить цель</Busy></div></div>
      <div className="card"><div className="card-head"><span className="ico-bubble"><Icon name="external" size={18} /></span><h3>Интеграция</h3></div>
        <Busy cls="sec block" onClick={async () => { const r = await post(`/api/integration/mis/push/${pid}`); setMis(r) }}>Отправить сводку в МИС</Busy>
        {mis && <p className="xs mute" style={{ margin: '8px 0 0' }}><Icon name="check" size={14} /> Отправлено в МИС (заглушка){mis.external_id ? ': ' + mis.external_id : ''}</p>}</div>
    </div></div>
}

function Import({ c, reload }) {
  const pid = c.patient.id
  const [txt, setTxt] = useState(''), [job, setJob] = useState(null), [sel, setSel] = useState({}), [r, setR] = useState(null)
  const KIND = { dx_icd10: 'Диагноз (МКБ-10)', egfr_ml_min: 'СКФ', med: 'Препарат', scale_total: 'Балл шкалы (справка)', allergy_mention: 'Аллергия (справка)', med_mentioned_not_current: 'Препарат отменён (не предлагается)' }
  return <div className="card"><div className="card-head"><span className="ico-bubble"><Icon name="upload" size={18} /></span><h2>Импорт истории болезни</h2></div>
    <p className="small mute">Система найдёт кандидатов, ничего не попадёт в карточку без вашей проверки. Баллы шкал из документов в расчёт правил не входят.</p>
    <textarea style={{ minHeight: 160 }} value={txt} onChange={e => setTxt(e.target.value)} aria-label="Текст истории" placeholder="Вставьте текст выписки или истории болезни" />
    <div className="row" style={{ marginTop: 12 }}><Busy onClick={async () => { const j = await post(`/api/doctor/patients/${pid}/import`, { text: txt }); setJob(j); setSel({}); setR(null) }} disabled={txt.length < 10}><Icon name="search" size={18} />Найти кандидатов</Busy></div>
    {job && <><div className="table-scroll" style={{ margin: '16px -20px 0', borderTop: '1px solid var(--line)' }}><table><thead><tr><th style={{ width: 48 }}>Принять</th><th>Тип</th><th>Значение</th><th>Фрагмент</th></tr></thead><tbody>{job.items.map(([i, it]) => <tr key={i}>
      <td><input type="checkbox" checked={!!sel[i]} disabled={!['dx_icd10', 'egfr_ml_min', 'med'].includes(it.kind)} onChange={e => setSel({ ...sel, [i]: e.target.checked })} aria-label="Принять" /></td><td>{KIND[it.kind]}</td>
      <td><strong>{typeof it.value === 'object' ? it.value.scale + ': ' + it.value.total : it.value}</strong>{it.dose ? ' · ' + it.dose : ''}</td><td className="small mute">…{it.excerpt}…</td></tr>)}</tbody></table></div>
      <div className="row" style={{ marginTop: 14 }}><Busy onClick={async () => { const x = await post(`/api/doctor/patients/${pid}/import/${job.job_id}/apply`, { accept: Object.keys(sel).filter(k => sel[k]).map(Number) }); setR(x); setJob(null); reload(); toast('Принято пунктов: ' + x.applied.length) }}><Icon name="check" size={18} />Принять отмеченное</Busy></div></>}
    {r && <p className="banner b-info" style={{ marginTop: 14 }}>Принято пунктов: {r.applied.length}. Список препаратов требует повторного подтверждения.</p>}</div>
}

const Kpi = ({ label, s }) => {
  if (!s) return <div className="kpi"><div className="k-label">{label}</div><div className="k-val faint">—</div><div className="k-sub">нет данных</div></div>
  const diff = s.previous != null ? s.latest - s.previous : null
  return <div className="kpi"><div className="k-label">{label}</div>
    <div className="k-val">{s.latest}{s.max ? <small>/ {s.max}</small> : null}{diff != null && diff !== 0 && <span className="delta" title={'предыдущее: ' + s.previous}><Icon name={diff > 0 ? 'arrowUp' : 'arrowDown'} size={14} stroke={2.2} />{Math.abs(diff)}</span>}</div>
    <div className="k-sub" title={(s.latest_label || '') + (s.previous != null ? ' · предыдущее: ' + s.previous : '')}>{s.latest_label || (s.previous != null ? 'предыдущее: ' + s.previous : '')}</div></div>
}

export function PatientCard({ id, tab }) {
  const [c, err, reload] = useLoad(() => get(`/api/doctor/patients/${id}/card`), [id])
  const t = tab || 'summary'
  if (err) return <div className="wrap"><Err e={err} /><a href="#/doctor">К списку</a></div>
  if (!c) return <PageLoading />
  const S = c.dynamics.series, nRed = c.alerts.filter(a => a.level === 'red').length
  const tabs = [['summary', 'Сводка', c.proposals.length], ['dynamics', 'Динамика'], ['profile', 'Профиль и данные'], ['contact', 'Связь и план'], ['import', 'Импорт']]
  return <div className="wrap">
    <nav className="crumbs" aria-label="Навигация"><a href="#/doctor"><Icon name="left" size={16} />Пациенты</a><span aria-hidden="true">/</span><span>{c.patient.code}</span></nav>
    <div className="card pt-head">
      <Avatar text={c.patient.code} size={56} tone={TONE[c.level]} />
      <div style={{ minWidth: 0, flex: '1 1 220px' }}><h1>{c.patient.code}<Level l={c.level} /></h1>
        <div className="pt-meta"><span>{c.patient.sex}{c.patient.age != null ? ', ' + c.patient.age + ' лет' : ''}</span><span className="pid-chip" title="Личный номер пациента">ID KK-{String(c.patient.id).padStart(6, '0')}</span>
          <span className="row tight"><Icon name="calendar" size={15} />чек-ин: {c.patient.checkin_enabled_on ? 'включён' : 'выключен'}</span></div></div>
      <div className="pt-actions"><Busy cls="sec" onClick={() => download('/api/doctor/patients/' + c.patient.id + '/summary.pdf', 'summary-' + c.patient.code + '.pdf')}><Icon name="download" size={18} /><span className="hide-sm">Сводка для психиатра (PDF)</span><span className="show-sm">Сводка PDF</span></Busy>
        <button className="sec" onClick={() => go(`#/doctor/patient/${id}/contact`)}><Icon name="message" size={18} />Написать</button></div>
    </div>
    <div className="pt-kpis">
      <Kpi label="PHQ-9" s={S.phq9} /><Kpi label="GAD-7" s={S.gad7} />
      <div className="kpi"><div className="k-label">Открытые сигналы</div><div className="k-val" style={nRed ? { color: 'var(--red)' } : null}>{c.alerts.length}</div><div className="k-sub">{nRed ? 'из них критических: ' + nRed : 'критических нет'}</div></div>
      <div className="kpi"><div className="k-label">Ждут решения</div><div className="k-val">{c.proposals.length}</div><div className="k-sub">предложения системы</div></div>
    </div>
    <CardSummary c={c} />
    <div className="sticky-tabs"><div className="tabs" role="tablist">{tabs.map(([k, l, n]) => <button key={k} role="tab" aria-selected={t === k} className={t === k ? 'on' : ''} onClick={() => go(`#/doctor/patient/${id}/${k}`)}>{l}{n ? <span className="tab-count">{n}</span> : null}</button>)}</div></div>
    {t === 'summary' && <Summary c={c} reload={reload} />}{t === 'dynamics' && <Dynamics c={c} />}{t === 'profile' && <Profile c={c} reload={reload} />}{t === 'contact' && <Contact c={c} reload={reload} />}{t === 'import' && <Import c={c} reload={reload} />}</div>
}
