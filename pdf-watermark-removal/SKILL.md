---
name: pdf-watermark-removal
version: "2.2"
description: "PDF去水印工具 - 支持分层型Form XObject无损删除与扫描件像素法；含水印自动检测（类型/位置/透明度/重复模式）"
author: WorkBuddy AI
trigger:
  - "去水印"
  - "清理水印"
  - "PDF去水印"
  - "检测水印"
  - "识别水印"
  - "remove watermark"
  - "watermark removal"
  - "detect watermark"
---

# PDF 去水印 Skill

## ⚠️ 底层强制规则 (不可违背)

### 规则0: 先分类，再选策略 — 这是最高优先级
处理任何 PDF 前，**必须先判断其类型**，选择对应策略，禁止一刀切用同一种方法：

```
┌──────────────────────┐
│  输入 PDF 文件        │
└──────────┬───────────┘
           ▼
  ┌─────────────────┐
  │ 第1页 get_text() │ ──→ 文本可提取(词>50) 且 非整页大图？
  │ + get_images()  │ + get_xobjects()
  └────────┬────────┘
           ├─ 是 ──▶ 【分层/矢量型】→ 按优先级尝试以下无损方法：
           │
           │   ★★★ 第一步（首选）：Form XObject 删除法（规则0.5）
           │     page.get_xobjects() → 找 Form 子类型 XObject
           │       ├─ 灰色/彩色填充 = 水印 → 删除其 Do 的 BDC...EMC 整块
           │       └─ 黑字 + 页眉/页脚位置(f<7%H 或 f>93%H) = 推广 → 同上删
           │     save(garbage=4, deflate=True) 清理未引用对象
           │     ✅ 正文完整、文本可选、文件缩小、零残影、毫秒级
           │     ❗ 绝大多数公众号PDF的水印都是这种结构！
           │
           │   ★★ 第二步：inline 文本 span redact（谨慎用）
           │     get_text("dict") 找水印文字块 → add_redact_annot(bbox) → apply_redactions()
           │     ⚠️ 仅当水印 bbox 不与正文重叠时安全；重叠会误伤正文！
           │
           │   ★ 第三步（兜底）：像素法
           │     渲染→灰度检测→连通域保护→JPEG压缩回写
           │     ⚠️ 会丢失文本可选性，仅当上述两步均不可用时使用
           │
           └─ 否(纯图/扫描件) ──▶ 【扫描/图片融合型】→ 像素级灰色斜铺法
                              - 渲染高分辨率图像 → RGB灰度检测 → 连通域保护 → JPEG压缩
                              - 仅当水印融合在图片像素中时才使用此法
```

**判断标准**:
- **分层型**: `len(page.get_text().strip()) > 50` 且 无整页大图(>80%面积)
- **扫描型**: 文本词数极少(<10) 且 整页被大图覆盖

### 规则0.5（新增核心）：Form XObject 无损删除法 — 分层型首选
这是处理**公众号导出PDF、WPS生成PDF等"有文本层+Form水印"**文件的**唯一正确方法**。
**教训**：曾因不知道水印藏在 Form XObject 中而错误地走像素法，导致：
  - 文本层被毁（正文无法选中复制） ← 最严重问题
  - 留下极淡残影（像素法精度限制）
  - 黑色推广文字未处理（灰度检测只覆盖灰色）
  - 文件体积反而增大

**操作流程**（每页循环，已固化在 `scripts/remove_watermark.py`）：
```python
def is_gray_form(c):  # 灰度填充检测
    return any(0.12 < v < 0.9 for v in gray_op(c))  # 0.5 0.5 0.5 rg 等
def is_text_form(c):  # 文本对象
    return 'BT' in c and 'ET' in c
for page in doc.pages:
    xobjs = page.get_xobjects()          # [(xref, name, ...)]
    remove_names = set()
    for (xref, name, *rest) in xobjs:
        if '/Form' not in doc.xref_object(xref): continue
        content = doc.xref_stream(xref).decode('latin-1')
        cm_f = last_cm_translate_y(page_stream, name)   # 该Do的平移y
        if is_gray_form(content):            remove_names.add(name)  # 水印
        elif is_text_form(content) and (cm_f < 0.07*H or cm_f > 0.93*H):
            remove_names.add(name)          # 推广(页眉/页脚)
    page_stream = strip_artifact(page_stream, remove_names)  # 删 BDC...EMC 整块
doc.save(outpath, garbage=4, deflate=True, clean=True)
```
> 关键点：删除的是**整个水印绘制指令**，正文对象字节级不受影响；正文与图片（Image XObject）完全不动。

**为什么比 redact 更好？**
- redact 是矩形区域擦除，水印 bbox 与正文重叠时会误伤正文（本例水印 bbox 覆盖了引用段落）
- Form XObject 删除是**对象级别**的——只移除水印绘制指令，正文对象的每个字节都 untouched

### 规则1: 输出文件大小必须受控
   - 输出文件大小**不得超过源文件的 1.5 倍**，理想情况应接近或小于源文件。
   - **绝对禁止使用无损PNG合成PDF**（会导致体积暴增数倍，如 19MB→129MB）。
   - 必须使用 **JPEG压缩**（质量80，可通过 `--quality` 调整 1-100）。
   - PDF保存时必须使用 `garbage=4, deflate=True` 压缩。
   - 处理前先记录源文件大小，处理后对比，超标必须重处理。
2. **先分析水印像素颜色，再处理** — 禁止凭经验假设水印颜色（曾误判灰色为粉色导致失败）。
3. **保持排版与内容完整** — 去水印后文字清晰可辨，图片主体不被误删。
4. **输出文件名** — 原文件名 + `_无水印` 后缀，输出到源文件同目录。

## 功能概述
去除PDF文件中的水印，支持多种水印类型。

## 触发关键词
- **中文**: "去水印"、"清理水印"、"去除水印"、"PDF去水印"、"去掉水印"
- **英文**: "remove watermark", "watermark removal"

## 支持的水印类型

### 1. 灰色斜向平铺文字 (默认模式 `--mode gray`)
最常见的类型，特征：
- 浅灰色/半透明灰色文字
- 斜向排列（通常从左下到右上，约45度）
- 平铺覆盖整个页面或大部分区域
- 典型内容："+助理微信，xxx入群"、公众号名、日期等
- **检测原理**: RGB三通道值接近（差异<30）且亮度在120-240之间
- **⚠️ 内容保护**: 使用**连通域面积过滤**自动区分「水印(细小笔画)」与「图片内容(大块灰色)」，
  大面积灰色连通域（>0.08%图像占比）会被保留，避免误删图片中的灰色区域

**典型参数**: `--mode gray` (默认, 自动启用内容保护)

### 2. 彩色水印 (`--mode color`)
特征：
- 粉色/红色/蓝色等有颜色的文字或图案
- 通常位于页面顶部、底部或边缘
- 典型场景：微信截图的粉色"xxx付费群"标题和日期
- **检测原理**: RGB阈值匹配（如 R>180, G<120, B<130 为粉色）

**典型参数**: `--mode color --rmin 180 --gmax 120 --bmax 130`

## 使用方法

### 在WorkBuddy对话中触发
当用户说"去水印"并提供PDF路径时，自动处理。

### 命令行使用

**首选主脚本 `remove_watermark.py`（自动分类 + Form XObject 无损优先）：**
```bash
# 自动分类 + 智能去水印（推荐，单文件或目录均可）
python remove_watermark.py input.pdf
python remove_watermark.py ./pdfs/

# 仅用 Form XObject 无损法（调试/确认分层结构时用）
python remove_watermark.py input.pdf --mode form

# 强制像素法（扫描件或兜底调试）
python remove_watermark.py input.pdf --mode gray --quality 80
python remove_watermark.py input.pdf --mode color --rmin 180 --gmax 120 --bmax 130

# 指定输出路径 / 目录
python remove_watermark.py input.pdf -o output/clean.pdf
```

**水印自动检测 `detect_watermark.py`（去水印前先判断，或独立使用）：**
```bash
python detect_watermark.py input.pdf                 # 人类可读结论（是否含水印/推广）
python detect_watermark.py input.pdf --json -o report.json   # 结构化 JSON 报告
python detect_watermark.py input.pdf --sample 5      # 仅分析前 5 页（提速）
```
返回：是否含水印 (`has_watermark`)、是否含推广 (`has_promo`)、置信度、文档类型
(`layered`/`scanned`)、以及每种水印的属性（位置/透明度/旋转角/重复模式/内容）。

**老脚本 `pdf_watermark.py`（纯像素法，仅扫描件/调试用）：**
```bash
python pdf_watermark.py input.pdf --mode gray
python pdf_watermark.py input.pdf --mode gray --gray-min 80 --gray-max 230
python pdf_watermark.py input.pdf --mode color --rmin 180 --gmax 120 --bmax 130
```

## 水印自动检测能力 (detect_watermark.py)

在去水印之前（或独立审计）可先**自动检测** PDF 是否含水印、水印类型与属性。覆盖四类分辨逻辑：

1. **背景层重复半透明文字/图案** — 解析 Form XObject，识别灰度填充 (`0.5 0.5 0.5 rg`) 或带 `/Subtype /Watermark` 标记的对象，并跨页统计出现次数判断重复性。
2. **覆盖正文上方、与正文无关的重复元素** — 同一 XObject 在每页以相同内容/位置出现（跨页配准），且与正文文本无关 → 判为水印/推广覆盖物。
3. **固定位置浅色/低不透明图形** — 页眉/页脚区域 (`y<7%H` 或 `y>93%H`) 或带旋转 (`角度>5°`) 的浅色图形；正文区中灰度或旋转的浅色元素 → 水印。
4. **区分水印与正常页眉页脚** — 页眉/页脚 XObject 若含推广关键词（公众号/二维码/入群等）判为 `promo`；若仅为页码/文档标题（如「第 3 页」）判为 `normal_header_footer` 并**排除**出「水印」结论；其它非灰度、无标记的普通图形（Logo/图片）判为 `graphic`，不报水印。

**路径**：矢量/分层型走 Form XObject + 文本层分析（首选）；扫描/图片融合型走像素级灰度检测（仅当 `doc_type==scanned` 时触发，避免分层文档误报）。

**输出结构**（`detect_watermark(path) -> dict`）：
- `has_watermark` / `has_promo` (bool)、`confidence` (0~1)、`doc_type` (`layered`/`scanned`)
- `watermarks`: 去重后的明细列表，每项含
  - `type`: `watermark` | `promo`
  - `source`: `xobject` | `text-layer` | `pixel`
  - `position`: `{area, bbox}`（area ∈ header / footer / center / side）
  - `opacity` / `translucent`（半透明感）
  - `rotation_deg`（旋转角，斜向水印的特征）
  - `content`: 可读文字（如「进圈加v：3030423182」）或「(页眉推广文字)」等
  - `repetition`: `{appears_on_pages, total_pages, repeated_across_pages, pattern}`
    （pattern ∈ per-page / tiled / single / fixed-position）
- `normal_header_footer`: 被明确排除的正常页眉页脚

## 技术方案

```
输入 PDF
   │
   ▼ 规则0: 分类
┌─────────────────────────────────────┐
│ 第1页 get_text() > 50 字 且 非整页大图? │
└──────────────────┬──────────────────┘
                   ├─ 是(LAYERED) ──▶ 规则0.5 首选: Form XObject 无损删除
                   │                  page.get_xobjects()
                   │                    ├ 灰度填充 Form → 水印 → 删 Do 的 BDC..EMC
                   │                    └ 黑字+页眉/页脚 Form → 推广 → 同上删
                   │                  save(garbage=4, deflate, clean)
                   │                  ✅ 正文/图片毫发无损、文本可选、体积更小
                   │                  └ 若无 XObject 目标 → inline text redact 兜底
                   │
                   └─ 否(SCANNED) ──▶ 像素法兜底（仅扫描件/图片融合水印）
                                      渲染→RGB灰度/彩色检测→连通域保护→JPEG压缩
                                      ⚠️ 会丢失文本可选性，体积需控 ≤1.5x
```

## 参数参考表

| 模式 | 参数 | 说明 | 推荐值 |
|------|------|------|--------|
| gray | `--gray-min` | 最小亮度 | 120 (浅灰), 80 (深灰) |
| gray | `--gray-max` | 最大亮度 | 240 |
| gray | `--gray-diff` | RGB最大差值 | 30 (严格), 45 (宽松) |
| color | `--rmin` | R通道最小值 | 180 (粉色) |
| color | `--gmax` | G通道最大值 | 120 (粉色) |
| color | `--bmax` | B通道最大值 | 130 (粉色) |

## 注意事项
1. **文件大小**: 必须 ≤ 源文件1.5倍，用JPEG压缩（禁止PNG）；详见"底层强制规则"
2. 输出文件名为原文件名 + `_无水印`
3. 处理基于图像像素替换，对纯图片页面可能有轻微影响
4. 对于包含大量自然灰度的照片页面，建议适当收紧参数
5. 首次使用建议先处理单页预览效果

## 参考项目
- https://github.com/ben0i0d/Remove-Watermark (RGB像素替换法)
- https://github.com/zuruoke/watermark-removal (深度学习图像修复)
