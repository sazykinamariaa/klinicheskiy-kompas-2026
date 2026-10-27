import React, { useEffect, useState } from 'react'
import { Icon, toDate } from './common.jsx'

const two = n => String(n).padStart(2, '0')
export function fmtLeft(ms) { const s = Math.floor(Math.abs(ms) / 1000), h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60; return h > 0 ? h + ' ч ' + two(m) + ' мин' : m + ':' + two(sec) }

export function SlaTimer({ due, level, compact }) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])

  if (!due) return null

  const left = toDate(due).getTime() - now
  const over = left < 0

  const cls = 'sla' + (over ? ' over' : '') + (over && level === 'red' ? ' hot' : '') + (compact ? ' compact' : '')

  return <span className={cls} role="timer" aria-live="off" title={over ? 'Срок реакции истёк: алерт уже эскалирован или будет эскалирован' : 'Время до эскалации дежурному'}><Icon name={over ? 'alert' : 'clock'} size={compact ? 14 : 16} stroke={2} />{over ? 'просрочено на ' + fmtLeft(left) : 'до эскалации ' + fmtLeft(left)}</span>
}