# Skills 合集

这里收录各类可复用的 WorkBuddy Skill，每个 skill 放在独立子目录中。

## 目录

| Skill | 说明 | 路径 |
| --- | --- | --- |
| **pdf-watermark-removal** | PDF 去水印工具：支持灰色斜向平铺水印与彩色水印；分层型无损删除、扫描型像素法去灰；输出体积受控（≤ 源文件 1.5 倍） | [pdf-watermark-removal/](pdf-watermark-removal/) |
| **caixin-weekly** | 财新周刊整期归档：抓取最新一期全部文章全文（含分页长文、题图、导语、图说），清洗后生成单文件 Markdown 合订本 `[财新周刊]YYYY.NN.md`；六步流程含交付前自动校验，支持 Kimi / Claude Code / Codex 三平台 | [caixin-weekly/](caixin-weekly/) |（需登录财新订阅账号）

## 使用方式

将对应子目录克隆到本地 `~/.workbuddy/skills/` 即可在 WorkBuddy 对话中通过触发词调用。

### caixin-weekly 三平台安装

```bash
git clone https://github.com/Kelisiqiang/skill.git
```

- **Kimi（Kimi Work）**：将 `caixin-weekly/` 复制到 Kimi skills 目录（如 `%APPDATA%\kimi-desktop\daimon-share\daimon\skills\`）；定时归档按 `references/kimi.md` 创建 Blueprint Automation（建议每周六 22:17，新刊上线后）
- **Claude Code**：将 `caixin-weekly/` 复制到 `~/.claude/skills/`；浏览器联动优先直连 Kimi WebBridge（本机已装时零依赖），备选 Playwright 接管用户 Chrome，详见 `references/claude-code.md`
- **Codex**：将 `caixin-weekly/` 复制到 `~/.config/agents/skills/` 或项目内 `.agents/skills/`，详见 `references/codex.md`

前置条件：可控的真实浏览器且已登录财新账号（企业/个人订阅全文权限）；Python 3（仅用标准库）。飞书通知可选，设置环境变量 `FEISHU_WEBHOOK` 即可。

## License

MIT
