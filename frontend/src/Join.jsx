import React, { useEffect, useState } from 'react'
import { get, post, setToken, session } from './api.js'
import { useLoad, Err, go, Icon, Loading } from './common.jsx'
import GoogleButton from './GoogleButton.jsx'

export function Join({ code }) {
  const [info, err] = useLoad(() => get('/api/public/invitation/' + code), [code])
  const [cfg, setCfg] = useState(null)
  useEffect(() => { get('/api/public/auth-config').then(setCfg).catch(() => setCfg({})) }, [])
  
  const [e, setE] = useState(null)
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(null)
  const [manual, setManual] = useState(false)
  const [agree, setAgree] = useState(false)  // 152-ФЗ: без галочки данные не сохраняются
  const [f, setF] = useState({ login: '', password: '' })

  const finish = r => { setToken(r.token); session.role = 'patient'; setDone(r) }

  const quick = async () => {
    setE(null)
    setBusy(true)
    try {
      const r = await post(`/api/public/invitation/${code}/accept-quick`, { consent: agree })
      finish(r)
    } catch (x) {
      setE(x.message)
    }
    setBusy(false)
  }

  const viaGoogle = async idToken => {
    setE(null)
    try {
      const r = await post(`/api/public/invitation/${code}/accept-google`, { consent: agree, id_token: idToken })
      finish(r)
    } catch (x) {
      setE(x.message)
    }
  }

  const viaPassword = async () => {
    setE(null)
    try {
      const r = await post(`/api/public/invitation/${code}/accept`, { consent: agree, login: f.login, password: f.password })
      finish({ ...r, public_id: 'KK-' + String(r.patient_id).padStart(6, '0') })
    } catch (x) {
      setE(x.message)
    }
  }

  if (err) return <div className="wrap"><div className="hello"><h1>Приглашение</h1></div><Err e={err} /><p><a href="#/login">Ко входу</a></p></div>
  if (done) return <div className="wrap"><div className="flow-done"><span className="big-ico"><Icon name="checkCircle" size={36} /></span><h2>Вы зарегистрированы</h2><p className="mute">Ваш личный номер пациента:</p><p className="pid">{done.public_id}</p></div>{done.password && <div className="card"><h3>Данные для входа</h3><p className="small mute">Сохраните их, чтобы войти снова с другого устройства.</p><dl className="kv"><dt>Логин</dt><dd><b>{done.login}</b></dd><dt>Пароль</dt><dd><b>{done.password}</b></dd></dl></div>}<button className="block" onClick={() => go('#/p')}>Продолжить<Icon name="arrowRight" size={18} /></button></div>

  if (!info) return <div className="wrap"><Loading rows={3} /><Loading rows={2} /></div>

  return <div className="wrap">
    <div className="hello"><span className="eyebrow">Приглашение от врача · код {code}</span><h1>Добро пожаловать</h1>{info.greeting.map((g, i) => <p key={i}>{g}</p>)}</div>
    <div className="card"><div className="p-trend"><span className="bub"><Icon name="lock" size={22} /></span><div><h3>Ваши данные</h3><p>{info.privacy}</p></div></div><p className="small mute">{info.consent_text_status}</p></div>
    <div className="card join-actions">
      <div className="consent-box">
      <p className="small mute">Текст согласия будет добавлен юристами</p>
      <label className="consent-check"><input type="checkbox" checked={agree} onChange={x => setAgree(x.target.checked)} /> <span>Я даю согласие на обработку моих персональных данных (152-ФЗ) для ведения лечения у моего врача</span></label>
      </div>
      <button className={'block' + (busy ? ' is-busy' : '')} disabled={busy || !agree} onClick={quick}><Icon name="check" size={18} />Согласен(-на), зарегистрироваться</button>
      {agree && cfg && cfg.google_client_id && <><div className="or"><span>или</span></div><GoogleButton clientId={cfg.google_client_id} onToken={viaGoogle} text="signup_with" /></>}
      <Err e={e} />
      <p style={{ textAlign: 'center' }}><button className="link" onClick={() => setManual(!manual)}>{manual ? 'Скрыть' : 'Придумать свой логин и пароль'} </button></p>
      {manual && <div><label htmlFor="jl">Логин</label><input id="jl" value={f.login} onChange={x => setF({ ...f, login: x.target.value })} autoComplete="username" autoCapitalize="none" /><label htmlFor="jp">Пароль (не короче 8 символов)</label><input id="jp" type="password" value={f.password} onChange={x => setF({ ...f, password: x.target.value })} autoComplete="new-password" /><button className="sec block" style={{ marginTop: 14 }} disabled={f.login.length < 3 || f.password.length < 8 || !agree} onClick={viaPassword}>Согласен(-на), зарегистрироваться с паролем</button></div>}
    </div>
    <div className="card" style={{ marginTop: 14 }}><h2>{info.why.title}</h2><p>{info.why.body}</p><ul>{info.why.bullets.map((b, i) => <li key={i}>{b}</li>)}</ul><p>{info.why.closing}</p></div>
</div>
}