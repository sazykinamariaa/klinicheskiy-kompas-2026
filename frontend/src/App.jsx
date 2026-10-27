import React, { useEffect, useState } from 'react'
import { get, post, setToken, hasToken, session } from './api.js'
import { Err, go, Icon, Mark, Avatar, useLoad, Toaster } from './common.jsx'
import { DoctorHome, PatientCard, NewPatient } from './Doctor.jsx'
import { AlertList, AlertView, Referrals, Admin, Sources } from './Staff.jsx'
import { PatientApp, Join } from './Patient.jsx'
import { Invite } from './Invite.jsx'
import PatientNav from './PatientNav.jsx'
import { Hints, DoctorReferrals, DrugSafety } from './DoctorSections.jsx'
import { DutyCenter, DutyRouting, Protocols, Handover } from './DutySections.jsx'
import './duty-sections.css'
import { PsyHome, PsyDynamics, PsyRecommendations, PsyPlan, PsyMessages } from './PsySections.jsx'
import './psy-sections.css'
import './doctor-sections.css'
import DevSwitcher from './DevSwitcher.jsx'
import GoogleButton from './GoogleButton.jsx'

const HOME = { doctor: '#/doctor', duty: '#/duty', psychiatrist: '#/psy', admin: '#/admin', patient: '#/p' }
const ROLE = { doctor: 'Врач', duty: 'Дежурный', psychiatrist: 'Психиатр', admin: 'Администратор', patient: 'Пациент' }
// [ссылка, иконка, подпись, короткая подпись для телефона]
const NAV = {
  doctor: [['#/doctor', 'users', 'Мои пациенты', 'Пациенты'], ['#/doctor/hints', 'sparkle', 'Клинические подсказки', 'Подсказки'], ['#/doctor/referrals', 'inbox', 'Направления'], ['#/doctor/drugs', 'pill', 'Лекарственная безопасность', 'Лекарства'], ['#/alerts', 'bell', 'Алерты'], ['#/sources', 'book', 'Источники', null, true]],
  duty: [['#/duty', 'bell', 'Центр оповещений', 'Оповещения'], ['#/alerts', 'alert', 'Пациенты и алертинг', 'Сигналы'], ['#/duty/routing', 'users', 'Маршрутизация и эскалация', 'Маршруты'], ['#/duty/protocols', 'book', 'Протоколы реагирования', 'Протоколы'], ['#/duty/handover', 'clipboard', 'Передача смены', 'Смена']],
  psychiatrist: [['#/psy', 'users', 'Мои пациенты', 'Пациенты'], ['#/psy/dynamics', 'activity', 'Динамика состояния', 'Динамика'], ['#/psy/recommendations', 'sparkle', 'Клинические рекомендации', 'Рекомендации'], ['#/psy/plan', 'clipboard', 'План лечения и наблюдения', 'План'], ['#/psy/messages', 'message', 'Сообщения от пациентов', 'Сообщения'], ['#/psy/referrals', 'inbox', 'Направления', null, true]],
  admin: [['#/admin', 'sliders', 'Администрирование', 'Админ'], ['#/sources', 'book', 'Источники']],
}

const logout = async () => { try { await post('/api/auth/logout') } catch {} setToken(null); session.role = null; go('#/login') }

function Login() {
  const [l, setL] = useState(''), [p, setP] = useState(''), [e, setE] = useState(null), [show, setShow] = useState(false), [busy, setBusy] = useState(false)
  const [mode, setMode] = useState('in'), [code, setCode] = useState(''), [cfg, setCfg] = useState(null)
  useEffect(() => { get('/api/public/auth-config').then(setCfg).catch(() => setCfg({})) }, [])
  const enter = r => { setToken(r.token); session.role = r.role; session.name = r.name; go(HOME[r.role]) }
  const viaGoogle = async t => { setE(null); try { enter(await post('/api/auth/google', { id_token: t })) } catch (x) { setE(x.message) } }
  const submit = async ev => {
    ev.preventDefault(); setE(null); setBusy(true)
    try { enter(await post('/api/auth/login', { login: l, password: p })) } catch (x) { setE(x.message) }
    setBusy(false)
  }
  return <div className="auth">
    <section className="auth-hero">
      <a className="brand" href="#/login"><Mark size={40} /><span className="brand-text"><b>Клинический компас</b><small>Цифровой ассистент врача</small></span></a>
      <div><h1>Тревога и депрессия: оценка, динамика и безопасность — в одной карточке</h1>
        <p className="lead">Поддержка принятия клинических решений для врача и спокойный дневник самочувствия для пациента. Диагноз устанавливает врач.</p></div>
      <div className="auth-benefits">
        {[['shield', 'Безопасность', 'Система следит за нежелательными явлениями, взаимодействиями и противопоказаниями и сразу сообщает врачу о тревожных сигналах.'],
          ['activity', 'Оценка и динамика', 'Регулярные анкеты показывают, как меняется состояние пациента, и помогают вовремя заметить ухудшение.'],
          ['send', 'Маршрутизация', 'Терапевт направляет пациента к психиатру в пару кликов, и результаты анкет с кратким анамнезом передаются автоматически.']]
          .map(([ic, t, d]) => <div className="auth-benefit" key={t}><span className="ib"><Icon name={ic} /></span><div><b>{t}</b><span>{d}</span></div></div>)}
      </div>
    </section>
    <section className="auth-panel">
      <div className="auth-card">
        <a className="brand auth-mobile-brand" href="#/login"><Mark size={40} /><span className="brand-text"><b>Клинический компас</b><small>Цифровой ассистент врача</small></span></a>
        <h2>{mode === 'in' ? 'Вход' : 'Регистрация пациента'}</h2><p className="mute">{mode === 'in' ? 'Для врачей, персонала и пациентов' : 'По коду приглашения от вашего врача'}</p>
        <div className="seg auth-seg" role="tablist"><button type="button" role="tab" aria-selected={mode === 'in'} className={mode === 'in' ? 'on' : ''} onClick={() => setMode('in')}>Вход</button><button type="button" role="tab" aria-selected={mode === 'reg'} className={mode === 'reg' ? 'on' : ''} onClick={() => setMode('reg')}>Регистрация</button></div>
        {mode === 'reg' && <form className="card" style={{ marginTop: 14 }} onSubmit={ev => { ev.preventDefault(); if (code.trim()) go('#/join/' + code.trim().toUpperCase()) }}>
          <label htmlFor="ic" style={{ marginTop: 0 }}>Код приглашения</label><input id="ic" value={code} onChange={x => setCode(x.target.value)} placeholder="Например, VR5ACTYL" autoCapitalize="characters" autoCorrect="off" spellCheck={false} />
          <p className="xs mute" style={{ margin: '8px 0 0' }}>Код выдаёт врач: он есть в QR-коде или ссылке приглашения. Так ваши данные сразу попадут к вашему лечащему врачу, а вы получите личный номер пациента.</p>
          <button type="submit" className="block" style={{ marginTop: 18 }} disabled={!code.trim()}>Продолжить<Icon name="arrowRight" size={18} /></button>
          </form>}
        {mode === 'in' && <form className="card" onSubmit={submit} style={{ marginTop: 14 }}>
          <label htmlFor="l" style={{ marginTop: 0 }}>Логин</label><input id="l" autoCapitalize="none" autoCorrect="off" spellCheck={false} value={l} onChange={x => setL(x.target.value)} autoComplete="username" />
          <label htmlFor="p">Пароль</label><div className="pw"><input id="p" type={show ? 'text' : 'password'} value={p} onChange={x => setP(x.target.value)} autoComplete="current-password" />
            <button type="button" onClick={() => setShow(!show)} aria-label={show ? 'Скрыть пароль' : 'Показать пароль'} title={show ? 'Скрыть пароль' : 'Показать пароль'}><Icon name={show ? 'eyeOff' : 'eye'} /></button></div>
          <Err e={e} />
          <button type="submit" className={'block' + (busy ? ' is-busy' : '')} style={{ marginTop: 20 }} disabled={busy}>Войти<Icon name="arrowRight" size={18} /></button>
          {cfg && cfg.google_client_id && <><div className="or"><span>или</span></div><GoogleButton clientId={cfg.google_client_id} onToken={viaGoogle} /></>}
        </form>}
      </div>
    </section>
    <DevSwitcher />
  </div>
}

function useBadge(role, path) {
  const fn = role === 'doctor' ? () => get('/api/doctor/inbox').then(r => ({ href: '#/alerts', count: r.alerts.length, hot: r.alerts.some(a => a.level === 'red') }))
    : role === 'duty' ? () => get('/api/alerts?open_only=true').then(r => ({ href: '#/alerts', count: r.length, hot: r.some(a => a.level === 'red') }))
      : role === 'psychiatrist' ? () => get('/api/psychiatrist/referrals').then(r => ({ href: '#/psy/referrals', count: r.filter(x => x.status === 'awaiting_acceptance').length }))
        : () => Promise.resolve(null)
  const [b] = useLoad(fn, [role, path])
  return b
}

function StaffShell({ children, path }) {
  const role = session.role, items = NAV[role] || []
  const badge = useBadge(role, path)
  const isOn = h => { const x = h.slice(1); if (x === '/doctor') return path === x || path.startsWith('/doctor/patient'); if (x === '/duty' || x === '/psy') return path === x; return path === x || path.startsWith(x + '/') }
  const item = ([h, ic, l, short], mobile) => {
    const on = isOn(h), cnt = badge && badge.href === h && badge.count > 0 ? <span className={'cnt' + (badge.hot ? ' hot' : '')}>{badge.count}</span> : null
    return <a key={h} href={h} className={on ? 'on' : ''} aria-current={on ? 'page' : undefined}>
      {mobile ? <span className="t-ico"><Icon name={ic} size={22} /></span> : <Icon name={ic} size={20} />}<span>{mobile ? (short || l) : l}</span>{cnt}</a>
  }
  return <div className="app">
    <aside className="side" aria-label="Навигация">
      <a className="brand" href={HOME[role] || '#/login'}><Mark size={36} /><span className="brand-text"><b>Клинический компас</b><small>{ROLE[role] || ''}</small></span></a>
      <div className="nav-label">Разделы</div>
      <nav className="nav">{items.map(it => item(it))}</nav>
      <div className="side-foot">
        <div className="me"><Avatar text={(ROLE[role] || '?')[0]} size={36} />
          <div className="me-text"><b title={session.name || ''}>{session.name || ROLE[role]}</b><small>{ROLE[role]}</small></div></div>
        <button className="sec" onClick={logout}><Icon name="logout" size={18} />Выйти</button>
      </div>
    </aside>
    <header className="mtop"><a className="brand" href={HOME[role] || '#/login'}><Mark size={32} /><span className="brand-text"><b>Клинический компас</b><small>{ROLE[role] || ''}</small></span></a>
      <button className="ghost icon" onClick={logout} aria-label="Выйти" title="Выйти"><Icon name="logout" size={22} /></button></header>
    <main className="main" id="main">{children}</main>
    {items.length > 1 && <nav className="mtab" aria-label="Разделы">{items.filter(it => !it[4]).map(it => item(it, true))}</nav>}
    <Toaster />
    <DevSwitcher />
  </div>
}

const FLOW = ['intake', 'scale', 'safety', 'checkin']
function PatientShell({ children, sub, join }) {
  if (!join && FLOW.includes(sub[0])) return <div className="patient flow">{children}<Toaster /></div>
  return <div className="patient">
    <header className="p-top"><div className="p-top-in"><a className="p-brand" href={join ? '#/login' : '#/p'}><Mark size={32} /><span>Клинический компас</span></a>
      {!join && <a className="p-me" href="#/p/profile" aria-label="Профиль и выход">{(session.name || 'Я').slice(0, 2).toUpperCase()}</a>}</div></header>
    {children}
    {!join && session.role === 'patient' && <PatientNav />}
    <Toaster />
    <DevSwitcher />
  </div>
}

export default function App() {
  const [h, setH] = useState(location.hash || '#/login'), [, tick] = useState(0), [ready, setReady] = useState(!hasToken() || !!session.role)
  useEffect(() => { const f = () => { setH(location.hash || '#/login'); tick(t => t + 1) }; addEventListener('hashchange', f); return () => removeEventListener('hashchange', f) }, [])
  useEffect(() => { if (hasToken() && !session.role) get('/api/auth/me').then(m => { session.role = m.role; session.name = m.name; setReady(true); if (h === '#/login' || h === '#/') go(HOME[m.role]) }).catch(() => { setToken(null); setReady(true) }) }, [])
  useEffect(() => { window.scrollTo(0, 0) }, [h])
  if (!ready) return <div className="splash"><Mark size={48} /><div className="skel" style={{ width: 140 }} /></div>
  const path = h.replace(/^#/, '')
  const p = path.split('/').filter(Boolean)
  if (p[0] === 'join') return <PatientShell join sub={[]}><Join code={p[1]} /></PatientShell>
  if (p[0] === 'invite') return <PatientShell join sub={[]}><Invite token={p[1]} /></PatientShell>
  if (!hasToken() || p[0] === 'login' || !p.length) return <Login />
  if (p[0] === 'p') return <PatientShell sub={p.slice(1)}><PatientApp sub={p.slice(1)} /></PatientShell>
  let v
  if (p[0] === 'doctor' && p[1] === 'patient') v = <PatientCard id={p[2]} tab={p[3]} />
  else if (p[0] === 'doctor' && p[1] === 'new') v = <NewPatient />
  else if (p[0] === 'doctor' && p[1] === 'hints') v = <Hints />
  else if (p[0] === 'doctor' && p[1] === 'referrals') v = <DoctorReferrals />
  else if (p[0] === 'doctor' && p[1] === 'drugs') v = <DrugSafety />
  else if (p[0] === 'doctor') v = <DoctorHome />
  else if (p[0] === 'duty' && p[1] === 'routing') v = <DutyRouting />
  else if (p[0] === 'duty' && p[1] === 'protocols') v = <Protocols />
  else if (p[0] === 'duty' && p[1] === 'handover') v = <Handover />
  else if (p[0] === 'duty') v = <DutyCenter />
  else if (p[0] === 'alerts' && p[1]) v = <AlertView id={p[1]} />
  else if (p[0] === 'alerts') v = <AlertList />
  else if (p[0] === 'sources') v = <Sources focus={p[1]} />
  else if (p[0] === 'psy' && p[1] === 'referrals') v = <Referrals />
  else if (p[0] === 'psy' && p[1] === 'dynamics') v = <PsyDynamics />
  else if (p[0] === 'psy' && p[1] === 'recommendations') v = <PsyRecommendations />
  else if (p[0] === 'psy' && p[1] === 'plan') v = <PsyPlan />
  else if (p[0] === 'psy' && p[1] === 'messages') v = <PsyMessages />
  else if (p[0] === 'psy') v = <PsyHome />
  else if (p[0] === 'admin') v = <Admin />
  else v = <div className="wrap"><h1>Страница не найдена</h1><p className="mute"><a href={HOME[session.role] || '#/login'}>На главную</a></p></div>
  return <StaffShell path={path}>{v}</StaffShell>
}
