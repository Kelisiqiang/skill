#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
detect_watermark.py — PDF 水印自动检测模块
================================================

为 PDF 文件处理模块提供「水印自动检测」能力：判断文件是否含水印，
并返回水印类型与属性（位置 / 透明度 / 重复模式 / 内容）。

覆盖四类检测逻辑（用户需求）：
  1. 检测页面背景层中重复出现的半透明文字或图案
  2. 识别覆盖在正文上方、且与正文内容无关的重复性元素
  3. 分析页面中固定位置出现的浅色 / 低不透明度图形
  4. 区分水印与正常的页眉页脚内容

检测路径（与 remove_watermark.py 的设计一致）：
  A. 矢量 / 分层型（首选）— 解析 Form XObject 与文本层：
       - 灰度填充 (0.5 0.5 0.5 rg) 或 /Subtype /Watermark 标记 → 水印
       - 页眉/页脚位置的推广文字（含广告关键词）→ promo（亦视为需去除的覆盖物）
       - 页眉/页脚但不含广告关键词（页码、文档标题）→ 正常页眉页脚（非水印）
       - 其它非灰度、无推广关键词的 XObject（图片/Logo）→ 正常图形，不报水印
  B. 扫描 / 图片融合型（兜底）— 像素级：
       - 渲染页面 → 灰度像素检测 → 跨页配准判断重复性 → 连通域判断平铺

输出结构（dict）：
  {
    "file": str,
    "has_watermark": bool,
    "has_promo": bool,
    "confidence": float,            # 0~1 总体置信度
    "page_count": int,
    "analyzed_pages": int,
    "watermarks": [ {...}, ... ],   # 去重后的水印/覆盖物明细（每项代表一种）
    "normal_header_footer": [...],  # 被明确排除的正常页眉页脚
    "summary": str                  # 人类可读结论
  }

CLI 用法：
  python detect_watermark.py input.pdf
  python detect_watermark.py input.pdf --json -o report.json
"""

import os
import re
import sys
import json
import math
import argparse
from collections import defaultdict

import fitz  # PyMuPDF


# ---------------------------------------------------------------------------
# 常量与阈值
# ---------------------------------------------------------------------------

# 归一化灰度（rg 操作符取值 0~1）被判为「浅色/半透明感」的范围
GRAY_LO = 0.15
GRAY_HI = 0.90
# 文本 span 颜色（0~255）判为「浅色」的范围
LIGHT_RGB_MIN = 90
LIGHT_RGB_MAX = 210
# 重复判定：出现页数 >= max(MIN_REP_PAGES, RATIO * 总页数) 视为「重复水印」
MIN_REP_PAGES = 3
REP_RATIO = 0.5
# 推广/广告关键词（命中即视为需去除的覆盖物，而非正常页眉页脚）
PROMO_KW = [
    "公众号", "关注", "微信", "入群", "加v", "助理", "付费", "二维码", "扫码",
    "有群", "米粒", "广积粮", "3030423182", "98元", "198", "268",
    "一年", "会员", "课程", "知识星球", "小报童", "知乎", "微博", "抖音", "小红书",
    "gua", "vx", "v信",
]
# 正常页眉页脚典型特征（命中 → 倾向于「非水印」）
NORMAL_HF_KW = ["第", "页", "page", "—", "·", "│", "版权", "©", "copyright", "confidential"]


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _decode_color(cint):
    """PyMuPDF 文本 span 的 color 是 sRGB 打包整数，解码为 (r,g,b)。"""
    if cint is None:
        return None
    if isinstance(cint, int):
        return ((cint >> 16) & 255, (cint >> 8) & 255, cint & 255)
    if isinstance(cint, (list, tuple)) and len(cint) >= 3:
        return (int(cint[0]), int(cint[1]), int(cint[2]))
    return None


def _is_gray_rgb(rgb, tol=25):
    if rgb is None:
        return False
    r, g, b = rgb
    return abs(r - g) < tol and abs(g - b) < tol


def _digits(s):
    return "".join(re.findall(r"\d", s or ""))


def _contains_promo(text):
    if not text:
        return False
    t = text.lower()
    return any(kw.lower() in t for kw in PROMO_KW)


def _looks_like_normal_header(text):
    if not text:
        return False
    t = text.strip().lower()
    if re.fullmatch(r"[\d\s/—·|第页p\.]*", t) and any(ch.isdigit() for ch in t):
        return True  # 纯页码
    return any(kw in t for kw in NORMAL_HF_KW) and not _contains_promo(text)


def _area_of(bbox, page_h):
    """根据 bbox *中心* 判定落在页面的哪个区域（用中心更稳，抗旋转大 bbox）。"""
    if not bbox or not page_h:
        return "unknown"
    cy = (bbox[1] + bbox[3]) / 2.0
    rel = cy / page_h
    if rel < 0.12:
        return "header"
    if rel > 0.88:
        return "footer"
    if 0.30 < rel < 0.70:
        return "center"
    return "side"


def _xobject_text_hint(stream):
    """从 XObject 内容流里抽取文字提示（用于报告水印内容）。"""
    if not stream:
        return ""
    ms = re.findall(r"\((.*?)\)\s*Tj", stream)
    if not ms:
        ms = re.findall(r"\[(.*?)\]\s*TJ", stream)
    return " ".join(m for m in ms if m.strip())[:120]


def _is_tiled_in_stream(snippet):
    """XObject 自身内容里若多次绘制同一文字 → 平铺水印。"""
    if not snippet:
        return False
    return len(re.findall(r"\(.*?\)\s*Tj", snippet)) > 1


def _cm_angle(page, doc, name):
    """从页面内容流里找 `/name Do` 之前的 cm 矩阵，返回旋转角度（度）。"""
    try:
        xr = page.get_contents()
        if isinstance(xr, list):
            xr = xr[0]
        s = doc.xref_stream(xr)
        if isinstance(s, bytes):
            s = s.decode("latin-1", "replace")
        m = re.search(
            r"([\d.\-]+)\s+([\d.\-]+)\s+([\d.\-]+)\s+([\d.\-]+)\s+"
            r"([\d.\-]+)\s+([\d.\-]+)\s+cm\s*/" + re.escape(name) + r"\s+Do",
            s,
        )
        if not m:
            return 0.0
        a, b = float(m.group(1)), float(m.group(2))
        if abs(a) < 1e-6 and abs(b) < 1e-6:
            return 0.0
        return round(math.degrees(math.atan2(b, a)), 1)
    except Exception:
        return 0.0


def _artifact_subtype(page, doc, name):
    """从页面内容流的 /Artifact ... BDC 包裹判断语义：Watermark/Header/Footer。"""
    try:
        xr = page.get_contents()
        if isinstance(xr, list):
            xr = xr[0]
        s = doc.xref_stream(xr)
        if isinstance(s, bytes):
            s = s.decode("latin-1", "replace")
        idx = s.find("/%s Do" % name)
        if idx < 0:
            return None
        back = s[max(0, idx - 500):idx]
        if "/Watermark" in back:
            return "Watermark"
        if "/Header" in back:
            return "Header"
        if "/Footer" in back:
            return "Footer"
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 单页分析
# ---------------------------------------------------------------------------

def _analyze_xobjects(doc, page, pno, page_h):
    """路径 A-1：解析页面 Form XObject。"""
    out = []
    try:
        xos = page.get_xobjects()
    except Exception:
        return out
    for xo in xos:
        if not isinstance(xo, (list, tuple)) or len(xo) < 2:
            continue
        xref = xo[0]
        name = xo[1]
        bbox = xo[3] if len(xo) > 3 else None
        try:
            obj = doc.xref_object(xref)
        except Exception:
            continue
        if "/Form" not in obj:
            continue  # 跳过图像 XObject
        try:
            stream = doc.xref_stream(xref)
            if isinstance(stream, bytes):
                stream = stream.decode("latin-1", "replace")
        except Exception:
            stream = ""

        color = None
        is_gray_light = False
        m = re.search(r"([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+rg", stream)
        if m:
            r, g, b = float(m.group(1)), float(m.group(2)), float(m.group(3))
            color = [round(r, 3), round(g, 3), round(b, 3)]
            if _is_gray_rgb((r, g, b), tol=0.08) and GRAY_LO < g < GRAY_HI:
                is_gray_light = True

        # 显式不透明度
        ca = re.search(r"/ca\s+([\d.]+)", stream) or re.search(r"/CA\s+([\d.]+)", obj)
        explicit_opacity = float(ca.group(1)) if ca else None

        subtype = _artifact_subtype(page, doc, name)
        angle = _cm_angle(page, doc, name)
        area = _area_of(bbox, page_h) if bbox else "unknown"
        text_hint = _xobject_text_hint(stream)
        # 提取数字签名时先去掉十六进制字形码 <...>，避免污染
        clean_hint = re.sub(r"<[^>]*>", "", text_hint)

        out.append({
            "name": name,
            "xref": xref,
            "color": color,
            "is_gray_light": is_gray_light,
            "explicit_opacity": explicit_opacity,
            "subtype": subtype,
            "bbox": list(bbox) if bbox else None,
            "area": area,
            "angle": angle,
            "text": text_hint,
            "digits": _digits(clean_hint),
            "pno": pno,
            "stream": stream[:600],
        })
    return out


def _analyze_text(doc, page, pno, page_h):
    """路径 A-2：文本层检测 — 浅色 / 低不透明度的重复文字。"""
    out = []
    try:
        td = page.get_text("dict")
    except Exception:
        return out
    for blk in td.get("blocks", []):
        if blk.get("type") != 0:
            continue
        for ln in blk.get("lines", []):
            for sp in ln.get("spans", []):
                rgb = _decode_color(sp.get("color"))
                alpha = sp.get("alpha")
                if rgb is None:
                    continue
                is_light = _is_gray_rgb(rgb) and LIGHT_RGB_MIN < rgb[0] < LIGHT_RGB_MAX
                low_op = isinstance(alpha, (int, float)) and 0 < alpha < 0.85
                if not (is_light or low_op):
                    continue
                out.append({
                    "text": sp.get("text", ""),
                    "rgb": list(rgb),
                    "alpha": alpha,
                    "bbox": list(sp.get("bbox", [])),
                    "area": _area_of(sp.get("bbox"), page_h),
                    "pno": pno,
                    "is_light": is_light,
                    "low_opacity": low_op,
                    "digits": _digits(sp.get("text", "")),
                })
    return out


def _analyze_pixel(page, page_h, page_w):
    """路径 B：像素级检测（扫描 / 图片融合型兜底）。"""
    try:
        import numpy as np
        from scipy import ndimage
    except Exception:
        return {"has_pattern": False, "reason": "numpy/scipy 不可用"}
    try:
        z = 1.5
        pix = page.get_pixmap(matrix=fitz.Matrix(z, z))
        if pix.n < 3:
            return {"has_pattern": False}
        arr = np.frombuffer(pix.samples, dtype=np.uint8)
        arr = arr.reshape(pix.height, pix.width, pix.n)[:, :, :3].astype(int)
        r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
        mask = (abs(r - g) < 30) & (abs(g - b) < 30) & (r > 120) & (r < 235)
        frac = float(mask.mean())
        if frac < 0.004:
            return {"has_pattern": False, "fraction": frac}
        lab, n = ndimage.label(mask)
        if n == 0:
            return {"has_pattern": False, "fraction": frac}
        coords = np.argwhere(lab > 0)
        y0, x0 = coords.min(0)
        y1, x1 = coords.max(0)
        bbox_page = [x0 / z, y0 / z, x1 / z, y1 / z]
        comp_sizes = ndimage.sum(np.ones_like(lab), lab, range(1, n + 1))
        big = int((comp_sizes > (0.0008 * pix.width * pix.height)).sum())
        return {
            "has_pattern": True,
            "fraction": round(frac, 4),
            "components": int(n),
            "tiled": int(n) > 8,
            "bbox": [round(v, 1) for v in bbox_page],
        }
    except Exception as e:
        return {"has_pattern": False, "reason": str(e)}


# ---------------------------------------------------------------------------
# 分类决策（核心：区分水印 / 推广 / 正常页眉页脚 / 正常图形）
# ---------------------------------------------------------------------------

def _classify(el):
    """
    输入一个归一化元素 dict，返回类型字符串：
      'watermark' | 'promo' | 'normal_header_footer' | 'graphic'
    """
    subtype = el.get("subtype")
    area = el.get("area")
    is_gray = el.get("is_gray_light", False)
    angle = el.get("angle", 0.0) or 0.0
    rotated = abs(angle) > 5
    promo = el.get("promo_hit", False)
    normal_hf = el.get("normal_hf_hit", False)
    in_margin = area in ("header", "footer") or subtype in ("Header", "Footer")

    # 1) 显式水印标记
    if subtype == "Watermark":
        return "watermark"
    # 2) 页眉/页脚区域
    if in_margin:
        if promo:
            return "promo"
        if normal_hf:
            return "normal_header_footer"
        # 页边区域、非广告、非页码 → 视为正常图形（如边角 Logo），不报水印
        return "graphic"
    # 3) 正文区：灰度或旋转 → 水印
    if (is_gray or rotated) and area in ("center", "side", "unknown"):
        return "watermark"
    # 4) 灰度 + 广告关键词 → 推广
    if is_gray and promo:
        return "promo"
    # 5) 其它（非灰度、无标记的普通图形/图片）→ 非水印
    return "graphic"


# ---------------------------------------------------------------------------
# 跨页聚合
# ---------------------------------------------------------------------------

def _aggregate_xobjects(xobj_all, total_pages, page_texts, readable_map):
    """按 (内容签名 + 颜色 + 语义) 跨页聚合，输出去重后的元素列表。

    page_texts: 每页纯文本（用于页眉/页脚推广关键词判定）
    readable_map: {数字签名: 可读文本}，用于把 XObject 水印的十六进制内容
                  替换为页面文本层里的可读文字
    """
    groups = defaultdict(list)
    for x in xobj_all:
        sig = (
            (x.get("text") or "")[:30],
            tuple(x.get("color") or (None, None, None)),
            x.get("subtype"),
            x.get("area"),
        )
        groups[sig].append(x)

    result = []
    for sig, items in groups.items():
        rep = items[0]
        pages_set = {it["pno"] for it in items}
        cnt = len(pages_set)
        # 标签：优先用整页文本里的推广关键词（XObject 内容为十六进制时也能命中）
        txt = rep.get("text", "")
        page_has_promo = any(_contains_promo(page_texts[it["pno"]]) for it in items
                             if it["pno"] < len(page_texts))
        rep["promo_hit"] = page_has_promo or _contains_promo(txt)
        rep["normal_hf_hit"] = _looks_like_normal_header(txt)
        # 用可读文本替换十六进制水印内容
        d = rep.get("digits", "")
        if d and d in readable_map:
            txt = readable_map[d]
            rep["text"] = txt
        wtype = _classify(rep)
        tiled = _is_tiled_in_stream(rep.get("stream", ""))
        repeated = cnt >= max(MIN_REP_PAGES, int(REP_RATIO * total_pages))

        op = rep.get("explicit_opacity")
        translucent = rep.get("is_gray_light", False)
        area = rep.get("area")
        angle = rep.get("angle", 0.0) or 0.0
        if wtype == "watermark" and abs(angle) > 5:
            area = "center"  # 旋转斜向水印通常铺满页面中部

        # 推广内容若为十六进制字形码，给出可读标签
        if wtype == "promo" and ("<" in txt or ">" in txt):
            region = "页眉" if area == "header" else ("页脚" if area == "footer" else "页边")
            txt = region + "推广文字（公众号/二维码等）"

        result.append({
            "source": "xobject",
            "name": rep.get("name"),
            "type": wtype,
            "is_watermark": wtype in ("watermark",),
            "is_promo": wtype == "promo",
            "subtype_tag": rep.get("subtype"),
            "color": rep.get("color"),
            "opacity": op,
            "translucent": translucent,
            "rotation_deg": angle,
            "position": {"area": area, "bbox": rep.get("bbox")},
            "content": txt if txt else "(图案/图片)",
            "digits": rep.get("digits", ""),
            "repetition": {
                "appears_on_pages": cnt,
                "total_pages": total_pages,
                "repeated_across_pages": repeated,
                "pattern": "tiled" if tiled else ("per-page" if cnt > 1 else "single"),
            },
            "confidence": 0.97 if rep.get("subtype") == "Watermark"
                          else (0.92 if translucent else (0.7 if wtype == "promo" else 0.5)),
        })
    return result


def _aggregate_text(text_all, total_pages, xobj_digits_set):
    """文本层聚合，并去除已被 XObject 覆盖的重复项。"""
    groups = defaultdict(list)
    for t in text_all:
        groups[(t.get("text") or "").strip()].append(t)

    result = []
    for txt, items in groups.items():
        if not txt:
            continue
        rep = items[0]
        pages_set = {it["pno"] for it in items}
        cnt = len(pages_set)
        if cnt < max(2, int(0.3 * total_pages)):
            continue  # 仅在极少数页出现 → 不视为规律性水印

        # 去重：若其数字签名已被某 XObject 覆盖 → 跳过（同一水印的两种提取方式）
        d = rep.get("digits", "")
        if d and any(d in xd for xd in xobj_digits_set if xd):
            continue

        rep["promo_hit"] = _contains_promo(txt)
        rep["normal_hf_hit"] = _looks_like_normal_header(txt)
        # 文本层元素无 subtype/angle，构造最小字段供 _classify
        el = {
            "subtype": None,
            "area": rep.get("area"),
            "is_gray_light": rep.get("is_light", False),
            "angle": 0.0,
            "promo_hit": rep["promo_hit"],
            "normal_hf_hit": rep["normal_hf_hit"],
        }
        wtype = _classify(el)
        if wtype in ("graphic", "normal_header_footer"):
            # 文本层里这些通常已被 XObject 路径处理；无 XObject 时也仅作参考
            if wtype == "normal_header_footer":
                result.append({
                    "source": "text-layer", "type": wtype, "is_watermark": False,
                    "is_promo": False, "content": txt, "position": {"area": rep.get("area")},
                    "repetition": {"appears_on_pages": cnt, "total_pages": total_pages},
                    "confidence": 0.5,
                })
            continue

        result.append({
            "source": "text-layer",
            "type": wtype,
            "is_watermark": wtype == "watermark",
            "is_promo": wtype == "promo",
            "color": rep.get("rgb"),
            "opacity": None,
            "translucent": rep.get("is_light", False) or rep.get("low_opacity", False),
            "rotation_deg": 0.0,
            "position": {"area": rep.get("area"), "sample_bbox": rep.get("bbox")},
            "content": txt,
            "repetition": {
                "appears_on_pages": cnt,
                "total_pages": total_pages,
                "repeated_across_pages": cnt >= max(2, int(0.3 * total_pages)),
                "pattern": "fixed-position" if len({it.get("area") for it in items}) <= 2 else "scattered",
            },
            "confidence": 0.85 if (rep.get("is_light") or rep.get("low_opacity")) else 0.6,
        })
    return result


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def detect_watermark(path, sample=None):
    """分析 PDF，返回水印检测结果 dict。"""
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    doc = fitz.open(path)
    total = doc.page_count
    page_idx = list(range(total)) if sample is None else list(range(min(sample, total)))

    xobj_all, text_all, pixel_all = [], [], []
    page_texts = []
    text_len_total = 0
    for pno in page_idx:
        page = doc[pno]
        ph = page.rect.height
        xobj_all.extend(_analyze_xobjects(doc, page, pno, ph))
        text_all.extend(_analyze_text(doc, page, pno, ph))
        pixel_all.append(_analyze_pixel(page, ph, page.rect.width))
        pt = page.get_text()
        page_texts.append(pt)
        text_len_total += len(pt)
    doc.close()

    n_pages = len(page_idx)
    avg_text = (text_len_total / n_pages) if n_pages else 0
    is_scanned = avg_text < 20  # 平均每页文字极少 → 视为扫描/图片融合型

    # 数字签名 → 可读文本（用于还原 XObject 水印的可读内容）
    readable_map = {}
    for t in text_all:
        d = t.get("digits", "")
        if d and t.get("text"):
            readable_map.setdefault(d, t["text"])

    xobj_groups = _aggregate_xobjects(xobj_all, total, page_texts, readable_map)
    xobj_digits_set = {g.get("digits", "") for g in xobj_groups}
    text_groups = _aggregate_text(text_all, total, xobj_digits_set)

    watermarks = []
    normal_hf = []
    for g in xobj_groups + text_groups:
        if g["type"] == "normal_header_footer":
            normal_hf.append(g)
        elif g["type"] in ("watermark", "promo"):
            watermarks.append(g)
        # 'graphic' 类型直接丢弃（正常图片/Logo，非水印）

    # 像素级兜底（仅对扫描/图片融合型、且矢量路径无任何发现时触发，避免分层文档误报）
    pixel_hits = [p for p in pixel_all if p.get("has_pattern")]
    pixel_items = []
    if pixel_hits and not watermarks and is_scanned:
        rel_centers = []
        for p in pixel_hits:
            bb = p.get("bbox")
            if bb:
                rel_centers.append(((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2))
        repeated = len(pixel_hits) >= max(MIN_REP_PAGES, int(REP_RATIO * total))
        tiled = any(p.get("tiled") for p in pixel_hits)
        rep_p = pixel_hits[0]
        pixel_items.append({
            "source": "pixel",
            "type": "watermark",
            "is_watermark": True,
            "is_promo": False,
            "color": [200, 200, 200],
            "opacity": None,
            "translucent": True,
            "rotation_deg": 0.0,
            "position": {"area": "background", "bbox": rep_p.get("bbox")},
            "content": "(灰度平铺图案)",
            "repetition": {
                "appears_on_pages": len(pixel_hits),
                "total_pages": total,
                "repeated_across_pages": repeated,
                "pattern": "tiled" if tiled else "per-page",
            },
            "confidence": 0.8,
        })
        watermarks.extend(pixel_items)

    has_watermark = any(w["is_watermark"] for w in watermarks)
    has_promo = any(w["is_promo"] for w in watermarks)

    conf = 0.0
    for w in watermarks:
        conf = max(conf, w.get("confidence", 0))
    if not watermarks:
        conf = 1.0 if not pixel_hits else 0.8

    summary = _build_summary(watermarks, normal_hf, total, n_pages)

    return {
        "file": os.path.abspath(path),
        "has_watermark": has_watermark or has_promo or bool(pixel_items),
        "has_promo": has_promo,
        "confidence": round(conf, 2),
        "page_count": total,
        "analyzed_pages": n_pages,
        "doc_type": "scanned" if is_scanned else "layered",
        "watermarks": watermarks,
        "normal_header_footer": normal_hf,
        "summary": summary,
    }


def _build_summary(watermarks, normal_hf, total, n_pages):
    if not watermarks and not normal_hf:
        return "未检测到水印或覆盖物（判定为无水印）。"
    lines = []
    wm = [w for w in watermarks if w["is_watermark"]]
    pr = [w for w in watermarks if w["is_promo"]]
    if wm:
        lines.append("检测到水印（%d 种）：" % len(wm))
        for w in wm:
            lines.append("  • " + _describe(w))
    if pr:
        lines.append("检测到推广覆盖物（%d 种，非正文、建议去除）：" % len(pr))
        for w in pr:
            lines.append("  • " + _describe(w))
    if normal_hf:
        names = sorted({h.get("content", "")[:24] for h in normal_hf if h.get("content")})
        if names:
            lines.append("正常页眉/页脚（已排除，非水印）：%s" % "、".join(names))
    return "\n".join(lines)


def _describe(w):
    t = w.get("type")
    src = w.get("source")
    content = (w.get("content") or "").strip() or "(图案/图片)"
    pos = w.get("position", {})
    area = pos.get("area")
    rep = w.get("repetition", {})
    op = w.get("opacity")
    op_s = (" 不透明度=%.2f" % op) if isinstance(op, (int, float)) else ""
    trans = " 半透明" if w.get("translucent") else ""
    rot = w.get("rotation_deg") or 0
    rot_s = (" 旋转%d°" % rot) if abs(rot) > 1 else ""
    return "[%s/%s] 内容=%r 位置=%s 重复=%s(%d/%d页)%s%s%s" % (
        t, src, content[:40], area, rep.get("pattern"), rep.get("appears_on_pages", 0),
        rep.get("total_pages", 0), op_s, trans, rot_s,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="PDF 水印自动检测")
    ap.add_argument("input", help="PDF 文件路径")
    ap.add_argument("-o", "--output", help="将 JSON 报告写入该文件")
    ap.add_argument("--json", action="store_true", help="以 JSON 格式输出")
    ap.add_argument("--sample", type=int, default=None, help="仅分析前 N 页（默认全部）")
    args = ap.parse_args()

    try:
        result = detect_watermark(args.input, sample=args.sample)
    except Exception as e:
        print("检测失败: %s" % e, file=sys.stderr)
        sys.exit(1)

    if args.json:
        text = json.dumps(result, ensure_ascii=False, indent=2)
    else:
        text = "文件: %s\n" % result["file"]
        text += "页码: %d（分析 %d 页）\n" % (result["page_count"], result["analyzed_pages"])
        text += "结论: %s\n" % ("含推广覆盖物" if result["has_promo"]
                                else ("含水印" if result["has_watermark"] else "无水印"))
        text += "置信度: %.2f\n" % result["confidence"]
        text += "\n" + result["summary"]

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False, indent=2))
        print("报告已写入: %s" % args.output)
    else:
        print(text)


if __name__ == "__main__":
    main()
