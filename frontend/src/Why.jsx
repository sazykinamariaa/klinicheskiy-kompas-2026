import React, { useState } from 'react'
import { Icon } from './common.jsx'

const VAL = v => v === true ? 'да' : v === false ? 'нет' : v == null ? 'неизвестно' : Array.isArray(v) ? v.join(', ') : typeof v === 'object' ? JSON.stringify(v) : String(v)
const STATUS = { confirmed: 'подтверждено', approved_by_physician: 'одобрено врачом', verify: 'нужна сверка', waiting: 'ждём данных' }

export default function Why({ ruleId, title, facts, basis, raw }) {
  const [open, setOpen] = useState(false)
  const [tech, setTech] = useState(false)

  const list = Object.entries(facts || {})

  return (
    <div className="why">
      <button className="why-btn" onClick={() => setOpen(!open)} aria-expanded={open}>
        <Icon name="info" size={16} stroke={2} />Почему?
      </button>
      {open && (
        <div className="why-box">
          <p className="why-line">
            <b>Правило {ruleId || '—'}</b>{title ? ': ' + title : ''}
          </p>
          {list.length > 0 ? (
            <>
              <p className="why-sub">Сработало, потому что в данных пациента:</p>
              <ul className="why-facts">
                {list.map(([k, v]) => (
                  <li key={k}>
                    <code>{k}</code> — <b>{VAL(v)}</b>
  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className="why-sub">Условие правила выполнено по данным анкеты и шкал.</p>
          )}
          {basis && (
            <p className="why-src">
              <Icon name="book" size={15} /> Источник: {basis.source || '—'}{basis.status ? ' · ' + (STATUS[basis.status] || basis.status) : ''}{basis.config ? ' · ' + basis.config : ''}
            </p>
          )}
          <p className="why-note">Система предлагает, решение принимает врач.</p>
          {raw && (
            <>
              <button className="link" onClick={() => setTech(!tech)}>
                {tech ? 'Скрыть технические данные' : 'Технические данные'}
              </button>
              {tech && <pre>{JSON.stringify(raw, null, 1)}</pre>}
            </>
          )}
        </div>
      )}
    </div>
  )
}