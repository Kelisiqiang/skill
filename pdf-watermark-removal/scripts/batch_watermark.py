# -*- coding: utf-8 -*-
"""
智能双路径 PDF 去水印 — 批量处理
规则0: 先分类再选策略
  LAYERED(有文本层)   → 直接 redact 遮盖水印对象 (快/无损)
  SCANNED(纯图/扫描件) → 灰色斜铺像素法 (连通域保护+JPEG压缩)
"""
import fitz
import numpy as np
from PIL import Image
import io, os, glob

SRC_DIR = 'D:/kelisiqing_OB/00.daidai/岱岱专题md/政策文件会议解读合集/重大政策文件解读'
JPEG_Q = 80

# ========== 扫描模式参数 ==========
ZOOM = 2
GRAY_MIN, GRAY_MAX, GRAY_DIFF = 120, 240, 30
MAX_AREA_RATIO = 0.0008
try:
    from scipy import ndimage; HAS_SCIPY = True
except: HAS_SCIPY = False

# ========== 分层模式参数 ==========
PROMO_KW = ['入群','有群','付费','助理','guaer','98元','198','268','一年有群']


def classify(doc):
    """判断 PDF 类型: 'layered' | 'scanned'"""
    pg = doc[0]
    txt = pg.get_text().strip()
    nwords = len(txt)
    # 整页大图?
    fullpage = False
    for im in pg.get_images():
        for r in pg.get_image_rects(im[0]):
            if r.width > pg.rect.width*0.8 and r.height > pg.rect.height*0.8:
                fullpage = True
    return 'layered' if (nwords > 50 and not fullpage) else 'scanned'


def process_layered(doc, output_path):
    """
    分层/矢量型 PDF: 直接 redact 遮盖水印对象
    - 检测推广关键词文本块 → 白色遮盖
    - 检测右下角二维码图片 → 白色遮盖
    - 无目标则保留原样
    返回: 总 redact 数量
    """
    total_redacts = 0
    pages_modified = 0

    for page_num in range(len(doc)):
        page = doc[page_num]
        h, w = page.rect.height, page.rect.width
        targets = []  # 要遮盖的矩形列表

        # --- 1. 文本层: 搜推广关键词 ---
        try:
            td = page.get_text("dict")
            for blk in td.get('blocks', []):
                if blk.get('type') != 0:
                    continue  # 跳过图片block
                for line in blk.get('lines', []):
                    for span in line.get('spans', []):
                        text = span.get('text', '')
                        if any(kw in text for kw in PROMO_KW):
                            bbox = fitz.Rect(span['bbox'])
                            # 条件: 字号较小 或 位于下半页 (排除正文大标题误伤)
                            font_size = span.get('size', 10)
                            if font_size < 13 or bbox.y0 > h * 0.55:
                                targets.append((bbox, f'text:"{text[:20]}"'))
        except Exception as e:
            pass  # get_text dict 解析失败时跳过

        # --- 2. 图片层: 右下角小图(疑似二维码/Logo) ---
        for im in page.get_images():
            for r in page.get_image_rects(im[0]):
                area_ratio = (r.width * r.height) / (w * h)
                if (r.x0 > w * 0.5 and r.y0 > h * 0.5
                        and area_ratio < 0.15 and area_ratio > 0.001):
                    targets.append((r, f'img:xref={im[0]}'))

        # --- 3. 执行 redact ---
        if targets:
            seen = set()
            for rect, desc in targets:
                key = (round(rect.x0), round(rect.y0),
                       round(rect.x1), round(rect.y1))
                if key not in seen:
                    seen.add(key)
                    page.add_redact_annot(rect, fill=(1, 1, 1))
            if seen:
                page.apply_redactions()
                total_redacts += len(seen)
                pages_modified += 1

    doc.save(output_path, garbage=4, deflate=True)
    return total_redacts, pages_modified


def process_scanned(doc, output_path):
    """
    扫描/图片融合型: 灰色斜铺像素法 + 连通域保护 + JPEG压缩
    """
    new_doc = fitz.open()

    for page_num in range(len(doc)):
        page = doc[page_num]
        pix = page.get_pixmap(matrix=fitz.Matrix(ZOOM, ZOOM), alpha=False)
        img = np.frombuffer(buffer=pix.samples, dtype=np.uint8).reshape(
            (pix.h, pix.w, -1)).copy()

        rc = img[:,:,0].astype(np.int16); gc = img[:,:,1].astype(np.int16)
        bc = img[:,:,2].astype(np.int16)
        rg = np.abs(rc-gc); rb = np.abs(rc-bc); gb = np.abs(gc-bc)
        avg = (rc+gc+bc)/3
        gray_mask = (rg<GRAY_DIFF)&(rb<GRAY_DIFF)&(gb<GRAY_DIFF)&\
                    (avg>GRAY_MIN)&(avg<GRAY_MAX)

        n_gray = int(np.sum(gray_mask))
        if n_gray >= 100 and HAS_SCIPY:
            lab, nf = ndimage.label(gray_mask)
            sizes = ndimage.sum(gray_mask, lab, range(1, nf+1))
            area = img.shape[0]*img.shape[1]
            final = gray_mask.copy()
            for cid in range(1, nf+1):
                if sizes[cid-1]/area > MAX_AREA_RATIO:
                    final[lab==cid] = False
            img[final] = [255,255,255]
        elif n_gray >= 100:
            img[gray_mask] = [255,255,255]

        pil = Image.fromarray(img.astype(np.uint8), 'RGB')
        buf = io.BytesIO()
        pil.save(buf, format='JPEG', quality=JPEG_Q, optimize=True)
        buf.seek(0)
        np_ = new_doc.new_page(width=page.rect.width, height=page.rect.height)
        np_.insert_image(np_.rect, stream=buf.getvalue())

    new_doc.save(output_path, garbage=4, deflate=True)
    return n_gray


# ==================== 主流程 ====================
if __name__ == '__main__':
    pdfs = sorted(glob.glob(os.path.join(SRC_DIR, '*.pdf')))
    pdfs = [p for p in pdfs if '_无水印' not in p]

    print(f'目录: {SRC_DIR}')
    print(f'待处理: {len(pdfs)} 个文件\n')
    hdr = '{:>3} {:>6} {:>4} {:>20} {:>7} {:>7} {}'.format('序号','类型','页数','操作','源MB','出MB','状态')
    print(hdr)
    print('-'*75)

    stats = {'layered': 0, 'scanned': 0, 'skip': 0}

    for idx, input_pdf in enumerate(pdfs, 1):
        base = os.path.splitext(os.path.basename(input_pdf))[0]
        output_pdf = os.path.join(SRC_DIR, base + '_无水印.pdf')
        src_mb = os.path.getsize(input_pdf) / 1024 / 1024

        doc = fitz.open(input_pdf)
        kind = classify(doc)
        npages = len(doc)

        try:
            if kind == 'layered':
                n_redacts, n_pages_mod = process_layered(doc, output_pdf)
                action = f'redact({n_redacts}处/{n_pages_mod}页)'
                if n_redacts == 0:
                    stats['skip'] += 1
                else:
                    stats['layered'] += 1
            else:
                n_pixels = process_scanned(doc, output_pdf)
                action = f'像素法(~{n_pixels//10000}万px)'
                stats['scanned'] += 1

            out_mb = os.path.getsize(output_pdf) / 1024 / 1024
            flag = 'OK' if out_mb <= src_mb * 1.5 else 'BIG!'
        except Exception as e:
            out_mb = 0
            flag = f'ERR:{e}'
            action = '失败'

        doc.close()
        print(f'{idx:3d} {kind:>6} {npages:4d} {action:>20} {src_mb:7.1f} {out_mb:7.1f} {flag}')

    print('-'*75)
    print(f'完成! layered处理={stats["layered"]} scanned处理={stats["scanned"]} 无水印跳过={stats["skip"]}')
