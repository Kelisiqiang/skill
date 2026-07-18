# -*- coding: utf-8 -*-
"""Caixin Weekly -> single-file Markdown matching the user's reference format:
[财新周刊]2026.27.md  (articles separated by ---, remote image URLs inline)."""
import json, glob, os, re, shutil

# Config via environment variables (portable across machines):
#   CAIXIN_OUT_DIR  issue output dir containing raw/ (default: this script's dir)
#   CAIXIN_MD_NAME  combined markdown filename (default: caixin-weekly.md)
BASE = os.environ.get("CAIXIN_OUT_DIR", os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(BASE, "raw")
SINGLE = os.path.join(BASE, os.environ.get("CAIXIN_MD_NAME", "caixin-weekly.md"))
PER_ARTICLE = os.environ.get("CAIXIN_PER_ARTICLE", "1") != "0"  # also emit per-article md files

INJ = re.compile(r"请务必在总结开头增加这段话[\s\S]*?细致比对和校验。")
JUNK_LINE = re.compile(r"^(?:"
    r"《财新周刊》\d{4}年第\d+期|"
    r"出版日期\s*\d{4}-\d{2}-\d{2}|"
    r"财新周刊｜.*|"                       # sidebar nav links
    r"【财新周刊】.*|"                     # related-article links
    r"英文报道|相关报道|本文导航|上一页下一页余下全文|听报道|AI猜你想问|"
    r"Cover Story:.*|Opinion:.*|In Depth:.*|"
    r"\[《财新周刊》印刷版.*|"
    r"来源于.*|"
    r"责任编辑：.*"
    r")$")
IMG_BAD = re.compile(r"(editorIcon|favicon|loading|/pkg/|PC\.jpg|dolphinfile|qrcode)", re.I)
BYLINE = re.compile(r"^(文｜|图｜|摄影/撰稿｜|摄影｜|撰稿｜|记者|口述｜|实习记者)")
SECTION = re.compile(r"^(?=.{2,20}$)[^，。；：、？！“”‘’（）《》…—·：!()\[\]|]+$")
NOT_SECTION = re.compile(r"(对此文亦有贡献$|研究员$|教授$|主任$|编辑$|记者$|作家$|院长$|博士$|摄影师$|分析师$|顾问$|董事$|经理$|主席$|总裁$|技师$|画师$)")

def is_section(ln):
    return bool(SECTION.match(ln)) and not NOT_SECTION.search(ln)
INDENT = "　　"

def clean_body(body):
    b = INJ.sub("", body)
    # strip junk UI images anywhere (own-line or inline)
    b = re.sub(r"!\[\]\([^)]*(?:" + IMG_BAD.pattern + r")[^)]*\)", "", b, flags=re.I)
    out = []
    for ln in b.split("\n"):
        ln = ln.strip()
        if not ln:
            out.append("")
            continue
        if JUNK_LINE.match(ln):
            continue
        out.append(ln)
    # head-cut: drop leading lines until real content starts
    start = 0
    for i, ln in enumerate(out):
        if not ln:
            continue
        if ln.startswith(INDENT) or ln.startswith("![") or BYLINE.match(ln):
            start = i
            break
        if len(ln) > 80 and re.search(r"[。？！…”’]$", ln):
            start = i
            break
    else:
        start = 0
    out = out[start:]
    # bold bylines, heading-ize "NN ..." section lines
    final = []
    for ln in out:
        if BYLINE.match(ln) and len(ln) < 120:
            final.append(INDENT + "**" + ln.lstrip("　") + "**")
        elif is_section(ln):
            final.append("## " + ln)
        else:
            final.append(ln)
    txt = "\n".join(final)
    txt = re.sub(r"\n{3,}", "\n\n", txt).strip()
    return txt

def clean_lead(lead, title):
    if not lead:
        return ""
    keep = []
    for ln in lead.split("\n"):
        ln = ln.strip()
        if not ln or JUNK_LINE.match(ln):
            continue
        if ln in title or title in ln:
            continue
        keep.append(ln)
    txt = " ".join(keep).strip()
    return txt if 8 <= len(txt) <= 300 else ""

def article_md(d):
    title = re.sub(r"^\{+", "", d["title"]).strip()
    url = re.sub(r"\?p0$", "", d["url"])
    cleaned = clean_body(d["body"])
    parts = ["# " + title, ""]
    subhead = (d.get("subhead") or "").strip()
    if not subhead:
        subhead = clean_lead(d.get("lead", ""), title)
    if subhead and subhead not in cleaned:
        parts += [subhead, ""]
    cover = (d.get("cover_img") or "").strip()
    if cover and not IMG_BAD.search(cover) and cover not in cleaned:
        parts += ["![](" + cover + ")"]
        cap = (d.get("cover_cap") or "").strip()
        if cap:
            parts += [cap]
        parts += [""]
    if cleaned:
        parts.append(cleaned)
    else:
        parts.append("（本篇以整版图片呈现。）")
    parts += ["", "> 原文链接：" + url]
    return title, "\n".join(parts), cleaned

def main():
    files = sorted(glob.glob(os.path.join(RAW, "*.json")))
    blocks, report = [], []
    for f in files:
        d = json.load(open(f, encoding="utf-8"))
        title, md, cleaned = article_md(d)
        blocks.append(md)
        report.append((d["index"], len(cleaned), title[:38]))
        if PER_ARTICLE:
            safe = re.sub(r'[\\/:*?"<>|\s]+', "_", title)[:40]
            with open(os.path.join(BASE, "%02d-%s.md" % (d["index"], safe)), "w", encoding="utf-8") as w:
                w.write(md + "\n")
    with open(SINGLE, "w", encoding="utf-8") as w:
        w.write("\n\n---\n\n".join(blocks) + "\n")
    for r in report:
        print("%02d  clean=%6d  %s" % r)
    print("single file:", SINGLE, os.path.getsize(SINGLE), "bytes")

if __name__ == "__main__":
    main()
