# Claude Code 适配

## 浏览器控制(首选):直连 Kimi WebBridge

若机器已装 Kimi WebBridge,Claude Code 无需任何额外依赖——守护进程
`http://127.0.0.1:10086/command` 是普通本地 HTTP 服务,不校验调用方。
skill 包里的 `scripts/driver_webbridge.py` 可直接运行(仅依赖标准库 + curl.exe):

```bash
python scripts/driver_webbridge.py 0 99   # 需先备好 toc.json,见脚本 docstring
```

- 守护进程未运行时先启动:`& "$env:USERPROFILE\.kimi-webbridge\bin\kimi-webbridge.exe" start`(Windows)
- 建议用环境变量 `WEBBRIDGE_SESSION` 换一个 session 名,避免与 Kimi 侧任务共享标签组
- 请求协议与铁律见 `references/kimi.md`(临时文件 + `curl.exe --data-binary` 等)

## 浏览器控制(备选):Playwright 接管用户 Chrome

复用用户登录态的关键是接管真实 Chrome,而非全新无头实例:

```bash
pip install playwright
```

```python
from playwright.sync_api import sync_playwright
# 方式一:连接已运行的 Chrome(先以 --remote-debugging-port=9222 启动 Chrome)
with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    page = browser.contexts[0].pages[0]

# 方式二:用用户 Profile 启动(Chrome 需先关闭)
# browser = p.chromium.launch_persistent_context(
#     r"C:\Users\<USER>\AppData\Local\Google\Chrome\User Data",
#     channel="chrome", headless=False)
```

也可安装 chrome-devtools / playwright 类 MCP server,让模型直接调用。
`scripts/extract.js` 与 `scripts/poll.js` 通过 `page.evaluate(js)` 执行;`location.href` 跳转后按 poll 逻辑轮询。

注意:CLAUDE.md 里声明"每次财新周刊任务使用本 skill 流程",并写明用户的财新登录已在该 Chrome Profile 中。

## 定时

- Windows:任务计划程序,每周六 22:17 执行
  `claude -p "按 caixin-weekly skill 抓取最新一期财新周刊并归档" --allowedTools "Bash,Read,Write,Edit"`
- macOS/Linux:cron `17 22 * * 6 cd <项目目录> && claude -p "..."`

## 飞书通知

`FEISHU_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/xxx` 写入环境变量或 `.env`,
任务末尾 `python scripts/notify_feishu.py "结果摘要"`。
