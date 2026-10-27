import React, { useState, useEffect } from 'react'
import Icon from './Icon.jsx'

const TABS = [['#/p', 'home', 'Главная'], ['#/p/trend', 'trend', 'Динамика'], ['#/p/methods', 'list', 'Опросники'], ['#/p/messages', 'message', 'Сообщения']]

export default function PatientNav() {
  const [hash, setHash] = useState(window.location.hash || '#/p')
  useEffect(() => {
    const f = () => setHash(window.location.hash)
    window.addEventListener('hashchange', f)
    return () => window.removeEventListener('hashchange', f)
  }, [])
  const cur = hash === '#/p/' || hash === '' ? '#/p' : hash
  return <nav className="tabbar" aria-label="Основная навигация">
    {TABS.map(([href, ic, label]) => {
      const on = cur === href
      return <a key={href} className={'tab' + (on ? ' active' : '')} href={href} aria-current={on ? 'page' : undefined}>
        <span className="t-ico"><Icon name={ic} size={22} stroke={on ? 2.1 : 1.8} /></span>{label}</a>
    })}
  </nav>
}
