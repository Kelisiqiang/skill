#!/usr/bin/env python3
"""
PDF去水印工具
参考GitHub项目: 
  - https://github.com/ben0i0d/Remove-Watermark (RGB像素替换法)
  - https://github.com/zuruoke/watermark-removal (深度学习图像修复)

技术方案: 将PDF转为图像，通过像素颜色特征检测水印并替换为白色

支持的水印类型:
  1. 彩色水印 -- 基于RGB阈值(如粉色、红色)
  2. 灰色水印 -- 基于RGB接近度+亮度范围(如浅灰色斜向平铺文字)
  3. 深色水印 -- 低亮度灰色文字
"""

import os
import sys
import io
import argparse
from pathlib import Path

try:
    import fitz
except ImportError:
    print("错误: 请安装 PyMuPDF")
    print("运行: pip install PyMuPDF")
    sys.exit(1)

try:
    import numpy as np
    from PIL import Image
except ImportError:
    print("错误: 请安装依赖")
    print("运行: pip install numpy Pillow")
    sys.exit(1)


def remove_color_watermark(img, rmin=175, rmax=255, gmax=175, bmax=175):
    """彩色水印去除 (如粉色/红色水印)"""
    r_ch = img[:,:,0].astype(np.int16)
    g_ch = img[:,:,1].astype(np.int16)
    b_ch = img[:,:,2].astype(np.int16)
    
    mask = (r_ch >= rmin) & (r_ch <= rmax) & (g_ch <= gmax) & (b_ch <= bmax)
    img[mask] = [255, 255, 255]
    return int(np.sum(mask))


def remove_gray_watermark(img, min_brightness=120, max_brightness=240, max_diff=30,
                          max_area_ratio=0.0008, use_protection=True):
    """灰色水印去除 (浅灰色/半透明斜向平铺文字) + 连通域保护
    
    核心改进: 通过连通域面积分析区分「水印(细小文字笔画)」与「图片内容(大块灰色区域)」
    
    参数:
        min_brightness: 最小亮度(0-255), 低于此值视为黑色文字保留
        max_brightness: 最大亮度(0-255), 高于此值视为背景白
        max_diff: RGB三通道最大差值, 越小越严格
        max_area_ratio: 连通域面积占图像比例阈值, 超过此值的连通域视为图片内容而保留
                       (默认0.0008即0.08%, 约1600像素@2x zoom的1190x1682图像)
        use_protection: 是否启用连通域保护 (默认True)
    """
    from scipy import ndimage
    
    r_ch = img[:,:,0].astype(np.int16)
    g_ch = img[:,:,1].astype(np.int16)
    b_ch = img[:,:,2].astype(np.int16)
    
    rg_diff = np.abs(r_ch - g_ch)
    rb_diff = np.abs(r_ch - b_ch)
    gb_diff = np.abs(g_ch - b_ch)
    avg_val = (r_ch + g_ch + b_ch) / 3
    
    # 第一步: 颜色检测找到所有灰色候选像素
    raw_mask = (rg_diff < max_diff) & (rb_diff < max_diff) & (gb_diff < max_diff) & \
               (avg_val > min_brightness) & (avg_val < max_brightness)
    
    total_gray = int(np.sum(raw_mask))
    
    if total_gray < 100:
        return total_gray
    
    if not use_protection or 'ndimage' not in dir():
        # 无保护模式: 直接全部替换
        img[raw_mask] = [255, 255, 255]
        return total_gray
    
    # 第二步: 连通域分析
    labeled_array, num_features = ndimage.label(raw_mask)
    component_sizes = ndimage.sum(raw_mask, labeled_array, range(1, num_features + 1))
    img_area = img.shape[0] * img.shape[1]
    
    # 找出「大块」连通域 → 视为图片内容，排除不删
    large_components = set()
    for comp_id in range(1, num_features + 1):
        size_ratio = component_sizes[comp_id - 1] / img_area
        if size_ratio > max_area_ratio:
            large_components.add(comp_id)
    
    # 第三步: 构建最终掩码（只删除小块连通域 = 水印）
    final_mask = raw_mask.copy()
    protected_count = 0
    for comp_id in large_components:
        final_mask[labeled_array == comp_id] = False
        protected_count += int(component_sizes[comp_id - 1])
    
    removed_count = int(np.sum(final_mask))
    
    img[final_mask] = [255, 255, 255]
    print(f"    灰色总{total_gray} → 删除{removed_count}(水印) 保护{protected_count}(内容)")
    
    return removed_count


def process_pdf(input_path, output_path, mode='gray', zoom=2,
                # 彩色模式参数
                rmin=175, rmax=255, gmax=175, bmax=175,
                # 灰色模式参数
                gray_min=120, gray_max=240, gray_diff=30,
                # 保护参数
                max_area_ratio=0.0008,
                # 压缩参数
                jpeg_quality=80):
    """处理单个PDF文件 (使用JPEG压缩控制输出大小)"""
    
    print(f"\n处理: {input_path}")
    print(f"模式: {mode}")
    
    doc = fitz.open(input_path)
    new_doc = fitz.open()
    total_pages = len(doc)
    print(f"总页数: {total_pages}")
    
    for page_num in range(total_pages):
        page = doc[page_num]
        
        # 渲染为高分辨率图像
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = np.frombuffer(buffer=pix.samples, dtype=np.uint8).reshape(
            (pix.h, pix.w, -1)
        ).copy()
        
        # 根据模式选择去水印算法
        if mode == 'color':
            modified = remove_color_watermark(img, rmin, rmax, gmax, bmax)
        elif mode == 'gray':
            modified = remove_gray_watermark(
                img, gray_min, gray_max, gray_diff,
                max_area_ratio=max_area_ratio
            )
        else:
            print(f"  未知模式: {mode}")
            continue
        
        if modified > 100:
            print(f"  第{page_num+1}页: 替换 {modified} 个像素")
        
        # 转为PIL图像
        if img.shape[2] == 4:
            pil = Image.fromarray(img, 'RGBA').convert('RGB')
        else:
            pil = Image.fromarray(img, 'RGB')
        
        # JPEG压缩写入内存，直接插入PDF（不写临时文件）
        buf = io.BytesIO()
        pil.save(buf, format='JPEG', quality=jpeg_quality, optimize=True)
        buf.seek(0)
        
        # 保持原始页面尺寸
        rect = page.rect
        new_page = new_doc.new_page(width=rect.width, height=rect.height)
        new_page.insert_image(new_page.rect, stream=buf.getvalue())
    
    # 使用garbage和deflate压缩PDF
    new_doc.save(output_path, garbage=4, deflate=True)
    new_doc.close()
    doc.close()
    
    out_size_mb = os.path.getsize(output_path) / 1024 / 1024
    print(f"\n✓ 输出: {output_path} ({out_size_mb:.1f} MB)")
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description='PDF去水印工具 - 支持多种水印类型',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
╔══════════════════════════════════════════════════╗
║              PDF Watermark Remover               ║
║                                                  ║
║  模式说明:                                        ║
║  gray  - 浅灰色斜向平铺文字 (默认,最常用)         ║
║  color - 彩色水印 (粉色/红色等)                   ║
║                                                  ║
║  典型场景参数:                                     ║
║  微信截图灰色水印: --mode gray                    ║
║  微信截图粉色水印: --mode color --rmin 180        ║
║                     --gmax 120 --bmax 130         ║
║  深灰水印:       --mode gray --gray-min 80        ║
╚══════════════════════════════════════════════════╝

示例:
  # 灰色斜向水印 (最常见)
  python pdf_watermark.py input.pdf --mode gray

  # 自定义灰色范围
  python pdf_watermark.py input.pdf --mode gray --gray-min 100 --gray-max 235

  # 粉色水印
  python pdf_watermark.py input.pdf --mode color --rmin 180 --gmax 120 --bmax 130

  # 高质量输出
  python pdf_watermark.py input.pdf --zoom 3
        """
    )
    
    parser.add_argument('source', help='输入PDF文件路径')
    parser.add_argument('-o', '--output', help='输出PDF路径 (默认: 同目录_无水印)')
    parser.add_argument('--mode', default='gray', choices=['gray', 'color'],
                        help='水印类型: gray=灰色(默认), color=彩色')
    parser.add_argument('--zoom', type=int, default=2, help='渲染缩放倍数 (默认2, 越大质量越高)')
    parser.add_argument('--quality', type=int, default=80, help='JPEG压缩质量 1-100 (默认80, 越大文件越大)')
    
    # 彩色模式参数
    parser.add_argument('--rmin', type=int, default=175, help='[彩色模式] R通道最小值')
    parser.add_argument('--rmax', type=int, default=255, help='[彩色模式] R通道最大值')
    parser.add_argument('--gmax', type=int, default=175, help='[彩色模式] G通道最大值')
    parser.add_argument('--bmax', type=int, default=175, help='[彩色模式] B通道最大值')
    
    # 灰色模式参数
    parser.add_argument('--gray-min', type=int, default=120, help='[灰色模式] 最小亮度')
    parser.add_argument('--gray-max', type=int, default=240, help='[灰色模式] 最大亮度')
    parser.add_argument('--gray-diff', type=int, default=30, help='[灰色模式] RGB最大差值')
    
    args = parser.parse_args()
    
    # 确定输出路径
    if args.output:
        output_path = args.output
    else:
        src = Path(args.source)
        output_path = str(src.parent / f"{src.stem}_无水印.pdf")
    
    process_pdf(
        input_path=args.source,
        output_path=output_path,
        mode=args.mode,
        zoom=args.zoom,
        rmin=args.rmin, rmax=args.rmax, gmax=args.gmax, bmax=args.bmax,
        gray_min=args.gray_min, gray_max=args.gray_max, gray_diff=args.gray_diff,
        jpeg_quality=args.quality
    )
    
    print("\n完成!")


if __name__ == '__main__':
    main()
