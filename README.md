# PDF 去水印 Skill (pdf-watermark-removal)

智能识别并去除 PDF 中的各类水印。支持**双层处理路径**：分层/矢量型 PDF 直接删除水印对象（无损、毫秒级），扫描/图片融合型 PDF 用像素级算法去除灰色斜铺水印。

---

## ✨ 特性

- 🧠 **自动分类**：先判断 PDF 类型，选对应策略（不是一刀切）
  - **LAYRED（有文本层）** → 直接 `redact` 遮盖水印对象，不损失正文质量
  - **SCANNED（纯图/扫描件）** → 灰度像素检测 + 连通域保护 + JPEG 压缩
- 🖼️ **灰色斜向平铺水印**：浅灰色半透明文字（如 "+助理微信，xxx入群"）精准去除
- 🔍 **连通域面积过滤**：自动区分「水印（细碎笔画）」与「图片内容（大块灰色）」，保护正文图片不被误删
- 📦 **输出体积受控**：强制 JPEG Q80 压缩，输出 ≤ 源文件 1.5 倍
- 🎯 **彩色水印**：支持粉色/红色等彩色水印（RGB 阈值匹配）
- ⚡ **批量处理**：目录批量、自动分类、并发统计

---

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install PyMuPDF Pillow numpy scipy
```

### 2. 命令行用法

```bash
# 默认：自动分类 + 智能去水印
python pdf_watermark.py input.pdf

# 指定输出目录
python pdf_watermark.py input.pdf -o results/

# 彩色水印（粉色，如微信截图标题）
python pdf_watermark.py input.pdf --mode color --rmin 180 --gmax 120 --bmax 130

# 批量处理整个目录
python pdf_watermark.py ./pdfs/
```

### 3. 在 WorkBuddy 对话中触发

当用户说"去水印"、"清理水印"、"去除水印"、"PDF 去水印" 并提供 PDF 路径时，自动处理。

---

## 🧭 双路径工作原理（核心）

```
输入 PDF
   │
   ▼
第1页 get_text() 词数 > 50 且 无整页大图?
   │
   ├─ 是 ──▶ 【分层/矢量型 LAYERED】
   │            • 搜索推广关键词文本块 + 右下角二维码图片
   │            • add_redact_annot() + apply_redactions() 白色遮盖
   │            ✅ 无损、毫秒级、保留排版
   │
   └─ 否 ──▶ 【扫描/图片融合型 SCANNED】
                • 渲染高分辨率图像
                • RGB 灰度检测（三通道接近 + 亮度 120-240）
                • 连通域面积过滤（大块=保留，小块=水印）
                • 白色替换 → JPEG Q80 压缩 → 合成 PDF
```

---

## ⚙️ 命令行参数

| 参数 | 简写 | 默认值 | 说明 |
|------|------|--------|------|
| `source` | - | 必填 | 输入 PDF 文件或目录 |
| `--mode` | - | `gray` | 处理模式：`gray`（灰度）/ `color`（彩色） |
| `--output` | `-o` | 同目录 | 输出目录 |
| `--rmin` | - | 175 | 彩色模式 R 通道最小值 |
| `--rmax` | - | 255 | 彩色模式 R 通道最大值 |
| `--gmax` | - | 175 | 彩色模式 G 通道最大值 |
| `--bmax` | - | 175 | 彩色模式 B 通道最大值 |
| `--gray-min` | - | 120 | 灰度模式最小亮度（浅灰=120，深灰=80） |
| `--gray-max` | - | 240 | 灰度模式最大亮度 |
| `--gray-diff` | - | 30 | 灰度模式 RGB 最大差值（严格=30，宽松=45） |
| `--zoom` | - | 2 | 渲染缩放倍数（1-3，越大越清晰越慢） |
| `--quality` | - | 80 | JPEG 压缩质量（1-100，控制输出体积） |

---

## 📊 实际案例

| 场景 | 类型 | 处理 | 效果 |
|------|------|------|------|
| 微信/QQ 聊天截图（纯图版）| SCANNED | 灰色斜铺像素法 | 斜向灰色水印清除，聊天内容完好 |
| 公众号文章合集（有文本层）| LAYERED | redact 遮盖 | 底部二维码/推广区清除，正文完好 |
| 粉色标题/日期水印 | SCANNED/COLOR | 彩色 RGB 匹配 | 粉色文字替换白色 |

---

## 📁 文件结构

```
pdf-watermark-removal/
├── SKILL.md                    # Skill 定义（含底层强制规则）
├── README.md                   # 本文档
├── _meta.json                  # 元数据
└── scripts/
    ├── pdf_watermark.py        # 主程序（单文件/目录去水印）
    ├── requirements.txt        # Python 依赖
    ├── setup.bat               # Windows 安装脚本
    └── ...（历史版本脚本）
```

---

## 🔧 底层强制规则（不可违背）

1. **先分类，再选策略**（规则 0，最高优先级）
   - LAYERED → 直接删对象；SCANNED → 像素法。禁止一刀切。
2. **输出体积受控**
   - ≤ 源文件 1.5 倍，理想接近或小于源文件
   - 禁止无损 PNG 合成；强制 JPEG Q80 + `garbage=4, deflate=True`
3. **先分析水印像素颜色再处理**——禁止凭经验假设颜色
4. **保持排版与内容完整**
5. **输出命名**：原文件名 + `_无水印`，同目录输出

---

## 📚 参考项目

- **ben0i0d/Remove-Watermark**：https://github.com/ben0i0d/Remove-Watermark（RGB 像素替换法）
- **zuruoke/watermark-removal**：https://github.com/zuruoke/watermark-removal（深度学习图像修复）

---

## 📄 License

MIT
