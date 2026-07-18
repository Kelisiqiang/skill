# -*- coding: utf-8 -*-
"""Validate a finished Caixin Weekly scrape BEFORE declaring success.

Env: CAIXIN_WS (workspace), CAIXIN_OUT (output subdir, default caixin-weekly-out),
     CAIXIN_MD_NAME (combined md filename, default: first [财新周刊]*.md in OUTDIR)

Checks (FAIL = must fix, WARN = confirm manually):
  1. raw/*.json count == article count in toc.json            [FAIL]
  2. every article body len >= 400, unless title matches the
     known image-only/stub columns (回溯/天眼/回声/读周刊/融媒精选/编辑更正/答疑) [FAIL]
  3. longest cover-story check: the first TOC article (封面报道)
     must be >= 8000 chars (it is always a multi-page long read)  [FAIL]
  4. each article has subhead / cover_img when available        [WARN]
  5. combined md exists and contains exactly count '# ' articles [FAIL]

Exit code 0 = all FAIL checks pass (WARNs allowed), 1 = any FAIL.
"""
import glob, json, os, re, sys

WS = os.environ.get("CAIXIN_WS", os.getcwd())
OUTDIR = os.path.join(WS, os.environ.get("CAIXIN_OUT", "caixin-weekly-out"))
RAWDIR = os.path.join(OUTDIR, "raw")

STUB = re.compile(r"回溯|天眼|回声|读周刊|融媒精选|编辑更正|答疑")

fails, warns = [], []

toc_path = os.path.join(OUTDIR, "toc.json")
if not os.path.exists(toc_path):
    print("FAIL: toc.json not found in", OUTDIR); sys.exit(1)
toc = json.load(open(toc_path, encoding="utf-8"))
items = toc["items"] if "items" in toc else json.loads(toc["data"]["value"])["items"]
arts = [it for it in items if it["k"] == "a"]

files = sorted(glob.glob(os.path.join(RAWDIR, "*.json")))
print("toc articles: %d, raw files: %d" % (len(arts), len(files)))
if len(files) != len(arts):
    fails.append("raw count %d != toc count %d" % (len(files), len(arts)))

rows = []
for i, f in enumerate(files):
    d = json.load(open(f, encoding="utf-8"))
    title = d.get("toc_title") or d.get("title", "?")
    ln = d.get("len", 0)
    sub = bool((d.get("subhead") or "").strip())
    cov = bool((d.get("cover_img") or "").strip())
    rows.append((i + 1, ln, sub, cov, title))
    if ln < 400 and not STUB.search(title):
        fails.append("#%02d body too short (%d chars): %s" % (i + 1, ln, title[:40]))
    if i == 0 and ln < 8000:
        fails.append("#01 cover story too short (%d chars, paginated long read not captured)" % ln)
    if not sub:
        warns.append("#%02d no subhead: %s" % (i + 1, title[:40]))
    if not cov:
        warns.append("#%02d no cover image: %s" % (i + 1, title[:40]))

md_name = os.environ.get("CAIXIN_MD_NAME")
if md_name:
    md_path = os.path.join(OUTDIR, md_name)
else:
    cands = glob.glob(os.path.join(OUTDIR, "*.md"))
    md_path = cands[0] if cands else None
if not md_path or not os.path.exists(md_path):
    fails.append("combined markdown not found in %s" % OUTDIR)
else:
    md = open(md_path, encoding="utf-8").read()
    n = len(re.findall(r"^# ", md, re.M))
    print("combined md: %s (%d articles, %d bytes)" % (os.path.basename(md_path), n, len(md)))
    if n != len(arts):
        fails.append("combined md has %d articles, toc has %d" % (n, len(arts)))

print()
print("idx  chars   subhead cover  title")
for i, ln, sub, cov, t in rows:
    print("%02d   %6d   %s      %s     %s" % (i, ln, "Y" if sub else "-", "Y" if cov else "-", t[:38]))
print()
for w in warns:
    print("WARN:", w)
for x in fails:
    print("FAIL:", x)
print()
print("RESULT:", "PASS (with %d warnings)" % len(warns) if not fails else "FAILED (%d failures)" % len(fails))
sys.exit(1 if fails else 0)
