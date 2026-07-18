# Codex(OpenAI Codex CLI)适配

## 浏览器控制

与 Claude Code 相同:Playwright `connect_over_cdp` 接管已登录 Chrome(先以
`--remote-debugging-port=9222` 启动),或 `launch_persistent_context` 使用用户 Profile。
`scripts/extract.js`、`scripts/poll.js` 经 `page.evaluate()` 执行。

在项目的 `AGENTS.md` 中声明:财新周刊任务遵循本 skill 流程;浏览器用系统 Chrome 复用登录态;
输出命名 `[财新周刊]YYYY.NN.md`;归档目录按用户实际配置。

## 定时

cron / 任务计划程序每周六 22:17:

```bash
17 22 * * 6 cd <项目目录> && codex exec "按 caixin-weekly skill 抓取最新一期财新周刊并归档,完成后推送飞书"
```

## 飞书通知

同 Claude Code:`FEISHU_WEBHOOK` 环境变量 + `scripts/notify_feishu.py`。
