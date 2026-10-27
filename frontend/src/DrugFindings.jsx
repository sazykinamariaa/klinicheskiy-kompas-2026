import React from 'react'
import { Icon } from './common.jsx'

export default function DrugFindings({ d }) {
  const ci = d.contraindications || []
  const ix = d.interactions || []
  
  if (!ci.length && !ix.length) return null

  return <div className="dfind">
    {ci.map(c => <div key={'c' + c.id} className="dfind-i red"><span className="dfind-lvl">Противопоказание</span><span className="dfind-t">{c.text}</span><span className="dfind-src"><Icon name="book" size={14} />ОХЛП, раздел {c.ohlp_section || '4.3'}</span></div>)}
    {ix.map((h, i) => <div key={'x' + i} className={'dfind-i ' + (h.level === 'red' ? 'red' : 'yellow')}><span className="dfind-lvl">{h.level === 'red' ? 'Противопоказанное сочетание' : 'Осторожность'}</span><span className="dfind-t"><b>{h.title || h.with_class}</b> — {h.med}</span><span className="dfind-src"><Icon name="book" size={14} />ОХЛП, раздел {h.ohlp_section || '4.5'}{h.level !== 'red' ? ' · нужно решение врача' : ''}</span></div>)}
  </div>
}