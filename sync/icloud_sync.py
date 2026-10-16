#!/usr/bin/env python
"""icloudpd 同步包装 — 配置集中在 icloud.conf, 密码只落本机文件

用法:
  py -3 icloud_sync.py               单次同步 (cron/手动, 增量)
  py -3 icloud_sync.py --watch       常驻监听 (watch-with-interval, 断点续传)
  py -3 icloud_sync.py --auth-only   只建 cookie/session (首次认证, 会要 MFA 验证码)
  py -3 icloud_sync.py --dry-run     icloudpd 原生 dry-run (不下载不改动)
"""
import os, shutil, subprocess, sys

BASE = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.join(BASE, "icloud.conf")
NOTIFY = os.path.join(BASE, "icloud_notify.py")

def load_conf():
    cfg = {}
    with open(CONF, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip()
    return cfg

def main():
    cfg = load_conf()
    apple_id = cfg.get("APPLE_ID", "")
    password = cfg.get("PASSWORD", "")
    if not apple_id or not password:
        sys.exit(f"请先填写 {CONF} 中的 APPLE_ID 和 PASSWORD (2FA账号建议用应用专用密码)")

    exe = shutil.which("icloudpd") or shutil.which("icloudpd.exe")
    if not exe:
        sys.exit("icloudpd 未安装: python -m pip install icloudpd")

    args = [
        exe,
        "-u", apple_id,
        "-p", password,
        "--domain", cfg.get("DOMAIN", "com"),
        "-d", cfg.get("ICLOUD_DIR", r"D:\icloud-photos"),
        "--folder-structure", cfg.get("FOLDER_STRUCTURE", "{:%Y/%m/%d}"),
        "--size", "original",              # 下原图
        "--set-exif-datetime",             # 无 EXIF 时间的用文件创建时间补 → adapter 有保底
        "--log-level", "info",
        "--no-progress-bar",
        "--notification-script", NOTIFY,   # 2FA过期/认证失败 → 飞书告警
    ]
    recent = cfg.get("RECENT", "")
    if recent.isdigit():
        args += ["--recent", recent]

    mode = set(sys.argv[1:])
    if "--auth-only" in mode:
        # 认证有交互 (MFA 验证码) → 统一交给专用脚本 icloud_auth.py
        sys.exit(subprocess.call([sys.executable, os.path.join(BASE, "icloud_auth.py")]))
    elif "--watch" in mode:
        args += ["--watch-with-interval", cfg.get("WATCH_INTERVAL", "3600")]
    if "--dry-run" in mode:
        args += ["--dry-run"]

    shown = [a if i < 2 or "PASSWORD" in a else ("***" if a == password else a)
             for i, a in enumerate(args)]
    print("exec:", " ".join(a if " " not in a else f'"{a}"' for a in shown))
    print(f"(mode={' '.join(mode) or 'single-sync'})")
    sys.exit(subprocess.call(args))

if __name__ == "__main__":
    main()
