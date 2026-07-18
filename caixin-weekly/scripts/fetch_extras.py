# -*- coding: utf-8 -*-
"""Batch-fetch article extras (subhead + cover image/caption) via browser fetch().

These two fields live OUTSIDE the body container, so the live-extraction in
extract.js does not capture them; but they ARE present in the static HTML,
so a plain fetch() (no navigation) suffices.

Env: CAIXIN_WS (workspace), CAIXIN_OUT (output subdir, default caixin-weekly-out)
Reads <OUT>/toc.json, updates <OUT>/raw/NN.json with keys:
  subhead, cover_img, cover_cap

Standalone:  python fetch_extras.py
As module:   from fetch_extras import fetch_extras; fetch_extras(wb, js_value, outdir)
"""
import json, os

EXTRAS_JS = """(async () => {
  const urls = %s;
  const out = [];
  for (const u of urls) {
    try {
      const r = await fetch(u, {credentials:'include'});
      const h = await r.text();
      const d = new DOMParser().parseFromString(h, 'text/html');
      const sh = d.querySelector('#subhead') || d.querySelector('.subhead');
      const media = d.querySelector('#the_content .media') || d.querySelector('#the_content .article_media_pic');
      const img = media ? media.querySelector('img') : null;
      const cap = media ? (media.textContent||'').trim().replace(/\\s+/g,' ') : '';
      out.push({u,
        subhead: sh ? (sh.textContent||'').trim().replace(/\\s+/g,' ') : '',
        src: img ? (img.src||img.getAttribute('data-src')||'') : '',
        cap: cap});
    } catch(e) { out.push({u, subhead:'', src:'', cap:'', err:String(e)}); }
  }
  return JSON.stringify(out);
})()"""


def fetch_extras(wb, js_value, outdir):
    """wb/js_value: WebBridge helpers from driver_webbridge. Returns count updated."""
    rawdir = os.path.join(outdir, "raw")
    toc = json.load(open(os.path.join(outdir, "toc.json"), encoding="utf-8"))
    items = toc["items"] if "items" in toc else json.loads(toc["data"]["value"])["items"]
    arts = [it for it in items if it["k"] == "a"]
    urls = [a["h"] for a in arts]
    r = wb("evaluate", {"code": EXTRAS_JS % json.dumps(urls)}, timeout=180, retries=1)
    data = js_value(r)
    if not data or len(data) != len(arts):
        raise RuntimeError("extras fetch failed: %r" % (r,)[:300])
    for i, item in enumerate(data):
        fp = os.path.join(rawdir, "%02d.json" % (i + 1))
        if not os.path.exists(fp):
            continue
        d = json.load(open(fp, encoding="utf-8"))
        d["subhead"] = item["subhead"]
        d["cover_img"] = item["src"]
        d["cover_cap"] = item["cap"]
        json.dump(d, open(fp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("%02d  subhead=%s  cover=%s" % (i + 1, bool(item["subhead"]), bool(item["src"])))
    return len(data)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from driver_webbridge import wb, js_value, OUTDIR
    fetch_extras(wb, js_value, OUTDIR)
