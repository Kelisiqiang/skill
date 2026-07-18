# Kimi(Kimi Work / Daimon)适配

## 浏览器控制:kimi-webbridge 技能

本地守护进程 `http://127.0.0.1:10086`,通过浏览器扩展控制用户真实浏览器(带登录态)。
调用前先加载 kimi-webbridge 技能获取完整协议。要点:

- 每个请求是 POST JSON 到 `http://127.0.0.1:10086/command`,形如
  `{"action":"evaluate","args":{"code":"..."},"session":"caixin-weekly"}`
- `session` 字段贯穿整个任务,所有标签页收进一个标签组。
- Windows 下请求体必须走临时文件 + `curl.exe --data-binary`(见 SKILL.md 铁律)。
- 守护进程不在线时启动:`& "$env:USERPROFILE\.kimi-webbridge\bin\kimi-webbridge.exe" start`(Windows)。
- 导航用 `evaluate` 执行 `location.href='...'`(立即返回),不用 `navigate`(整页 load 会被广告拖到 30s 超时)。
- 响应经 `data.value` 取回,`evaluate` 返回的是 JSON 字符串需二次解析。

## 参考实现

`scripts/driver_webbridge.py`:完整驱动(逐篇导航、稳定等待、正文提取)。
用环境变量配置:`CAIXIN_WS`(工作根目录)、`CAIXIN_OUT`(输出子目录,默认 `caixin-weekly-out`)。
目录页 TOC 需先保存为 `$CAIXIN_WS/$CAIXIN_OUT/toc.json`(格式见脚本内 docstring)。
正文清洗脚本 `scripts/build_md.py` 用 `CAIXIN_OUT_DIR`(raw/ 所在目录)与 `CAIXIN_MD_NAME`(合订本文件名)配置。

## 定时:Blueprint Automation

创建 agent local_conversation 类型 Automation(cron job):
- trigger: `{"kind":"schedule","cron":"17 22 * * 6","timezone":"Asia/Shanghai"}`(每周六 22:17,新刊周六晚间上线后)
- prompt 要点:读本技能 SKILL.md → 按五步流程执行 → 结束推送飞书(如有 webhook)→ 对话内汇报
- delivery 可加 Kimi 桌面/手机通知
