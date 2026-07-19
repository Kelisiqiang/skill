# PDF 去水印 Skill (pdf-watermark-removal)

智能识别并去除 PDF 中的各类水印。**核心能力**：对「有文本层 + Form 水印」的公众号/文档 PDF，
用 **Form XObject 对象级无损删除**（正文、图片、文本可选性毫发无损，体积反而更小）；对扫描件/图片融合水印，
用像素级灰度/彩色检测兜底（连通域保护 + JPEG 压缩，体积强制 ≤ 源文件 1.5 倍）。

---

## ✨ 特性

- 🧠 **自动分类**：先判 PDF 类型，选对应策略（不一刀切）
  - **LAYERED（有文本层）** → 首选 **Form XObject 无损删除**（毫秒级、零残影、正文完整、文本可选）
  - **SCANNED（纯图/扫描件）** → 像素级灰度/彩色检测 + 连通域保护 + JPEG 压缩
- 🎯 **Form XObject 无损删除**：绝大多数「公众号导出 PDF / WPS 生成 PDF」的水印都是独立可复用对象，
  直接删其绘制指令即可，不伤正文（曾因误判走像素法导致文本层被毁，已修正）
- 🖼️ **灰色斜向平铺水印**：浅灰色半透明文字精准去除（像素法兜底）
- 🔍 **连通域面积过滤**：区分「水印（细碎笔画）」与「图片内容（大块灰色）」，保护正文图片
- 📦 **输出体积受控**：强制 JPEG 压缩 + `garbage=4, deflate=True`，输出 ≤ 源文件 1.5 倍
- 🎯 **彩色水印**：支持粉色/红色等（RGB 阈值匹配）
- 🔎 **水印自动检测**：`detect_watermark.py` 自动判断是否含水印及类型，提取位置/透明度/旋转角/重复模式，并区分水印与正常页眉页脚
- ⚡ **批量处理**：目录批量、自动分类、统一统计

---

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install PyMuPDF Pillow numpy scipy
```

### 2. 命令行用法（推荐主脚本 `remove_watermark.py`）

```bash
# 自动分类 + 智能去水印（单文件或整个目录，推荐）
python remove_watermark.py input.pdf
python remove_watermark.py ./pdfs/

# 仅用 Form XObject 无损法（调试/确认分层结构）
python remove_watermark.py input.pdf --mode form

# 强制像素法（扫描件或兜底调试）
python remove_watermark.py input.pdf --mode gray  --quality 80
python remove_watermark.py input.pdf --mode color --rmin 180 --gmax 120 --bmax 130

# 指定输出路径 / 目录
python remove_watermark.py input.pdf -o results/clean.pdf
```

### 3. 老脚本 `pdf_watermark.py`（纯像素法，仅扫描件/调试）

```bash
python pdf_watermark.py input.pdf --mode gray
python pdf_watermark.py input.pdf --mode color --rmin 180 --gmax 120 --bmax 130
```

### 4. 水印自动检测 `detect_watermark.py`

去水印前（或独立审计）可先自动检测：

```bash
# 人类可读结论：是否含水印 / 推广、类型、位置、重复模式
python detect_watermark.py input.pdf

# 结构化 JSON 报告（含每类水印的位置/透明度/旋转角/重复模式）
python detect_watermark.py input.pdf --json -o report.json

# 仅分析前 5 页（提速）
python detect_watermark.py input.pdf --sample 5
```

**四类分辨逻辑**：
1. **背景层重复半透明文字/图案** — 灰度填充 (`0.5 0.5 0.5 rg`) 或 `/Subtype /Watermark` 的 Form XObject，跨页统计重复性。
2. **覆盖正文上方、与正文无关的重复元素** — 同内容/同位置跨页出现的 Form（跨页配准）→ 水印/推广。
3. **固定位置浅色/低不透明图形** — 页眉/页脚区域或带旋转的浅色图形；正文区灰度/旋转元素 → 水印。
4. **区分水印与正常页眉页脚** — 含公众号/二维码等关键词 → `promo`；仅页码/标题 → `normal_header_footer`（排除）；普通 Logo/图片 → `graphic`（不报）。

**返回字段**：`has_watermark` / `has_promo` / `confidence` / `doc_type`(`layered`/`scanned`) / `watermarks[]`（每项含 `type`、`source`、`position`、`opacity`、`translucent`、`rotation_deg`、`content`、`repetition`）/ `normal_header_footer[]`。

### 5. 在 WorkBuddy 对话中触发

当用户说"去水印"、"清理水印"、"去除水印"、"PDF 去水印" 并提供 PDF 路径时，自动处理。

---

## 🧭 工作原理（核心：规则0 + 规则0.5）

```
输入 PDF
   │
   ▼ 规则0: 分类
第1页 get_text() > 50 字 且 非整页大图?
   │
   ├─ 是(LAYERED) ──▶ 规则0.5 首选: Form XObject 无损删除
   │                  · 灰度填充的 Form  = 水印 → 删其 Do 的 /Artifact BDC..EMC 整块
   │                  · 黑字+页眉/页脚位置的 Form = 推广 → 同上删
   │                  save(garbage=4, deflate, clean)
   │                  ✅ 正文/图片毫发无损、文本可选、体积更小
   │                  └ 若无 XObject 目标 → inline 文本 redact 兜底
   │
   └─ 否(SCANNED) ──▶ 像素法兜底（仅扫描件/图片融合水印）
                      渲染→RGB灰度/彩色检测→连通域保护→JPEG压缩
                      ⚠️ 会丢失文本可选性，体积需控 ≤1.5x
```

### 为什么 Form XObject 删除优于 redact / 像素法？

- **redact** 是矩形区域擦除，水印 bbox 与正文重叠时会误伤正文（很多公众号水印斜跨正文）。
- **Form XObject 删除**是**对象级别**的——只移除水印绘制指令，正文对象的每个字节都 untouched。
- **像素法**会把整页炸成图，毁掉文本可选性、留残影、漏黑色推广、易膨胀体积——它是扫描件的兜底，不是分层型的正解。

---

## ⚙️ 命令行参数（`remove_watermark.py`）

| 参数 | 简写 | 默认值 | 说明 |
|------|------|--------|------|
| `source` | - | 必填 | 输入 PDF 文件或目录 |
| `--mode` | - | `auto` | `auto`(智能) / `form`(仅Form无损) / `gray` / `color`(像素法) |
| `--output` | `-o` | 同目录 | 输出文件或目录 |
| `--zoom` | - | 2 | 像素法渲染缩放倍数（1-3） |
| `--quality` | - | 80 | JPEG 压缩质量（1-100，控制体积） |
| `--gray-min/max/diff` | - | 120/240/30 | 灰度检测：亮度范围与 RGB 最大差值 |
| `--rmin/rmax/gmax/bmax` | - | 175/255/175/175 | 彩色检测：RGB 阈值 |

---

## 📊 实际案例

| 场景 | 类型 | 处理方法 | 效果 |
|------|------|----------|------|
| 公众号文章合集（有水印/推广 Form）| LAYERED | Form XObject 无损删除 | 水印+推广清除，正文完整、文本可选、体积更小 |
| 微信/QQ 聊天截图（纯图版）| SCANNED | 灰色斜铺像素法 | 斜向灰色水印清除，聊天内容完好 |
| 粉色标题/日期水印 | SCANNED/COLOR | 彩色 RGB 匹配 | 粉色文字替换白色 |
| 任意 PDF 审计 | — | `detect_watermark.py` | 返回 `has_watermark`/类型/位置/透明度/重复模式，区分正常页眉页脚 |

---

## 📁 文件结构

```
pdf-watermark-removal/
├── SKILL.md                    # Skill 定义（含底层强制规则）
├── README.md                   # 本文档
├── _meta.json                  # 元数据
└── scripts/
    ├── remove_watermark.py     # ★ 主脚本：自动分类 + Form 无损优先 + 像素兜底
    ├── detect_watermark.py     # 水印自动检测：类型/位置/透明度/重复模式/区分页眉页脚
    ├── pdf_watermark.py        # 纯像素法脚本（扫描件/调试用）
    ├── batch_watermark.py      # 目录批量封装（复用主脚本逻辑）
    ├── requirements.txt        # Python 依赖
    └── setup.bat               # Windows 安装脚本
```

---

## 🔧 底层强制规则（不可违背）

1. **先分类，再选策略**（规则 0，最高优先级）
   - LAYERED 首选 Form XObject 无损删除；无 XObject 目标再 inline redact；SCANNED 才走像素法。
2. **输出体积受控**
   - ≤ 源文件 1.5 倍，理想接近或小于源文件。
   - 禁止无损 PNG 合成；强制 JPEG 压缩 + `garbage=4, deflate=True`。
3. **先分析水印颜色/结构再处理**——禁止凭经验假设（曾误判灰色为粉色）。
4. **保持排版与内容完整**——正文、图片、文本可选性不被破坏（分层无损法天然满足）。
5. **输出命名**：原文件名 + `_无水印`，同目录输出。

---

## 📚 参考项目

- **ben0i0d/Remove-Watermark**：https://github.com/ben0i0d/Remove-Watermark（RGB 像素替换法）
- **zuruoke/watermark-removal**：https://github.com/zuruoke/watermark-removal（深度学习图像修复）

---

## 📄 License

MIT
