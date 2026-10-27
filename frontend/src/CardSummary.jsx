import React from 'react'
import { Icon, LEVEL } from './common.jsx'

export default function CardSummary({ c }) {
  const red = c.alerts.filter(a => a.level === 'red').length
  const lv = (c.level && LEVEL[c.level]) ? LEVEL[c.level][0] : '—'
  const ch = Object.values(c.dynamics.series).filter(s => s.previous != null).map(s => s.title + ' ' + (s.latest - s.previous > 0 ? '+' : '') + (s.latest - s.previous) + ' (было ' + s.previous + ', стало ' + s.latest + ')')
  const must = c.proposals.filter(p => p.kind === 'routing' && p.payload.kind === 'mandatory').length
  const done = []
  if (c.orders.length) done.push('назначений: ' + c.orders.length)
  if (c.referrals.length) done.push('направлений: ' + c.referrals.length)
  const acc = c.alerts.filter(a => a.accepted).length
  if (acc) done.push('сигналов принято: ' + acc)

  const items = [
    ['alert', 'Риск', red ? lv + ' · критических сигналов: ' + red : lv],
    ['trend', 'Что изменилось', ch.length ? ch.join('; ') : 'нет повторных измерений'],
    ['clipboard', 'Что предлагается', c.proposals.length ? c.proposals.length + ' на решение' + (must ? ', из них обязательных: ' + must : '') : 'нет предложений'],
    ['checkCircle', 'Что уже сделано', done.length ? done.join(', ') : 'решений пока нет']
  ]

  return (
    <div className="csum">
      {items.map(([ic, h, t], i) => (
        <div key={h} className={'csum-i' + (i === 0 && c.level === 'red' ? ' hot' : '')}>
          <span className="csum-ico"><Icon name={ic} size={18} /></span>
          <div>
            <div className="csum-h">{h}</div>
            <div className="csum-t">{t}</div>
  </div>
        </div>
      ))}
    </div>
  )
}