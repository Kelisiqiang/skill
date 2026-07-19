#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDF 去水印 — 统一智能入口（pdf-watermark-removal skill 主脚本）

处理优先级（规则0 / 规则0.5）：
  1. 先分类：LAYERED(有文本层) vs SCANNED(纯图/扫描件)
  2. LAYERED 首选 → Form XObject 无损删除法
        · 灰度填充的 Form = 水印
        · 黑字 + 页眉/页脚位置的 Form = 推广
        · 从页面流中删除其 Do 的 /Artifact BDC...EMC 整块
        · save(garbage=4, deflate=True) 清理，正文/图片毫发无损
  3. LAYERED 兜底 → inline 文本 span redact（仅当水印在页面流 inline 文本中时使用）
  4. SCANNED 兜底 → 像素级灰度/彩色检测 + 连通域保护 + JPEG 压缩

底层强制规则：
  · 输出体积 ≤ 源文件 1.5 倍（理想更小）
  · 禁止 PNG 无损合成；JPEG 压缩 + garbage=4, deflate=True
  · 输出文件名 = 源文件名 + "_无水印"，同目录

依赖：PyMuPDF（必选）；numpy/Pillow/scipy（像素法兜底用）
"""
import os
import re
import sys
import io
import argparse
from pathlib import Path

try:
    import fitz
except ImportError:
    print("错误: 请安装 PyMuPDF (pip install PyMuPDF)")
    sys.exit(1)


# ====================== Form XObject 无损删除法 ======================

def is_gray_form(content):
    """内容流中是否出现灰色填充（近似灰度，0.12~0.9 之间）。"""
    for m in re.finditer(r'(\d*\.\d+)\s+[gG]\b', content):
        if 0.12 < float(m.group(1)) < 0.9:
            return True
    for m in re.finditer(r'(\d*\.\d+)\s+(\d*\.\d+)\s+(\d*\.\d+)\s+[rR][gG]\b', content):
        r, g, b = float(m.group(1)), float(m.group(2)), float(m.group(3))
        if abs(r - g) < 0.05 and abs(g - b) < 0.05 and 0.12 < (r + g + b) / 3 < 0.9:
            return True
    return False


def is_text_form(content):
    return 'BT' in content and 'ET' in content


def classify_xobject(doc, xref, name, cm_f, page_h):
    """判断某个 Form XObject 是否为水印/推广。"""
    obj = doc.xref_object(xref)
    if '/Form' not in obj:
        return None
    content = doc.xref_stream(xref).decode("latin-1", errors="replace")
    if is_gray_form(content):
        return "WATERMARK"
    if is_text_form(content) and cm_f is not None and (
            cm_f < 0.07 * page_h or cm_f > 0.93 * page_h):
        return "PROMO"
    return None


def strip_artifact(stream, remove_names):
    """从页面流中删除目标 Do 的 /Artifact BDC...EMC 整块（或外层 q..Q）。"""
    result = stream
    changed = True
    while changed:
        changed = False
        for m in re.finditer(r'/([A-Za-z0-9]+)\s+Do', result):
            name = m.group(1)
            if name not in remove_names:
                continue
            s = m.start()
            # 优先删除 /Artifact BDC ... EMC 整块
            bdc = None
            for bm in re.finditer(r'\bBDC\b', result[:s]):
                if result.count('EMC', bm.end(), s) == 0:
                    bdc = bm.start()
            emc = None
            for em in re.finditer(r'\bEMC\b', result[s:]):
                emc = s + em.end()
                break
            if bdc is not None and emc is not None:
                result = result[:bdc] + result[emc:]
                changed = True
                break
            # 退化方案：删除外层 q..Q
            depth = 0
            qpos = None
            for qm in re.finditer(r'\b[qQ]\b', result[:s]):
                if qm.group() == 'q':
                    depth += 1
                    qpos = qm.start()
                else:
                    depth -= 1
                    if depth == 0:
                        qpos = None
            depth = 0
            Qpos = None
            for qm in re.finditer(r'\b[qQ]\b', result[s:]):
                if qm.group() == 'q':
                    depth += 1
                else:
                    depth -= 1
                    if depth == 0:
                        Qpos = s + qm.end()
                        break
            if qpos is not None and Qpos is not None:
                result = result[:qpos] + result[Qpos:]
                changed = True
                break
    return result


def remove_form_watermark(doc):
    """
    分层型首选无损法：删除 Form XObject 水印与推广。
    返回 (wm_count, promo_count, modified_pages)。
    """
    total_wm = total_promo = modified = 0
    for pno in range(doc.page_count):
        p = doc[pno]
        page_h = p.rect.height
        xobjs = p.get_xobjects()
        if not xobjs:
            continue
        remove_names = set()
        cx = p.get_contents()
        cstream = b"".join(doc.xref_stream(x) for x in cx) if isinstance(cx, list) else doc.xref_stream(cx)
        cstr = cstream.decode("latin-1", "replace")
        for (xref, name, *rest) in xobjs:
            f = None
            for dm in re.finditer(r'(.*?)/' + re.escape(name) + r'\s+Do', cstr, re.S):
                cc = re.findall(
                    r'([\d.\-]+)\s+([\d.\-]+)\s+([\d.\-]+)\s+([\d.\-]+)\s+([\d.\-]+)\s+([\d.\-]+)\s+cm',
                    dm.group(1))
                if cc:
                    f = float(cc[-1][5])
            cls = classify_xobject(doc, xref, name, f, page_h)
            if cls == "WATERMARK":
                remove_names.add(name)
                total_wm += 1
            elif cls == "PROMO":
                remove_names.add(name)
                total_promo += 1
        if not remove_names:
            continue
        if isinstance(cx, list):
            for xr in cx:
                raw = doc.xref_stream(xr)
                new = strip_artifact(raw.decode("latin-1", "replace"), remove_names).encode("latin-1")
                doc.update_stream(xr, new)
        else:
            raw = doc.xref_stream(cx)
            new = strip_artifact(raw.decode("latin-1", "replace"), remove_names).encode("latin-1")
            doc.update_stream(cx, new)
        modified += 1
    return total_wm, total_promo, modified


# ====================== inline 文本 redact 兜底 ======================

PROMO_HINTS = ['入群', '有群', '付费', '助理', 'guaer', '98元', '198', '268', '一年有群',
               '公众号', '关注', '二维码', '加v', '加微', '微信']


def remove_inline_redact(doc):
    """
    LAYERED 兜底：水印是页面流 inline 文本时的矩形 redact 遮盖。
    仅删除含推广关键词的小字 span；正文大标题（字号大/位于上半页）不碰。
    """
    total = 0
    for page_num in range(doc.page_count):
        page = doc[page_num]
        h = page.rect.height
        targets = []
        try:
            td = page.get_text("dict")
            for blk in td.get('blocks', []):
                if blk.get('type') != 0:
                    continue
                for line in blk.get('lines', []):
                    for span in line.get('spans', []):
                        text = span.get('text', '')
                        if any(kw in text for kw in PROMO_HINTS):
                            bbox = fitz.Rect(span['bbox'])
                            font_size = span.get('size', 10)
                            if font_size < 14 or bbox.y0 > h * 0.5:
                                targets.append(bbox)
        except Exception:
            pass
        if targets:
            seen = set()
            for rect in targets:
                key = (round(rect.x0), round(rect.y0), round(rect.x1), round(rect.y1))
                if key not in seen:
                    seen.add(key)
                    page.add_redact_annot(rect, fill=(1, 1, 1))
            if seen:
                page.apply_redactions()
                total += len(seen)
    return total


# ====================== 分类与像素兜底 ======================

def classify(doc):
    """返回 'layered' 或 'scanned'。"""
    pg = doc[0]
    txt = pg.get_text().strip()
    fullpage = False
    for im in pg.get_images(full=True):
        for r in pg.get_image_rects(im[0]):
            if r.width > pg.rect.width * 0.8 and r.height > pg.rect.height * 0.8:
                fullpage = True
                break
        if fullpage:
            break
    return 'layered' if (len(txt) > 50 and not fullpage) else 'scanned'


# 像素法延迟导入（仅在 SCANNED 时使用，避免无 numpy 时报错）
def _process_pixel(input_path, output_path, mode, **kw):
    try:
        from pdf_watermark import process_pdf
    except ImportError:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from pdf_watermark import process_pdf
    process_pdf(input_path, output_path, mode=mode, **kw)


# ====================== 主流程 ======================

def process_file(input_path, output_path=None, mode='auto',
                 zoom=2, quality=80, gray_min=120, gray_max=240,
                 gray_diff=30, rmin=175, rmax=255, gmax=175, bmax=175):
    src = Path(input_path)
    if output_path is None:
        output_path = str(src.parent / f"{src.stem}_无水印.pdf")

    doc = fitz.open(input_path)
    src_mb = os.path.getsize(input_path) / 1024 / 1024
    kind = classify(doc)

    used = None
    if mode in ('auto', 'form'):
        wm, promo, pages = remove_form_watermark(doc)
        if wm or promo:
            doc.save(output_path, garbage=4, deflate=True, clean=True)
            doc.close()
            used = f"Form XObject 无损删除 (水印{wm} 推广{promo} 共{pages}页)"
            # 已无损处理，跳过像素法
            out_mb = os.path.getsize(output_path) / 1024 / 1024
            _report(input_path, output_path, kind, used, src_mb, out_mb)
            return output_path

    if mode == 'auto':
        # 无损法没找到目标 → 判断是否扫描件；若是则像素法，否则 inline redact
        if kind == 'scanned':
            _process_pixel(input_path, output_path, 'gray', zoom=zoom,
                           gray_min=gray_min, gray_max=gray_max, gray_diff=gray_diff,
                           jpeg_quality=quality)
            used = "像素法 (灰度, 扫描件)"
        else:
            redacts = remove_inline_redact(doc)
            doc.save(output_path, garbage=4, deflate=True, clean=True)
            doc.close()
            used = f"inline redact 遮盖 ({redacts} 处)"
    elif mode in ('gray', 'color'):
        # 强制像素法
        _process_pixel(input_path, output_path, mode, zoom=zoom,
                       rmin=rmin, rmax=rmax, gmax=gmax, bmax=bmax,
                       gray_min=gray_min, gray_max=gray_max, gray_diff=gray_diff,
                       jpeg_quality=quality)
        used = f"像素法 ({mode})"
    else:
        doc.close()
        raise ValueError(f"未知 mode: {mode}")

    out_mb = os.path.getsize(output_path) / 1024 / 1024
    _report(input_path, output_path, kind, used, src_mb, out_mb)
    return output_path


def _report(input_path, output_path, kind, used, src_mb, out_mb):
    flag = "OK" if out_mb <= src_mb * 1.5 else "⚠️ BIG!"
    print(f"  类型: {kind}")
    print(f"  方法: {used}")
    print(f"  大小: {src_mb:.2f} MB → {out_mb:.2f} MB ({out_mb/src_mb:.2f}x) {flag}")
    print(f"  输出: {output_path}")


def iter_pdf_files(source):
    p = Path(source)
    if p.is_dir():
        files = sorted([str(x) for x in p.glob('*.pdf') if '_无水印' not in x.name])
        return files
    return [str(p)]


def main():
    parser = argparse.ArgumentParser(
        description='PDF 去水印 — 自动分类 + Form XObject 无损优先 + 像素法兜底',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 自动分类处理单个文件（推荐）
  python remove_watermark.py input.pdf

  # 处理整个目录
  python remove_watermark.py ./pdfs/

  # 强制像素法（扫描件/调试用）
  python remove_watermark.py input.pdf --mode gray --quality 80

  # 仅用 Form XObject 无损法
  python remove_watermark.py input.pdf --mode form
        """)
    parser.add_argument('source', help='输入 PDF 文件或目录')
    parser.add_argument('-o', '--output', help='输出路径（文件或目录）')
    parser.add_argument('--mode', default='auto',
                        choices=['auto', 'form', 'gray', 'color'],
                        help='处理策略: auto=智能(默认) / form=仅Form无损 / gray,color=像素法')
    parser.add_argument('--zoom', type=int, default=2, help='像素法渲染缩放 (默认2)')
    parser.add_argument('--quality', type=int, default=80, help='JPEG 质量 1-100 (默认80)')
    parser.add_argument('--gray-min', type=int, default=120)
    parser.add_argument('--gray-max', type=int, default=240)
    parser.add_argument('--gray-diff', type=int, default=30)
    parser.add_argument('--rmin', type=int, default=175)
    parser.add_argument('--rmax', type=int, default=255)
    parser.add_argument('--gmax', type=int, default=175)
    parser.add_argument('--bmax', type=int, default=175)

    args = parser.parse_args()

    files = iter_pdf_files(args.source)
    if not files:
        print("未找到待处理 PDF 文件。")
        return

    print(f"待处理: {len(files)} 个文件\n" + "-" * 60)
    for f in files:
        print(f"\n▶ {f}")
        try:
            out = args.output
            if out and len(files) > 1 and os.path.isdir(args.source):
                out = os.path.join(out, Path(f).stem + "_无水印.pdf")
            process_file(f, out, mode=args.mode, zoom=args.zoom,
                         quality=args.quality, gray_min=args.gray_min,
                         gray_max=args.gray_max, gray_diff=args.gray_diff,
                         rmin=args.rmin, rmax=args.rmax, gmax=args.gmax, bmax=args.bmax)
        except Exception as e:
            print(f"  ❌ 失败: {e}")
    print("\n完成!")


if __name__ == '__main__':
    main()
