// Демо: новый пациент открывает ссылку-приглашение (/invite/DEMO-2026) и впервые регистрируется — без телефона, SMS и внешних сервисов.
import React, { useState } from 'react'
import { get, post, setToken, session } from './api.js'
import { useLoad, Err, go, Icon, Loading, Busy, fmt } from './common.jsx'

const NAME = /^[А-ЯЁA-Z][а-яёa-z]+(-[А-ЯЁA-Z]?[а-яёa-z]+)?$/

// Те же правила, что на сервере (backend/app/routers/demo_invite.py → validate)
export function validate(f) {
  const e = {}
  const parts = f.full_name.trim().split(/\s+/).filter(Boolean)
  if (parts.length < 2) e.full_name = 'Укажите фамилию и имя (отчество — если есть)'
  else if (parts.length > 4 || !parts.every(x => NAME.test(x))) e.full_name = 'ФИО пишется буквами, каждое слово с заглавной, например: Соколова Анна Сергеевна'
  if (!/^\d{4}-\d{2}-\d{2}$/.test(f.birth_date)) e.birth_date = 'Укажите дату рождения'
  else {
    const b = new Date(f.birth_date + 'T00:00:00'), t = new Date()
    let age = t.getFullYear() - b.getFullYear()
    if (t.getMonth() < b.getMonth() || (t.getMonth() === b.getMonth() && t.getDate() < b.getDate())) age--
    if (isNaN(b)) e.birth_date = 'Укажите дату рождения'
    else if (b > t) e.birth_date = 'Дата рождения не может быть в будущем'
    else if (age < 18) e.birth_date = 'Приложение предназначено для взрослых: с 18 лет'
    else if (age > 110) e.birth_date = 'Проверьте год рождения'
  }
  if (f.password.length < 8) e.password = 'Пароль — не короче 8 символов'
  else if (!/[A-Za-zА-Яа-яЁё]/.test(f.password) || !/\d/.test(f.password)) e.password = 'В пароле нужны хотя бы одна буква и одна цифра'
  else if (f.password !== f.password2) e.password2 = 'Пароли не совпадают'
  if (!f.consent) e.consent = 'Без согласия на обработку персональных данных продолжить нельзя'
  return e
}

const FieldErr = ({ m, id }) => m ? <p className="err small" id={id} role="alert">{m}</p> : null

export function Invite({ token }) {
  const [k, setK] = useState(0)
  const [info, err] = useLoad(() => get('/api/public/demo-invite/' + token), [token, k])
  const [f, setF] = useState(null)
  const [fe, setFe] = useState({})
  const [e, setE] = useState(null)
  const [done, setDone] = useState(null)

  const resetDemo = async () => {
    await post('/api/public/demo-invite/' + token + '/reset')
    setToken(null); session.role = null; setDone(null); setF(null); setFe({}); setE(null); setK(k + 1)
  }

  const submit = async f => {
    setE(null)
    const v = validate(f)
    setFe(v)
    if (Object.keys(v).length) return
    try {
      const r = await post('/api/public/demo-invite/' + token + '/register', { full_name: f.full_name.trim().replace(/\s+/g, ' '), birth_date: f.birth_date, password: f.password, consent: f.consent })
      setToken(r.token); session.role = 'patient'; session.name = r.name
      setDone(r)
    } catch (x) {
      try { const d = JSON.parse(x.message); setFe(d.fields || {}); setE(d.message) } catch { setE(x.message) }
    }
  }

  if (err) return <div className="wrap"><div className="hello"><h1>Приглашение</h1></div><Err e={err} /><p><a href="#/login">Ко входу</a></p></div>
  if (!info) return <div className="wrap"><Loading rows={3} /><Loading rows={2} /></div>

  if (done) return <div className="wrap">
    <div className="flow-done"><span className="big-ico"><Icon name="checkCircle" size={36} /></span><h2>Добро пожаловать, {done.first_name}!</h2>
      <p className="mute">Регистрация завершена. Клиника: {done.clinic}, ваш врач — {done.doctor}.</p></div>
    <div className="card">
      <h3>Что дальше</h3>
      <ol className="inv-steps">
        <li><b>Заполните анкету</b> — около 10 минут, можно с перерывами. Ответы увидит только ваш врач.</li>
        <li><b>Пройдите короткие опросники</b> о настроении и тревоге — приложение предложит их после анкеты.</li>
        <li><b>Врач посмотрит ответы</b> и свяжется с вами, чтобы обсудить следующий шаг.</li>
      </ol>
      <p className="small mute">Пока здесь пусто: диагнозов, приёмов и назначений нет — история появится по мере работы с врачом.</p>
    </div>
    <div className="card"><h3>Данные для входа</h3><p className="small mute">Сохраните их, чтобы войти снова с другого устройства.</p>
      <dl className="kv"><dt>Логин</dt><dd><b>{done.login}</b></dd><dt>Пароль</dt><dd>тот, который вы придумали</dd></dl></div>
    <button className="block" onClick={() => go('#/p')}>Перейти в приложение<Icon name="arrowRight" size={18} /></button>
  </div>

  if (info.used) return <div className="wrap">
    <div className="hello"><span className="eyebrow">Приглашение · {info.clinic}</span><h1>Ссылка уже использована</h1>
      <p>По этому приглашению пациент уже зарегистрировался{info.used_at ? ' ' + fmt(info.used_at) : ''}. Повторная регистрация по той же ссылке не создаёт новую карточку.</p></div>
    <div className="card join-actions">
      <button className="block" onClick={() => go('#/login')}><Icon name="arrowRight" size={18} />Войти с логином и паролем</button>
      <p className="small mute">Если это вы — войдите со своим логином и паролем. Если нужна новая ссылка — попросите врача.</p>
    </div>
    <div className="card inv-demo"><h3>Демонстрация</h3><p className="small mute">Чтобы показать сценарий заново, сбросьте демо: зарегистрированный по ссылке пациент будет удалён, ссылка снова станет новой.</p>
      <Busy cls="sec" onClick={resetDemo}>Сбросить демо</Busy></div>
  </div>

  const v = f || { full_name: info.prefill.full_name, birth_date: '', password: '', password2: '', consent: false }
  const set = (key, val) => { setF({ ...v, [key]: val }); if (fe[key]) setFe({ ...fe, [key]: undefined }) }

  return <div className="wrap">
    <div className="hello"><span className="eyebrow">Приглашение · {info.clinic}</span><h1>Здравствуйте!</h1>
      <p>{info.clinic} приглашает вас в приложение «Клинический компас». Ваш врач — {info.doctor}. Регистрация займёт пару минут и проходит прямо в браузере: телефон и SMS не нужны.</p></div>
    <form className="card inv-form" noValidate onSubmit={x => { x.preventDefault(); submit(v) }}>
      <label htmlFor="if">ФИО</label>
      <input id="if" value={v.full_name} onChange={x => set('full_name', x.target.value)} autoComplete="name" aria-invalid={!!fe.full_name} aria-describedby="if-e" />
      <p className="xs mute">Подставлено из приглашения — проверьте и при необходимости исправьте.</p>
      <FieldErr m={fe.full_name} id="if-e" />
      <label htmlFor="ib">Дата рождения</label>
      <input id="ib" type="date" value={v.birth_date} onChange={x => set('birth_date', x.target.value)} autoComplete="bday" aria-invalid={!!fe.birth_date} aria-describedby="ib-e" />
      <FieldErr m={fe.birth_date} id="ib-e" />
      <label htmlFor="ip">Придумайте пароль</label>
      <input id="ip" type="password" value={v.password} onChange={x => set('password', x.target.value)} autoComplete="new-password" aria-invalid={!!fe.password} aria-describedby="ip-e" />
      <p className="xs mute">Не короче 8 символов, хотя бы одна буква и одна цифра.</p>
      <FieldErr m={fe.password} id="ip-e" />
      <label htmlFor="ip2">Повторите пароль</label>
      <input id="ip2" type="password" value={v.password2} onChange={x => set('password2', x.target.value)} autoComplete="new-password" aria-invalid={!!fe.password2} aria-describedby="ip2-e" />
      <FieldErr m={fe.password2} id="ip2-e" />
      <div className="consent-box">
        <p className="small mute">{info.consent_text_status}</p>
        <label className="consent-check"><input type="checkbox" checked={v.consent} onChange={x => set('consent', x.target.checked)} /> <span>Я даю согласие на обработку моих персональных данных (152-ФЗ) для ведения лечения у моего врача</span></label>
        <FieldErr m={fe.consent} id="ic-e" />
      </div>
      <Err e={e} />
      <button type="submit" className="block"><Icon name="check" size={18} />Зарегистрироваться</button>
    </form>
    <div className="card"><div className="p-trend"><span className="bub"><Icon name="lock" size={22} /></span><div><h3>Ваши данные</h3><p>{info.privacy}</p></div></div></div>
  </div>
}
