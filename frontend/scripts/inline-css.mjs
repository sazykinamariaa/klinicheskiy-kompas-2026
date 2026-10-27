// После сборки кладёт CSS прямо в index.html: странице не нужен отдельный запрос за стилями,
// поэтому она выглядит одинаково и по локальному адресу, и через туннель.
import fs from 'node:fs'
import path from 'node:path'
const dist = path.resolve('dist')
let html = fs.readFileSync(path.join(dist, 'index.html'), 'utf8')
html = html.replace(/<link rel="stylesheet"[^>]*href="\/(assets\/[^"]+\.css)"[^>]*>/g, (_, href) => {
  const css = fs.readFileSync(path.join(dist, href), 'utf8')
  return '<style>' + css + '</style>'
})
fs.writeFileSync(path.join(dist, 'index.html'), html)
console.log('CSS встроен в index.html')
