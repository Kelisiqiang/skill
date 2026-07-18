# -*- coding: utf-8 -*-
"""飞书自定义机器人推送(平台通用)。
用法:
  set FEISHU_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/xxx   (Windows)
  export FEISHU_WEBHOOK=...                                              (macOS/Linux)
  python notify_feishu.py "要推送的文本"
成功时打印 {"code":0,...}。
"""
import json, os, sys, urllib.request

def main():
    webhook = os.environ.get("FEISHU_WEBHOOK", "").strip()
    text = " ".join(sys.argv[1:]).strip() or "财新周刊归档任务已结束。"
    if not webhook:
        print("ERROR: FEISHU_WEBHOOK 未设置", file=sys.stderr)
        sys.exit(1)
    body = json.dumps({"msg_type": "text", "content": {"text": text}}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(webhook, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        resp = r.read().decode("utf-8")
    print(resp)
    if '"code":0' not in resp:
        sys.exit(2)

if __name__ == "__main__":
    main()
