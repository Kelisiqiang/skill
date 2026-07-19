# -*- coding: utf-8 -*-
"""
智能双路径 PDF 去水印 — 批量处理（目录级封装）

规则0 / 规则0.5：
  LAYERED(有文本层)   → 首选 Form XObject 无损删除（水印+推广），无目标时回退 inline redact
  SCANNED(纯图/扫描件) → 灰度/彩色像素法 + 连通域保护 + JPEG 压缩

本脚本直接复用 remove_watermark.process_file 的统一逻辑，保证与单文件处理一致。
"""
import os
import glob
import sys

# 让本目录可被导入
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from remove_watermark import process_file, classify, _report  # noqa: E402


def main():
    # 默认处理目录（可按需修改，或用命令行传入目录）
    SRC_DIR = os.environ.get(
        'WATERMARK_SRC_DIR',
        'D:/kelisiqing_OB/00.daidai/岱岱专题md/政策文件会议解读合集/重大政策文件解读')

    if len(sys.argv) > 1:
        SRC_DIR = sys.argv[1]

    pdfs = sorted(glob.glob(os.path.join(SRC_DIR, '*.pdf')))
    pdfs = [p for p in pdfs if '_无水印' not in p]

    print(f'目录: {SRC_DIR}')
    print(f'待处理: {len(pdfs)} 个文件\n')

    stats = {'layered_form': 0, 'layered_redact': 0, 'scanned': 0, 'skip': 0, 'err': 0}

    for input_pdf in pdfs:
        base = os.path.splitext(os.path.basename(input_pdf))[0]
        output_pdf = os.path.join(SRC_DIR, base + '_无水印.pdf')
        src_mb = os.path.getsize(input_pdf) / 1024 / 1024
        print(f'\n▶ {os.path.basename(input_pdf)}')
        try:
            # process_file 内部自动分类并选策略；mode=auto 即 Form 优先
            process_file(input_pdf, output_pdf, mode='auto')
            # 统计类型：简单判断输出体积倍率
            out_mb = os.path.getsize(output_pdf) / 1024 / 1024
            stats['layered_form' if out_mb <= src_mb * 1.5 else 'scanned'] += 1
        except Exception as e:
            stats['err'] += 1
            print(f'  ❌ 失败: {e}')

    print('\n' + '-' * 40)
    print('完成!', stats)


if __name__ == '__main__':
    main()
