// 正文加载稳定性轮询:跳转 location.href 后循环执行,直到返回的长度连续 4 次不变
// 且距跳转 ≥10 秒(正文异步注入,固定 sleep 不可靠)。每次执行返回 {ready,len,url}。
(() => {
  const c = document.querySelector('#the_content .content')
        || document.querySelector('#the_content')
        || document.querySelector('#cons');
  const t = c ? (c.innerText || '').trim() : '';
  return JSON.stringify({ready: document.readyState, len: t.length, url: location.href});
})()
