import './patient.css'
import './patient-mobile.css'
import React, { useState } from 'react'
import { get, post, put, setToken, session } from './api.js'
import { useLoad, Err, Busy, go, Icon, Loading, Avatar, fmt, toast } from './common.jsx'
import Crisis from './Crisis.jsx'
import './patient-extras.css'
import { Methods, GoalCard, Steps, MedToday, MedDetails } from './PatientExtras.jsx'
import { visibleFollowups, Followups, fuText, fuValue } from './IntakeFollowups.jsx'

const logout = async () => { try { await post('/api/auth/logout') } catch {} setToken(null); session.role = null; go('#/login') }
const greet = () => { const h = new Date().getHours(); return h < 5 ? 'Доброй ночи' : h < 12 ? 'Доброе утро' : h < 18 ? 'Добрый день' : 'Добрый вечер' }
const today = () => new Date().toLocaleDateString('ru-RU', { weekday: 'long', day: 'numeric', month: 'long' })

// Верхняя панель пошагового опросника: закрыть, заголовок, прогресс
const FlowTop = ({ title, sub, i, n }) => <div className="flow-top"><div className="flow-top-in">
  <a className="icon-link" href="#/p" aria-label="Закрыть и вернуться на главную"><Icon name="x" size={24} /></a>
  <div className="ft-title">{title}{sub && <small>{sub}</small>}</div><span />
  {n ? <div className="prog" role="progressbar" aria-valuenow={i} aria-valuemin={0} aria-valuemax={n} aria-label="Прогресс"><div style={{ width: Math.min(100, 100 * i / n) + '%' }} /></div> : null}
</div></div>
const Actions = ({ children, two }) => <div className="flow-actions"><div className={'flow-actions-in' + (two ? ' two' : '')}>{children}</div></div>

export { Join } from './Join.jsx'

function Support({ s, compact }) {
  const [more, setMore] = useState(false), [d, setD] = useState(null)
  if (!s || s.screen === 'none') return null
  const open = async () => { setMore(!more); if (!d) setD(await get('/api/patient/support/details')) }
  const btns = (s.buttons || []).map(b => b.tel ? <a key={b.id} href={'tel:' + b.tel}><button><Icon name="phone" size={20} />{b.label}</button></a>
    : b.id === 'contact_doctor' ? <a key={b.id} href="#/p/messages"><button className="sec"><Icon name="message" size={20} />{b.label}</button></a>
      : <div key={b.id}><button className="sec" disabled title="Номер проверяется" style={{ width: '100%' }}>{b.label}</button><span className="sup-wait">Номер проверяется</span></div>)
  if (compact) return <div className="sup"><div className="sup-compact-head"><span className="bub"><Icon name="heart" size={22} /></span><strong>Поддержка рядом</strong></div>
    <p>Если вам сейчас тяжело или вы думаете о том, чтобы причинить себе вред, вы можете позвонить прямо сейчас или написать врачу.</p>
    <div className="row">{btns}</div>{s.after_hours_notice && <p className="small" style={{ margin: '12px 0 0' }}>{s.after_hours_notice}</p>}</div>
  return <div className="sup" role="alert">{s.screen === 'support_short' ? <><h2>{s.title}</h2><div className="lines">{s.lines.map((l, i) => <p key={i}>{l}</p>)}</div></> : <p>{s.text}</p>}
    <div className="row">{btns}</div>
    {s.after_hours_notice && <p className="small" style={{ margin: '14px 0 0' }}>{s.after_hours_notice}</p>}
    {s.details_available && <p style={{ margin: '6px 0 0' }}><button className="link" onClick={open} aria-expanded={more}>{more ? 'Скрыть' : 'Подробнее'}</button></p>}
    {more && d && <div style={{ marginTop: 8 }}><p><strong>{d.lead}</strong></p><p>{d.instructions_title}</p><ul>{d.instructions.map((i, k) => <li key={k}>{i}</li>)}</ul><p>{d.help_to_call}</p><p>{d.doctor_notified_line}</p><p className="small">{d.disclaimer}</p></div>}</div>
}

function Home() {
  const [h, err, reload] = useLoad(() => get('/api/patient/home'), [])
  const [tr] = useLoad(() => get('/api/patient/trend', { cache: 'no-cache' }), [])
  if (err) return <div className="wrap"><Err e={err} /></div>
  if (!h) return <div className="wrap"><div className="hello"><div className="skel" style={{ width: '42%' }} /><div className="skel" style={{ width: '68%', height: 30, marginTop: 14 }} /></div><Loading rows={3} /><Loading rows={2} /></div>
  if (h.support.screen === 'support_short') return <div className="wrap"><Crisis s={h.support} disclaimer={h.disclaimer} /></div>

  // [ссылка, заголовок, подпись, иконка, доля выполнения, текст кнопки]
  const todo = []
  if (!h.intake.finished) todo.push(['#/p/intake', h.intake.answered ? 'Продолжить анкету' : 'Начать анкету', `${h.intake.answered} из ${h.intake.total}`, 'clipboard', h.intake.total ? h.intake.answered / h.intake.total : null, h.intake.answered ? 'Продолжить' : 'Начать'])
  h.scales_to_fill.forEach(s => todo.push(['#/p/scale/' + s, 'Опросник ' + s.toUpperCase().replace('_', ' '), '', 'list', null, 'Начать']))
  if (h.safety_followup_needed) todo.push(['#/p/safety', 'Несколько вопросов о том, как вы сейчас', 'важно', 'heart', null, 'Ответить'])
  if (h.checkin_enabled) todo.push(['#/p/checkin', 'Отметить самочувствие сегодня', 'можно пропустить день', 'calendar', null, 'Отметить'])
  const [first, ...rest] = todo

  return <div className="wrap">
    <div className="hello"><span className="eyebrow">{today()}</span><h1>{greet()}</h1><p>Рады, что вы здесь. Здесь можно отмечать самочувствие и оставаться на связи с врачом.</p></div>
    {h.support.screen !== 'none' && <Support s={h.support} compact />}
    {first ? <a className="p-hero" href={first[0]}><span className="kicker">Следующий шаг</span><h2>{first[1]}</h2>{first[2] && <p>{first[2]}</p>}
      {first[4] != null && <div className="hbar" role="progressbar" aria-valuenow={Math.round(100 * first[4])} aria-valuemin={0} aria-valuemax={100} aria-label="Заполнено"><i style={{ width: Math.round(100 * first[4]) + '%' }} /></div>}
      <span className="hbtn">{first[5]}<Icon name="arrowRight" size={18} /></span></a>
      : <div className="p-hero done"><span className="kicker">На сегодня</span><h2>Всё, что нужно, уже сделано</h2><p>Спасибо!</p></div>}
    <MedToday />
    {h.reminder && h.support.screen === 'none' && <div className="p-note"><Icon name="sparkle" size={20} /><span>{h.reminder}</span></div>}
    {(rest.length > 0 || h.unread_messages > 0) && <><div className="p-section">Ещё на сегодня</div><div className="p-list">
      {h.unread_messages > 0 && <a className="p-row" href="#/p/messages"><span className="bub sup"><Icon name="message" size={22} /></span><span className="txt"><b>Новые сообщения от врача</b></span><span className="cnt">{h.unread_messages}</span><Icon name="right" className="chev" /></a>}
      {rest.map(([href, l, sub, ic]) => <a key={href} className="p-row" href={href}><span className="bub"><Icon name={ic} size={22} /></span><span className="txt"><b>{l}</b>{sub && <small>{sub}</small>}</span><Icon name="right" className="chev" /></a>)}</div></>}
    {tr && tr.message && <div className="card"><div className="p-trend"><span className="bub"><Icon name="trend" size={22} /></span><div><h3 style={{ marginBottom: 4 }}>Ваша динамика</h3><p className="clamp3">{tr.message}</p>
      <a className="p-more" href="#/p/trend">Подробнее<Icon name="right" size={16} /></a></div></div></div>}
    <div className="p-help"><div className="h-top"><span className="bub"><Icon name="heart" size={22} /></span><b>Если вам тяжело прямо сейчас:</b></div>
      <Busy cls="block" onClick={async () => { await post('/api/patient/need-support'); reload(); toast('Врач получит сообщение') }}>{h.need_support_button.label}</Busy>
      <p className="small mute">Врач получит сообщение. Если опасно, позвоните <a href="tel:112">112</a> или <a href="tel:103">103</a>.</p></div>
    <p className="p-disclaimer">{h.disclaimer}</p>
  </div>
}

// Текст ответа для просмотра анкеты
function answerText(q) {
  const a = q.answer, lab = id => ((q.options || []).find(o => o.id === id) || {}).label || id
  if (a == null) return '—'
  if (q.type === 'structured_list') return Array.isArray(a) && a.length ? a.map(m => m.name + (m.dose ? ' — ' + m.dose : '')).join('; ') : 'Ничего не принимаю'
  if (Array.isArray(a)) return a.map(lab).join('; ')
  if (typeof a === 'object') return lab(a.choice) + (a.text ? ': ' + a.text : '')
  return lab(a)
}

function Intake() {
  const [d, err] = useLoad(() => get('/api/patient/intake'), [])
  const [i, setI] = useState(null), [val, setVal] = useState(null), [e, setE] = useState(null), [sup, setSup] = useState(null), [free, setFree] = useState(''), [single, setSingle] = useState(false), [fv, setFv] = useState(null)
  if (err) return <><FlowTop title="Анкета" /><div className="wrap"><Err e={err} /></div></>
  if (!d) return <><FlowTop title="Анкета" /><div className="wrap"><Loading rows={5} /></div></>
  const Q = d.questions, idx = i ?? Math.max(0, Q.findIndex(q => q.answer == null)), q = Q[idx]
  if (Q.every(x => x.answer != null) && i == null) return <><FlowTop title="Моя анкета" /><div className="wrap">
    <div className="flow-done"><span className="big-ico"><Icon name="checkCircle" size={36} /></span><h2>Анкета заполнена</h2><p className="mute">Ответы сохранены и переданы врачу. Любой ответ можно изменить.</p></div>
    <div className="card iv-list">{Q.map((x, k) => <div className="iv-item" key={x.id}><div className="iv-q">{k + 1}. {x.text}</div><div className="iv-a">{answerText(x)}</div>
      {visibleFollowups(x, x.answer, Object.fromEntries((x.followups || []).map(f => [f.id, f.answer]))).map(f => { const t = fuText(f, f.answer); return t && <div className="iv-sub" key={f.id}>{f.short}: {t}</div> })}
      <button className="link" onClick={() => { setVal(null); setFv(null); setSingle(true); setI(k); window.scrollTo(0, 0) }}><Icon name="edit" size={16} />Изменить</button></div>)}</div></div>
    <Actions><a href="#/p" className="primary"><button className="block">На главную</button></a></Actions></>
  const cur = val ?? (q.answer ?? (q.type === 'multi' ? [] : q.type === 'structured_list' ? [] : null))
  const fvals = fv ?? Object.fromEntries((q.followups || []).filter(f => f.answer != null).map(f => [f.id, f.answer]))
  const toggle = id => { const ex = q.exclusive_options || []; let v = cur.includes(id) ? cur.filter(x => x !== id) : [...cur, id]; if (ex.includes(id)) v = [id]; else v = v.filter(x => !ex.includes(x)); setVal(v) }
  const next = async () => {
    setE(null)
    try {
      let a = cur
      if (q.type === 'single_plus_structured') a = free ? { choice: cur.choice || cur, text: free } : (cur.choice || cur)
      let r = await put('/api/patient/intake/' + q.id, { answer: a })
      for (const f of visibleFollowups(q, a, fvals)) {  // уточнения — необязательные, сохраняются только изменения
        const nv = fuValue(f, fvals[f.id])
        if (JSON.stringify(nv) !== JSON.stringify(f.answer ?? null)) { r = await put('/api/patient/intake/' + f.id, { answer: nv }); f.answer = nv }
      }
      setSup(r.support)
      setVal(null); setFv(null); setFree(''); Q[idx].answer = a
      if (single || idx + 1 >= Q.length) { setSingle(false); setI(null); window.scrollTo(0, 0) } else { setI(idx + 1); window.scrollTo(0, 0) }
    } catch (x) { setE(x.message) }
  }
  const choice = q.type === 'single_plus_structured' ? (cur && cur.choice) || cur : cur
  const ok = q.type === 'structured_list' ? true : q.type === 'multi' ? cur.length > 0 : choice != null
  const meds = Array.isArray(cur) ? cur : []
  return <>
    <FlowTop title="Анкета" sub={`Вопрос ${idx + 1} из ${Q.length}`} i={idx + 1} n={Q.length} />
    <div className="wrap">
      <Support s={sup} />
      <div className="flow-q"><h2>{q.text}</h2>{q.type === 'multi' ? <p className="flow-hint">Можно выбрать несколько вариантов · можно вернуться назад</p> : q.type !== 'structured_list' ? <p className="flow-hint">Можно вернуться назад</p> : null}</div>
      {(q.type === 'multi') && q.options.map(o => <button key={o.id} className={'opt multi ' + (cur.includes(o.id) ? 'on' : '')} aria-pressed={cur.includes(o.id)} onClick={() => toggle(o.id)}>{o.label}</button>)}
      {(q.type === 'single' || q.type === 'single_plus_structured') && q.options.map(o => <button key={o.id} className={'opt ' + (choice === o.id ? 'on' : '')} aria-pressed={choice === o.id} onClick={() => setVal(o.id)}>{o.label}</button>)}
      {q.type === 'single_plus_structured' && choice === q.options[0].id && <><label>Уточните (по желанию)</label><input value={free} onChange={x => setFree(x.target.value)} /></>}
      {q.type === 'structured_list' && <div className="card"><p className="mute" style={{ marginTop: 0 }}>Лекарства, БАД и другие средства. Если ничего не принимаете, нажмите «Далее».</p>
        {meds.length > 0 && <div className="p-list" style={{ boxShadow: 'none' }}>{meds.map((m, k) => <div className="p-row" key={k} style={{ minHeight: 56 }}><span className="bub"><Icon name="pill" size={20} /></span><span className="txt"><b>{m.name}</b>{m.dose && <small>{m.dose}</small>}</span></div>)}</div>}
        <div className="stack"><input placeholder="Название" id="mn" aria-label="Название" /><div className="row" style={{ flexWrap: 'nowrap' }}><input placeholder="Доза" id="md" aria-label="Доза" />
          <button className="sec" style={{ flex: 'none' }} onClick={() => { const n = document.getElementById('mn'), dd = document.getElementById('md'); if (n.value.trim()) { setVal([...meds, { name: n.value.trim(), dose: dd.value }]); n.value = ''; dd.value = '' } }}><Icon name="plus" size={18} />Добавить</button></div></div></div>}
      <Followups items={visibleFollowups(q, cur, fvals)} fv={fvals} setFv={setFv} />
      <Err e={e} />
    </div>
    <Actions>{idx > 0 && <button className="sec" onClick={() => { setVal(null); setFv(null); setI(idx - 1) }}><Icon name="left" size={18} />Назад</button>}<button disabled={!ok} onClick={next}>Далее<Icon name="arrowRight" size={18} /></button></Actions>
  </>
}

function Scale({ sid }) {
  const [s, err] = useLoad(() => get('/api/patient/scales/' + sid), [sid])
  const [ans, setAns] = useState({}), [k, setK] = useState(0), [res, setRes] = useState(null), [e, setE] = useState(null)
  if (err) return <><FlowTop title="Опросник" /><div className="wrap"><Err e={err} /><a href="#/p">Назад</a></div></>
  if (!s) return <><FlowTop title="Опросник" /><div className="wrap"><Loading rows={5} /></div></>
  if (res) return <><FlowTop title={s.title} /><div className="wrap"><Support s={res.support} />
    {res.result ? <div className="flow-done"><span className="big-ico"><Icon name="checkCircle" size={36} /></span><h2>{res.result.title}</h2>{res.result.body.map((b, i) => <p key={i} className="mute">{b}</p>)}
      <div className="card result-card"><h3>{res.result.next_steps_title}</h3><ul>{res.result.next_steps.map((n, i) => <li key={i}>{n}</li>)}</ul></div><p>{res.result.closing}</p></div>
      : <div className="flow-done"><span className="big-ico"><Icon name="check" size={34} /></span><p>{res.note}</p></div>}</div>
    <Actions><a className="primary" href={res.safety_followup_needed ? '#/p/safety' : '#/p'}><button className="block">Дальше</button></a></Actions></>
  const it = s.items[k], opts = it.answers || s.answers || [], saved = { ...s.saved, ...ans }
  const pick = v => { setAns({ ...ans, [it.id]: v }); if (k + 1 < s.items.length) setTimeout(() => { setK(k + 1); window.scrollTo(0, 0) }, 260) }
  const submit = async (finish) => { setE(null); try { setRes(await post('/api/patient/scales/' + sid, { answers: ans, finish })); window.scrollTo(0, 0) } catch (x) { setE(x.message) } }
  return <>
    <FlowTop title={s.title} sub={`${k + 1} из ${s.items.length}`} i={k + 1} n={s.items.length} />
    <div className="wrap">
      <div className="flow-q">{s.stem && <p className="stem">{s.stem}</p>}<h2>{it.text}</h2></div>
      {opts.map(o => <button key={o.value} className={'opt ' + (saved[it.id] === o.value ? 'on' : '')} aria-pressed={saved[it.id] === o.value} onClick={() => pick(o.value)}>{o.label}</button>)}
      <Err e={e} />
      <div className="flow-later"><button className="link" onClick={() => submit(false)}>Продолжить позже</button></div>
    </div>
    <Actions>{k > 0 && <button className="sec" onClick={() => setK(k - 1)}><Icon name="left" size={18} />Назад</button>}
      {k + 1 < s.items.length ? <button disabled={saved[it.id] == null} onClick={() => { setK(k + 1); window.scrollTo(0, 0) }}>Далее<Icon name="arrowRight" size={18} /></button> : <button disabled={saved[it.id] == null} onClick={() => submit(true)}>Готово<Icon name="check" size={18} /></button>}</Actions>
  </>
}

function Safety() {
  const [d] = useLoad(() => get('/api/patient/safety-followup'), []), [a, setA] = useState({}), [k, setK] = useState(0), [days, setDays] = useState(''), [res, setRes] = useState(null), [e, setE] = useState(null)
  if (!d) return <><FlowTop title="Несколько вопросов" /><div className="wrap"><Loading rows={4} /></div></>
  if (res) return <><FlowTop title="Несколько вопросов" /><div className="wrap"><Support s={res.support} /><div className="flow-done"><span className="big-ico"><Icon name="heart" size={34} /></span><p>Спасибо, что ответили. Ваши ответы получит врач.</p></div></div>
    <Actions><a className="primary" href="#/p"><button className="block">На главную</button></a></Actions></>
  const q = d.questions[k], last = k + 1 === d.questions.length
  const send = async fin => { setE(null); try { setRes(await post('/api/patient/safety-followup', { answers: a, finished: fin, sf6_days_ago: days === '' ? null : Number(days) })); window.scrollTo(0, 0) } catch (x) { setE(x.message) } }
  return <>
    <FlowTop title="Несколько вопросов" sub={`Вопрос ${k + 1} из ${d.questions.length}`} i={k + 1} n={d.questions.length} />
    <div className="wrap">
      <div className="flow-q"><p className="stem">Эти вопросы помогут врачу понять, как вам помочь.</p><h2>{q.text}</h2></div>
      {q.options.map(o => <button key={o.value} className={'opt ' + (a[q.id] === o.value ? 'on' : '')} aria-pressed={a[q.id] === o.value} onClick={() => setA({ ...a, [q.id]: o.value })}>{o.label}</button>)}
      {q.id === 'sf6' && a.sf6 === 'yes' && <><label>Сколько дней назад это было?</label><input type="number" min="0" value={days} onChange={x => setDays(x.target.value)} /></>}
      <Err e={e} />
      <div className="flow-later"><button className="link" onClick={() => send(false)}>Остановиться</button></div>
    </div>
    <Actions>{k > 0 && <button className="sec" onClick={() => setK(k - 1)}><Icon name="left" size={18} />Назад</button>}
      {last ? <button disabled={!a[q.id]} onClick={() => send(true)}>Готово<Icon name="check" size={18} /></button> : <button disabled={!a[q.id]} onClick={() => { setK(k + 1); window.scrollTo(0, 0) }}>Далее<Icon name="arrowRight" size={18} /></button>}</Actions>
  </>
}

function Checkin() {
  const [d, err] = useLoad(() => get('/api/patient/checkin'), []), [a, setA] = useState({}), [res, setRes] = useState(null), [e, setE] = useState(null)
  if (err) return <><FlowTop title="Самочувствие" /><div className="wrap"><Err e={err} /><a href="#/p">Назад</a></div></>
  if (!d) return <><FlowTop title="Самочувствие" /><div className="wrap"><Loading rows={3} /><Loading rows={3} /></div></>
  if (res) return <><FlowTop title="Самочувствие" /><div className="wrap"><Support s={res.support} />{res.note && <p className="banner b-info">{res.note}</p>}
    <div className="flow-done"><span className="big-ico"><Icon name="checkCircle" size={36} /></span><h2>Спасибо!</h2></div></div>
    <Actions><a className="primary" href={res.safety_followup_needed ? '#/p/safety' : '#/p'}><button className="block">Дальше</button></a></Actions></>
  const v = { ...d.saved, ...a }
  const send = async fin => { setE(null); try { setRes(await post('/api/patient/checkin', { answers: a, finish: fin })); window.scrollTo(0, 0) } catch (x) { setE(x.message) } }
  return <>
    <FlowTop title="Самочувствие сегодня" sub={new Date().toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })} />
    <div className="wrap">
      <div className="flow-q"><h2>Как вы сегодня?</h2><p className="flow-hint">Это дневник самонаблюдения, не тест. Можно пропустить день.</p></div>
      {d.questions.map(q => {
        if (q.type === 'scale') {
          const min = q.min ?? 0, max = q.max ?? 10, val = v[q.id], pct = val == null ? 0 : Math.round(100 * (val - min) / ((max - min) || 1))
          return <div className="card ci-q" key={q.id}><h3>{q.text}</h3>
            <div className={'ci-val' + (val == null ? ' none' : '')}>{val == null ? <b>не выбрано</b> : <><b>{val}</b><span>из {max}</span></>}</div>
            <input type="range" className={val == null ? 'unset' : ''} min={min} max={max} value={val ?? min} style={{ '--v': pct + '%' }} onChange={x => setA({ ...a, [q.id]: Number(x.target.value) })} aria-label={q.text} />
            <div className="ci-ends"><span>{q.min_label}</span><span>{q.max_label}</span></div>
            {val == null && <div style={{ textAlign: 'center' }}><button className="link" onClick={() => setA({ ...a, [q.id]: min })}>выбрать {min}</button></div>}</div>
        }
        return <div className="card ci-q" key={q.id}><h3>{q.text}</h3><div className="chips">{q.options.map(o => <button key={o} className={'chip' + (v[q.id] === o ? ' on' : '')} aria-pressed={v[q.id] === o} onClick={() => setA({ ...a, [q.id]: o })}>{o}</button>)}</div></div>
      })}
      <Err e={e} />{d.unfinished_text && <p className="flow-hint" style={{ textAlign: 'center' }}>{d.unfinished_text}</p>}
    </div>
    <Actions two><button className="sec" onClick={() => send(false)}>Сохранить то, что отвечено</button><button onClick={() => send(true)}>Сохранить</button></Actions>
  </>
}

const PLAN_ICON = { early_signs: 'activity', what_helps: 'sparkle', people: 'users', contact_doctor: 'message', safe_place: 'home', emergency: 'phone' }
function Plan() {
  const [p, err, r] = useLoad(() => get('/api/patient/plan'), []), [ed, setEd] = useState({})
  if (err) return <div className="wrap"><Err e={err} /></div>
  if (!p) return <div className="wrap"><Loading rows={2} /><Loading rows={3} /><Loading rows={3} /></div>
  return <div className="wrap">
    <div className="hello"><span className="eyebrow">План действий</span><h1>Мой план на трудные моменты</h1><p>Составьте его вместе с врачом.</p></div>
    <div style={{ marginBottom: 14 }}><span className={'plan-state ' + (p.confirmed_by_doctor ? 'ok' : 'wait')}><Icon name={p.confirmed_by_doctor ? 'checkCircle' : 'clock'} size={18} />{p.confirmed_by_doctor ? 'Врач подтвердил план.' : 'Врач пока не подтвердил план.'}</span></div>
    {p.sections.map(s => <div className={'card plan-sec' + (s.id === 'emergency' ? ' em' : '')} key={s.id}><label htmlFor={s.id}><span className="bub"><Icon name={PLAN_ICON[s.id] || 'edit'} size={18} /></span>{s.label}</label>
      <textarea id={s.id} defaultValue={s.text} onChange={e => setEd({ ...ed, [s.id]: e.target.value })} placeholder="Запишите своими словами" /></div>)}
    <Busy cls="block" onClick={async () => { await put('/api/patient/plan', { sections: ed }); setEd({}); r(); toast('План сохранён') }} disabled={!Object.keys(ed).length}>Сохранить</Busy>
    {Object.keys(ed).length > 0 && <p className="flow-hint" style={{ textAlign: 'center' }}>Есть несохранённые изменения</p>}
  </div>
}

function Messages() {
  const [m, err, r] = useLoad(() => get('/api/patient/messages'), []), [t, setT] = useState('')
  return <div className="wrap">
    <div className="hello"><span className="eyebrow">Связь с врачом</span><h1>Сообщения врачу</h1></div>
    <div className="p-note"><Icon name="info" size={20} /><span>Это не для срочной помощи. Если нужна помощь прямо сейчас, позвоните <a href="tel:112">112</a> или <a href="tel:103">103</a>.</span></div>
    <Err e={err} />
    {!m && !err && <Loading rows={2} />}
    {m && m.length === 0 && <div className="chat-empty"><span className="bub"><Icon name="message" size={26} /></span><b>Сообщений пока нет</b><div className="small">Напишите врачу, если хотите что-то уточнить</div></div>}
    {m && m.length > 0 && <div className="chat">{m.map(x => <div key={x.id} className={'bubble ' + (x.mine ? 'out' : 'in')}>{x.kind === 'appointment_request' && <div className="xs" style={{ fontWeight: 700, marginBottom: 2 }}>Запрос приёма</div>}{x.body}
      <span className="b-meta">{x.mine ? 'вы' : 'врач'}{x.ts ? ' · ' + fmt(x.ts) : ''}</span></div>)}</div>}
    <div className="composer"><textarea value={t} onChange={e => setT(e.target.value)} aria-label="Сообщение" placeholder="Напишите сообщение" />
      <div className="row"><span className="grow" /><Busy onClick={async () => { await post('/api/patient/messages', { body: t }); setT(''); r(); toast('Сообщение отправлено') }} disabled={!t.trim()}><Icon name="send" size={18} />Отправить</Busy></div></div>
    <div style={{ marginTop: 12 }}><Busy cls="sec block" onClick={async () => { await post('/api/patient/appointment-request', { body: t || 'Прошу записать на приём' }); setT(''); r(); toast('Запрос приёма отправлен') }}><Icon name="calendar" size={18} />Запросить приём</Busy></div>
  </div>
}

function Trend() {
  const [tr, err] = useLoad(() => get('/api/patient/trend', { cache: 'no-cache' }), [])
  return <div className="wrap">
    <div className="hello"><span className="eyebrow">Самонаблюдение</span><h1>Динамика</h1><p>Как меняется самочувствие по вашим ответам — простыми словами, без баллов.</p></div>
    <GoalCard />
    <Err e={err} />
    {!tr && !err && <Loading rows={3} />}
    {tr && (tr.message ? <div className="card"><div className="p-trend"><span className="bub"><Icon name="trend" size={22} /></span><div><h3 style={{ marginBottom: 6 }}>По вашим последним ответам</h3><p>{tr.message}</p></div></div></div>
      : <div className="card"><div className="empty"><span className="empty-ico"><Icon name="trend" size={22} /></span><strong>Пока мало данных</strong><span className="mute">Описание динамики появится после повторного заполнения опросника.</span></div></div>)}
    {tr && <div className="p-list"><div className="p-row"><span className="bub"><Icon name="list" size={22} /></span><span className="txt"><b>Заполнений опросника PHQ-9</b><small>по ним описывается динамика</small></span><b style={{ fontSize: '1.3rem' }}>{tr.points_count}</b></div></div>}
    <Steps />
    <MedDetails />
    <div className="p-note"><Icon name="info" size={20} /><span>Подробные результаты видит ваш врач.</span></div>
  </div>
}

function Profile() {
  const [me] = useLoad(() => get('/api/auth/me'), [])
  const pid = me && me.patient_id ? 'KK-' + String(me.patient_id).padStart(6, '0') : null
  return <div className="wrap">
    <div className="p-profile-head"><Avatar text={(me && me.name) || session.name || 'Я'} size={80} /><h2 style={{ margin: 0 }}>{(me && me.name) || session.name || 'Профиль'}</h2><span className="mute small">Кабинет пациента</span>{pid && <span className="pid-chip" title="Личный номер пациента">ID {pid}</span>}</div>
    <div className="p-list">
      <a className="p-row" href="#/p/intake"><span className="bub"><Icon name="clipboard" size={22} /></span><span className="txt"><b>Моя анкета</b><small>первичная анкета и ваши ответы</small></span><Icon name="right" className="chev" /></a>
      <a className="p-row" href="#/p/methods"><span className="bub"><Icon name="list" size={22} /></span><span className="txt"><b>Опросники</b></span><Icon name="right" className="chev" /></a>
      <a className="p-row" href="#/p/plan"><span className="bub"><Icon name="shield" size={22} /></span><span className="txt"><b>Мой план на трудные моменты</b></span><Icon name="right" className="chev" /></a>
      <a className="p-row" href="#/p/messages"><span className="bub"><Icon name="message" size={22} /></span><span className="txt"><b>Сообщения врачу</b></span><Icon name="right" className="chev" /></a>
    </div>
    <div className="p-section">Если нужна помощь прямо сейчас</div>
    <div className="p-list">
      <a className="p-row" href="tel:112"><span className="bub sup"><Icon name="phone" size={22} /></span><span className="txt"><b>Позвонить 112</b></span></a>
      <a className="p-row" href="tel:103"><span className="bub sup"><Icon name="phone" size={22} /></span><span className="txt"><b>Позвонить 103</b></span></a>
    </div>
    <Busy cls="sec block" onClick={logout}><Icon name="logout" size={18} />Выйти</Busy>
    <p className="p-disclaimer">Приложение не заменяет экстренную помощь</p>
  </div>
}

export function PatientApp({ sub }) {
  const [a, b] = sub
  if (a === 'intake') return <Intake />
  if (a === 'scale') return <Scale sid={b} />
  if (a === 'safety') return <Safety />
  if (a === 'checkin') return <Checkin />
  if (a === 'plan') return <Plan />
  if (a === 'methods') return <Methods />
  if (a === 'messages') return <Messages />
  if (a === 'trend') return <Trend />
  if (a === 'profile') return <Profile />
  return <Home />
}
