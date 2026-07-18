// 财新周刊正文提取器(平台通用):在已渲染的 文章URL?p0 页面上执行。
// 用法:page.evaluate(EXTRACT_JS) / WebBridge evaluate / 任意可执行 JS 的浏览器控制通道。
// 返回 JSON 字符串:{url,title,len,body,lead} — body 中图片已原地转为 ![](src) 文本。
(() => {
  const box = document.querySelector('#the_content');
  const mob = document.querySelector('#cons');           // 移动版 /m/ 页面容器
  const root = box ? (box.querySelector('.content') || box) : mob;
  if (!root) return JSON.stringify({url: location.href, error: 'no_content_root'});
  const h1 = document.querySelector('h1') || (mob ? mob.querySelector('h1') : null);
  const title = h1 ? h1.innerText.trim().replace(/\s+/g, ' ') : document.title;
  const c = root.cloneNode(true);
  c.querySelectorAll('script,style,noscript,iframe,form,button,select,.page,.content-tag,.moreReport,.idetor,.lanmu_textend,.mask')
    .forEach(e => e.remove());
  c.querySelectorAll('img').forEach(im => {
    const s = (im.src || im.getAttribute('data-src') || '').trim();
    if (s.startsWith('http')) {
      im.replaceWith(document.createTextNode('\n![](' + s + ')\n'));
    } else { im.remove(); }
  });
  document.body.appendChild(c);          // innerText 需要渲染态
  let txt = c.innerText || '';
  c.remove();
  txt = txt.replace(/\r/g, '').replace(/[ \t\u00a0]+/g, ' ').replace(/\n{3,}/g, '\n\n').trim();
  let lead = '';
  if (box) {
    const first = box.querySelector(':scope > div');
    lead = first && first !== root ? (first.innerText || '').trim() : '';
  }
  return JSON.stringify({url: location.href, title: title, len: txt.length, body: txt, lead: lead});
})()
