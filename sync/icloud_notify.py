#!/usr/bin/env python
"""icloudpd --notification-script 钩子: 2FA过期/认证异常 → 飞书告警 + 本地留痕

icloudpd 在需要重新认证时调用本脚本; argv/stdin 原样落日志, 飞书发送失败不阻塞。
"""
import datetime, os, subprocess, sys

BASE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(BASE, "notify.log")
FEISHU_HOME = "oc_27cdc2ff3bcc32a42f96de7abc204c19"   # Hermes Home 频道

def main():
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    try:
        stdin = sys.stdin.read() if not sys.stdin.isatty() else ""
    except Exception:
        stdin = ""
    detail = " | ".join(sys.argv[1:]) or stdin.strip() or "2FA/会话过期"
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{ts} argv={sys.argv[1:]} stdin={stdin.strip()!r}\n")

    msg = f"⚠️ iCloud 照片同步需要重新认证（{ts}）\n原因: {detail[:200]}\n处理: 跑 `py -3 sync/icloud_sync.py --auth-only` 完成 MFA"
    exe = "feishu-cli"
    try:
        subprocess.run(
            [exe, "msg", "send", "--receive-id-type", "chat_id",
             "--receive-id", FEISHU_HOME, "--text", msg],
            capture_output=True, timeout=30)
    except Exception as e:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{ts} feishu-send-failed: {e}\n")

if __name__ == "__main__":
    main()
