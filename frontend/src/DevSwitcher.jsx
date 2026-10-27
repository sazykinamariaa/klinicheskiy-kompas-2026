import React, { useEffect, useState } from 'react'
import { get, post, setToken, session } from './api.js'
import { Icon, go } from './common.jsx'

const HOME = { doctor: '#/doctor', duty: '#/duty', psychiatrist: '#/psy', admin: '#/admin', patient: '#/p' }
const ROLE = { doctor: 'Врач', duty: 'Дежурный', psychiatrist: 'Психиатр', admin: 'Администратор', patient: 'Пациент' }

export default function DevSwitcher() {
  const [cfg, setCfg] = useState(null)
  const [open, setOpen] = useState(false)
  const [users, setUsers] = useState(null)
  const [err, setErr] = useState(null)

  useEffect(() => {
    get('/api/public/auth-config').then(setCfg).catch(() => setCfg({ dev_mode: false }))
  }, [])

  if (!cfg || !cfg.dev_mode) return null

  const toggle = () => {
    if (!users) {
      get('/api/dev/users').then(setUsers).catch(e => setErr(e.message))
    }
    setOpen(!open)
  }

  const pick = async (login) => {
    try {
      const r = await post('/api/dev/impersonate', { login })
      setToken(r.token)
      session.role = r.role
      session.name = r.name
      setOpen(false)
      go(HOME[r.role] || '#/login')
    } catch (e) {
      setErr(e.message)
    }
  }

  const groups = Object.keys(ROLE).map(role => [role, (users || []).filter(u => u.role === role)]).filter(([, list]) => list.length)

  return (
    <div className="dev-sw">
      {open && (
        <div className="dev-panel" role="dialog" aria-label="Переключение ролей">
          <div className="dev-head">
            <b>Режим разработки</b>
            <button className="ghost icon" onClick={() => setOpen(false)} aria-label="Закрыть">
              <Icon name="x" size={18} />
            </button>
          </div>
          <p className="xs mute">Войти под любым пользователем без пароля. Работает только при KK_DEV_MODE=1.</p>
          {err && <p className="err">{err}</p>}
          {!users && !err && <p className="small mute">Загрузка…</p>}
          {groups.map(([role, list]) => (
            <div key={role} className="dev-group">
              <div className="dev-role">{ROLE[role]}</div>
              {list.map(u => (
                <button key={u.login} className={'dev-user' + (session.name === u.name && session.role === u.role ? ' on' : '')} onClick={() => pick(u.login)}>
                  <span>{u.name}</span>
                  <small>{u.login}</small>
                </button>
              ))}
            </div>
          ))}
        </div>
      )}
      <button className="dev-fab" onClick={toggle} aria-expanded={open} title="Переключить роль">
        <Icon name="users" size={20} />
        <span>Роли</span>
      </button>
    </div>
  )
}