import React, { useEffect, useRef, useState } from 'react'

let loading = null
function loadGis() {
  if (window.google && window.google.accounts && window.google.accounts.id) {
    return Promise.resolve()
  }
  if (!loading) {
    loading = new Promise((res, rej) => {
      const s = document.createElement('script')
      s.src = 'https://accounts.google.com/gsi/client'
      s.async = true
      s.onload = () => res()
      s.onerror = () => {
        loading = null
        rej(new Error('Не удалось загрузить вход Google'))
      }
      document.head.appendChild(s)
    })
  }
  return loading
}

export default function GoogleButton({ clientId, onToken, text = 'continue_with' }) {
  const box = useRef(null)
  const [err, setError] = useState(null)

  useEffect(() => {
    let on = true
    loadGis().then(() => {
      if (!on || !box.current) return
      window.google.accounts.id.initialize({
        client_id: clientId,
        callback: (r) => onToken(r.credential)
      })
      box.current.innerHTML = ''
      window.google.accounts.id.renderButton(box.current, {
        theme: 'outline',
        size: 'large',
        shape: 'pill',
        text,
        width: box.current.offsetWidth || 320,
        locale: 'ru'
      })
    }).catch(e => {
      if (on) setError(e.message)
    })

    return () => {
      on = false
    }
  }, [clientId])

  return (
    <div className="g-wrap">
      <div ref={box} className="g-btn" />
      {err && <p className="err">{err}</p>}
    </div>
  )
}