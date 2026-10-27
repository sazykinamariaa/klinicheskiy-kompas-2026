let token = null
try { token = sessionStorage.getItem('kk_token') } catch {}
export const session = { role: null, name: null }
// Адрес сервера: страница с сервера — тот же адрес; файл .html — http://127.0.0.1:8000 (другой адрес: ?server=http://192.168.1.10:8000)
const srv = new URLSearchParams(location.search).get('server')
export const BASE = (srv || window.KK_SERVER || (location.protocol === 'file:' ? 'http://127.0.0.1:8000' : '')).replace(/\/$/, '')
export const ORIGIN = BASE || location.origin
const NOSRV = 'Нет связи с сервером «Клинического компаса» (' + (BASE || location.host) + '). Запустите его двойным щелчком по «Запустить.command» в папке klinicheskiy-kompas и откройте этот файл в Safari или Chrome (не в окне предпросмотра).'
export function setToken(t) { token = t; try { t ? sessionStorage.setItem('kk_token', t) : sessionStorage.removeItem('kk_token') } catch {} }
export const hasToken = () => !!token
export async function api(method, url, body, raw) {
  let r
  try { r = await fetch(BASE + url, { method, headers: { ...(body ? { 'Content-Type': 'application/json' } : {}), ...(token ? { Authorization: 'Bearer ' + token } : {}) }, body: body ? JSON.stringify(body) : undefined }) }
  catch { throw new Error(NOSRV) }
  if (r.status === 401 && token) { setToken(null); location.hash = '#/login'; throw new Error('Сессия истекла, войдите снова') }
  if (r.status === 404 && url.startsWith('/api/auth/')) throw new Error(NOSRV)
  if (raw && r.ok) return r
  let j = null; try { j = await r.json() } catch {}
  if (!r.ok) { const d = j && j.detail; throw new Error(typeof d === 'string' ? d : d ? JSON.stringify(d) : 'Ошибка ' + r.status) }
  return j
}
export const get = u => api('GET', u), post = (u, b) => api('POST', u, b || {}), put = (u, b) => api('PUT', u, b || {})
export async function download(url, name) {
  const r = await api('GET', url, null, true); const b = await r.blob(); const a = document.createElement('a')
  a.href = URL.createObjectURL(b); a.download = name; a.click()
}
