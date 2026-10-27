import React from 'react'

// Набор простых линейных иконок 24×24 (обводка = currentColor). Без внешних библиотек.
const P = {
  home: <><path d="M3.5 10.2 12 3.5l8.5 6.7V19a1.5 1.5 0 0 1-1.5 1.5h-4.2v-6h-5.6v6H5A1.5 1.5 0 0 1 3.5 19z" /></>,
  users: <><circle cx="9" cy="8.2" r="3.4" /><path d="M2.8 20c.8-3.5 3.3-5.6 6.2-5.6s5.4 2.1 6.2 5.6" /><circle cx="17.2" cy="9" r="2.6" /><path d="M16.6 14.5c2.3.2 4 1.9 4.7 4.9" /></>,
  bell: <><path d="M6.2 9.5a5.8 5.8 0 0 1 11.6 0c0 4.8 2 6.4 2 6.4H4.2s2-1.6 2-6.4z" /><path d="M10 19.5a2.1 2.1 0 0 0 4 0" /></>,
  book: <><path d="M4.5 18.8V5.6A2.1 2.1 0 0 1 6.6 3.5H19.5v13.3H6.6a2.1 2.1 0 0 0-2.1 2z" /><path d="M4.5 18.8a2 2 0 0 0 2.1 1.7H19.5" /></>,
  clipboard: <><rect x="5" y="4.5" width="14" height="16" rx="2" /><path d="M9 4.5V3.6c0-.3.3-.6.6-.6h4.8c.3 0 .6.3.6.6v.9" /><path d="m8.8 12.2 2.1 2.1 4.3-4.4" /></>,
  inbox: <><path d="M3.5 13.2 6 5.5h12l2.5 7.7V19a1.5 1.5 0 0 1-1.5 1.5H5A1.5 1.5 0 0 1 3.5 19z" /><path d="M3.5 13.2h5l1.4 2.4h4.2l1.4-2.4h5" /></>,
  sliders: <><path d="M4 6.5h9.5M18.5 6.5H20M4 12h3M11 12h9M4 17.5h11M19 17.5h1" /><circle cx="16" cy="6.5" r="2.2" /><circle cx="9" cy="12" r="2.2" /><circle cx="17" cy="17.5" r="2.2" /></>,
  logout: <><path d="M14.5 4.5h3A1.5 1.5 0 0 1 19 6v12a1.5 1.5 0 0 1-1.5 1.5h-3" /><path d="m9.5 16.5 4.5-4.5-4.5-4.5" /><path d="M14 12H4" /></>,
  plus: <><path d="M12 5v14M5 12h14" /></>,
  search: <><circle cx="11" cy="11" r="6.5" /><path d="m20 20-4.2-4.2" /></>,
  right: <><path d="m9.5 6 6 6-6 6" /></>,
  left: <><path d="m14.5 6-6 6 6 6" /></>,
  down: <><path d="m6 9.5 6 6 6-6" /></>,
  x: <><path d="M6.5 6.5l11 11M17.5 6.5l-11 11" /></>,
  phone: <><path d="M6.5 3.8h2.6c.4 0 .7.2.8.6l1.1 3.3c.1.4 0 .8-.3 1l-1.6 1.2a11.4 11.4 0 0 0 5 5l1.2-1.6c.2-.3.7-.4 1-.3l3.3 1.1c.4.1.6.4.6.8v2.6c0 .9-.8 1.7-1.7 1.6C10.5 19.4 4.6 13.5 4.9 5.5c0-.9.7-1.7 1.6-1.7z" /></>,
  heart: <><path d="M12 19.6s-7.2-4.4-8.6-9C2.5 7.3 4.6 4.6 7.4 4.6c1.9 0 3.2 1 4.6 2.8 1.4-1.8 2.7-2.8 4.6-2.8 2.8 0 4.9 2.7 4 6-1.4 4.6-8.6 9-8.6 9z" /></>,
  message: <><path d="M5 4.5h14A1.5 1.5 0 0 1 20.5 6v9A1.5 1.5 0 0 1 19 16.5h-8.2L6 20.2v-3.7H5A1.5 1.5 0 0 1 3.5 15V6A1.5 1.5 0 0 1 5 4.5z" /></>,
  trend: <><path d="M4 19.5h16" /><path d="m5 15 4-4.2 3 3 6.5-7" /><path d="M15 6.8h3.5v3.5" /></>,
  activity: <><path d="M3 12h4l2.6-6.5 4.8 13 2.6-6.5h4" /></>,
  shield: <><path d="M12 3.2 19.5 6v5.8c0 4.3-3.1 7.9-7.5 9-4.4-1.1-7.5-4.7-7.5-9V6z" /><path d="m9 12 2.1 2.1 4-4.2" /></>,
  check: <><path d="m5 12.5 4.5 4.5L19 7.5" /></>,
  checkCircle: <><circle cx="12" cy="12" r="8.5" /><path d="m8.3 12.3 2.6 2.6 4.9-5.4" /></>,
  clock: <><circle cx="12" cy="12" r="8.5" /><path d="M12 7.5V12l3 2" /></>,
  info: <><circle cx="12" cy="12" r="8.5" /><path d="M12 11v5.5" /><path d="M12 7.8v.2" /></>,
  alert: <><path d="M10.7 4.3 2.9 18a1.5 1.5 0 0 0 1.3 2.2h15.6a1.5 1.5 0 0 0 1.3-2.2L13.3 4.3a1.5 1.5 0 0 0-2.6 0z" /><path d="M12 9.5v4.2" /><path d="M12 16.8v.2" /></>,
  send: <><path d="m4.5 11.6 14.8-7c.5-.2 1 .3.8.8l-7 14.8c-.2.5-.9.4-1-.1l-1.5-5.6-5.6-1.5c-.5-.1-.6-.8-.1-1z" /><path d="m10.6 13.4 4.4-4.4" /></>,
  download: <><path d="M12 4v10.5" /><path d="m7.5 10 4.5 4.5 4.5-4.5" /><path d="M5 19.5h14" /></>,
  upload: <><path d="M12 19.5V9" /><path d="m7.5 13.5 4.5-4.5 4.5 4.5" /><path d="M5 4.5h14" /></>,
  refresh: <><path d="M19.5 11.5a7.5 7.5 0 1 0-2.2 5.5" /><path d="M19.5 4.5v7h-7" /></>,
  user: <><circle cx="12" cy="8" r="3.8" /><path d="M4.5 20.5c.9-3.9 3.9-6 7.5-6s6.6 2.1 7.5 6" /></>,
  calendar: <><rect x="3.5" y="5" width="17" height="15.5" rx="2" /><path d="M3.5 10h17M8 3v4M16 3v4" /></>,
  pill: <><path d="M10.3 19.9a4.6 4.6 0 0 1-6.5-6.5l6-6a4.6 4.6 0 0 1 6.5 6.5z" /><path d="m7.1 10.4 6.5 6.5" /></>,
  edit: <><path d="M4.5 19.5h3.8L19 8.8 15.2 5 4.5 15.7z" /><path d="m13.2 7 3.8 3.8" /></>,
  eye: <><path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z" /><circle cx="12" cy="12" r="2.8" /></>,
  eyeOff: <><path d="M2.5 12S6 5.5 12 5.5c1.6 0 3 .4 4.2 1M21.5 12s-3.5 6.5-9.5 6.5c-1.6 0-3-.4-4.2-1" /><path d="M9.9 9.9a2.8 2.8 0 0 0 4.2 4.2" /><path d="m4 4 16 16" /></>,
  lock: <><rect x="5" y="10.5" width="14" height="10" rx="2" /><path d="M8.3 10.5V8a3.7 3.7 0 0 1 7.4 0v2.5" /></>,
  arrowUp: <><path d="M12 19V5.5" /><path d="m6.5 11 5.5-5.5 5.5 5.5" /></>,
  arrowDown: <><path d="M12 5v13.5" /><path d="m6.5 13 5.5 5.5 5.5-5.5" /></>,
  arrowRight: <><path d="M5 12h13.5" /><path d="m13 6.5 5.5 5.5-5.5 5.5" /></>,
  minus: <><path d="M6 12h12" /></>,
  file: <><path d="M6.5 3.5h7l4 4v12a1 1 0 0 1-1 1h-10a1 1 0 0 1-1-1v-15a1 1 0 0 1 1-1z" /><path d="M13.5 3.5v4h4" /><path d="M8.8 13h6.4M8.8 16.5h4.2" /></>,
  list: <><path d="M9 6.5h11M9 12h11M9 17.5h11" /><path d="M4.5 6.5h.1M4.5 12h.1M4.5 17.5h.1" /></>,
  sparkle: <><path d="M12 4.5c.6 3.8 1.7 4.9 5.5 5.5-3.8.6-4.9 1.7-5.5 5.5-.6-3.8-1.7-4.9-5.5-5.5 3.8-.6 4.9-1.7 5.5-5.5z" /><path d="M18.5 15.5c.3 1.6.8 2.1 2.4 2.4-1.6.3-2.1.8-2.4 2.4-.3-1.6-.8-2.1-2.4-2.4 1.6-.3 2.1-.8 2.4-2.4z" /></>,
  hand: <><path d="M8 12.5V6.8a1.4 1.4 0 0 1 2.8 0v4.7M10.8 11V5.4a1.4 1.4 0 0 1 2.8 0v5.6M13.6 11V6.6a1.4 1.4 0 0 1 2.8 0v6.2" /><path d="M16.4 10.4a1.4 1.4 0 0 1 2.8 0v3.4c0 3.7-2.8 6.7-6.5 6.7h-.6c-2.2 0-3.6-.9-4.9-2.5l-2.7-3.4a1.5 1.5 0 0 1 2.2-2l1.3 1.3" /></>,
  compass: <><circle cx="12" cy="12" r="8.5" /><path d="m15.4 8.6-2.1 4.7-4.7 2.1 2.1-4.7z" fill="currentColor" stroke="none" /></>,
  filter: <><path d="M4 5.5h16l-6.2 7.3v5.7l-3.6 1.8v-7.5z" /></>,
  external: <><path d="M13.5 4.5h6v6" /><path d="m19.5 4.5-8 8" /><path d="M17.5 13.5v5a1 1 0 0 1-1 1h-11a1 1 0 0 1-1-1v-11a1 1 0 0 1 1-1h5" /></>,
}

export default function Icon({ name, size = 20, stroke = 1.8, className, style, title }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round"
    className={'ico' + (className ? ' ' + className : '')} style={style} aria-hidden={title ? undefined : 'true'} role={title ? 'img' : undefined} focusable="false">
    {title ? <title>{title}</title> : null}{P[name] || P.info}</svg>
}

// Знак продукта: стрелка компаса в скруглённом квадрате.
export function Mark({ size = 32 }) {
  return <span className="mark" style={{ width: size, height: size, borderRadius: Math.round(size * 0.3) }} aria-hidden="true">
    <svg width={Math.round(size * 0.62)} height={Math.round(size * 0.62)} viewBox="0 0 24 24" fill="none">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity=".55" strokeWidth="1.6" />
      <path d="M16.2 7.8 13.3 13.3 7.8 16.2 10.7 10.7z" fill="currentColor" />
      <circle cx="12" cy="12" r="1.2" fill="var(--mark-bg, #0F4B4F)" />
    </svg></span>
}
