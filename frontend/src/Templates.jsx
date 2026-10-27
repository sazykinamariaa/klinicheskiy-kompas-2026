import React from 'react'

export const TEMPLATES = [
  'Здравствуйте! Я получил(а) ваши ответы и свяжусь с вами сегодня.',
  'Пожалуйста, будьте на связи: я позвоню вам в ближайшее время.',
  'Предлагаю обсудить ваше самочувствие на приёме. Когда вам удобно?',
  'Спасибо, что отметили самочувствие. Если станет хуже, нажмите «Мне тяжело» или позвоните 112 / 103.',
]

export default function Templates({ onPick }) {
  return <div className="tpl" aria-label="Шаблоны сообщений">
    <span className="xs mute">Шаблоны:</span>
    {TEMPLATES.map((t, i) => <button key={i} type="button" className="tpl-b" onClick={() => onPick(t)} title={t}>{t.length > 42 ? t.slice(0, 40) + '…' : t}</button>)}
  </div>
}