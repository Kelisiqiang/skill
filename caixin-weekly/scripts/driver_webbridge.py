# -*- coding: utf-8 -*-
"""Drive Kimi WebBridge to scrape Caixin Weekly article full texts.

Environment variables:
  CAIXIN_WS   workspace dir (default: current working directory)
  CAIXIN_OUT  output dir name under CAIXIN_WS (default: caixin-weekly-out)

Expects <OUT>/toc.json containing either:
  - a WebBridge evaluate response {"data": {"value": "<json string>"}} whose
    value parses to {"items": [...]}, or
  - directly {"items": [...]} with items like {"k": "a", "t": title, "h": url}

Usage: python driver_webbridge.py <start_index> <end_index>
Writes raw article JSON files to <OUT>/raw/NN.json (skips existing files).
"""
import json, os, re, subprocess, sys, time, hashlib

WS = os.environ.get("CAIXIN_WS", os.getcwd())
OUTDIR = os.path.join(WS, os.environ.get("CAIXIN_OUT", "caixin-weekly-out"))
RAWDIR = os.path.join(OUTDIR, "raw")
TOC_PATH = os.path.join(OUTDIR, "toc.json")
DAEMON = os.environ.get("WEBBRIDGE_DAEMON", "http://127.0.0.1:10086/command")
SESSION = os.environ.get("WEBBRIDGE_SESSION", "caixin-weekly")

os.makedirs(RAWDIR, exist_ok=True)

POLL_JS = """(() => { const c=document.querySelector('#the_content .content')||document.querySelector('#the_content')||document.querySelector('#cons'); const t=c?(c.innerText||'').trim():''; return JSON.stringify({ready:document.readyState, len:t.length, url:location.href}); })()"""

EXTRACT_JS = """(() => {
  const box = document.querySelector('#the_content');
  const mob = document.querySelector('#cons');
  const root = box ? (box.querySelector('.content') || box) : mob;
  if (!root) return JSON.stringify({url:location.href, error:'no_content_root'});
  const h1 = document.querySelector('h1') || (mob ? mob.querySelector('h1') : null);
  const title = h1 ? h1.innerText.trim().replace(/\\s+/g,' ') : document.title;
  const c = root.cloneNode(true);
  c.querySelectorAll('script,style,noscript,iframe,form,button,select,.page,.content-tag,.moreReport,.idetor,.lanmu_textend,.mask').forEach(e=>e.remove());
  c.querySelectorAll('img').forEach(im=>{ const s=(im.src||im.getAttribute('data-src')||'').trim(); if(s.startsWith('http')){ im.replaceWith(document.createTextNode('\\n![]('+s+')\\n')); } else { im.remove(); } });
  document.body.appendChild(c);
  let txt = c.innerText || '';
  c.remove();
  txt = txt.replace(/\\r/g,'').replace(/[ \\t\\u00a0]+/g,' ').replace(/\\n{3,}/g,'\\n\\n').trim();
  let lead = '';
  if (box) { const first = box.querySelector(':scope > div'); lead = first && first!==root ? (first.innerText||'').trim() : ''; }
  return JSON.stringify({url:location.href, title:title, len:txt.length, body:txt, lead:lead});
})()"""

def wb(action, args, timeout=45, retries=2):
    body = json.dumps({"action": action, "args": args, "session": SESSION}, ensure_ascii=False)
    fn = os.path.join(OUTDIR, "wb-req-%s.json" % hashlib.md5((action + json.dumps(args, ensure_ascii=False) + str(time.time())).encode()).hexdigest()[:10])
    with open(fn, "w", encoding="utf-8") as f:
        f.write(body)
    try:
        for attempt in range(retries + 1):
            try:
                p = subprocess.run(["curl.exe", "-s", "-m", str(timeout), "-X", "POST", DAEMON,
                                    "-H", "Content-Type: application/json", "--data-binary", "@" + fn],
                                   capture_output=True, timeout=timeout + 10)
                out = p.stdout.decode("utf-8", errors="replace").strip()
                if not out:
                    raise RuntimeError("empty response")
                return json.loads(out)
            except Exception as e:
                if attempt >= retries:
                    return {"ok": False, "error": str(e)}
                time.sleep(1.5)
    finally:
        try: os.remove(fn)
        except OSError: pass

def js_value(resp):
    try:
        return json.loads(resp["data"]["value"])
    except Exception:
        return None

def goto(url):
    wb("evaluate", {"code": "location.href=%s;'nav'" % json.dumps(url)}, timeout=20)

def wait_stable(art_id, max_rounds=50):
    last = -1; stable = 0; t0 = time.time()
    for _ in range(max_rounds):
        r = wb("evaluate", {"code": POLL_JS}, timeout=20, retries=1)
        d = js_value(r)
        if d and art_id in d.get("url", ""):
            ln = d.get("len", 0)
            elapsed = time.time() - t0
            if ln == last and ln > 200:
                stable += 1
                if stable >= 4 and elapsed >= 10:
                    return d
            else:
                stable = 0
            last = ln
        time.sleep(1.2)
    return None

def extract():
    r = wb("evaluate", {"code": EXTRACT_JS}, timeout=45, retries=2)
    return js_value(r)

def load_toc_items():
    raw = json.load(open(TOC_PATH, encoding="utf-8"))
    if "items" in raw:
        return raw["items"]
    inner = raw.get("data", {}).get("value")
    if inner:
        return json.loads(inner)["items"]
    raise RuntimeError("toc.json has no items")

def main():
    start = int(sys.argv[1]); end = int(sys.argv[2])
    items = load_toc_items()
    arts = [it for it in items if it["k"] == "a"]
    print("total articles:", len(arts))
    for i in range(start, min(end, len(arts))):
        a = arts[i]
        url = a["h"]
        m = re.search(r"/(\d+)\.html", url)
        art_id = m.group(1) if m else url
        raw_path = os.path.join(RAWDIR, "%02d.json" % (i + 1))
        print("[%02d] %s -> %s" % (i + 1, a["t"][:30], url), flush=True)
        if os.path.exists(raw_path):
            print("     skip (exists)", flush=True)
            continue
        goto(url + "?p0")
        ok = wait_stable(art_id)
        if not ok:
            print("     WARN: not stable, retry via navigate", flush=True)
            wb("navigate", {"url": url + "?p0"}, timeout=40, retries=0)
            ok = wait_stable(art_id)
        if not ok:
            print("     FAIL: load timeout", flush=True)
            continue
        data = extract()
        if not data or not data.get("body"):
            print("     FAIL: extract", flush=True)
            continue
        data["toc_title"] = a["t"]
        data["index"] = i + 1
        with open(raw_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        print("     OK len=%d title=%s" % (data["len"], data["title"][:40]), flush=True)
        time.sleep(0.5)
    # Step 3 (automatic): batch-fetch subhead + cover image for all articles.
    # These live outside the body container but are in the static HTML.
    try:
        from fetch_extras import fetch_extras
        print("fetching extras (subhead + cover) ...", flush=True)
        fetch_extras(wb, js_value, OUTDIR)
    except Exception as e:
        print("WARN: extras fetch failed (%s); run scripts/fetch_extras.py manually" % e, flush=True)

if __name__ == "__main__":
    if len(sys.argv) >= 3:
        main()
    else:
        # no range given: extras only (raw/ already populated)
        from fetch_extras import fetch_extras
        fetch_extras(wb, js_value, OUTDIR)
