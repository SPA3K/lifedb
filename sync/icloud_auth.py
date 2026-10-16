#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""iCloud 认证一键脚本 — 触发一次 → 等推送 → 自动填码 (icloudpd --auth-only 包装)

设计要点 (解决"弹两次码 + 卡住 + 不优雅"):
  1. 单实例锁: 同时只允许一个认证进程, 杜绝并发触发导致 Apple 连环弹窗
  2. icloudpd 认证分多步: 选项提示(选设备/选方式)自动回车应答, 不浪费验证码;
     只有真正要 6 位验证码时才向你要码, 喂码后自动完成后续流程
  3. 输出全程 flush + 落盘 icloud_auth.log, 进度永远可见
  4. 明确成败判据: 失败串检测 + cookie 文件 mtime 校验, 结果一目了然

用法:
  py -3 icloud_auth.py                    交互式 (推荐: 触发后把最新码敲进来回车)
  py -3 icloud_auth.py --code 123456      非交互 (预知验证码时)
  py -3 icloud_auth.py --log-level debug  调试

认证成功后 cookie 有效期约 2 个月, 到期 icloud_notify.py 会发飞书提醒。
"""
import argparse
import os
import re
import subprocess
import sys
import threading
import time

BASE = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.join(BASE, "icloud.conf")
LOG = os.path.join(BASE, "icloud_auth.log")

# 真正需要 6 位验证码的提示
CODE_PROMPT_RE = re.compile(r"Please enter two-factor authentication code", re.I)
# 选项类提示: 自动回车选默认项, 不消耗验证码
OPTION_PROMPT_RE = re.compile(
    r"Please choose an option|Which device would you like to use|Which phone number",
    re.I,
)
FAIL_RE = re.compile(
    r"Incorrect verification code|Code verification failed|"
    r"Authentication has failed|Invalid username/password|"
    r"Multifactor authentication information missing|Failed to verify",
    re.I,
)
SUCCESS_RE = re.compile(r"Authentication completed|Two factor authentication cookie generated", re.I)


def log(msg=""):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


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


class SingleInstanceLock:
    """防并发双触发: PID 文件 + 存活检查 (stale 自动清)"""

    def __init__(self, path):
        self.path = path

    def __enter__(self):
        import psutil
        if os.path.exists(self.path):
            try:
                with open(self.path) as f:
                    pid = int(f.read().strip())
                if psutil.pid_exists(pid) and pid != os.getpid():
                    log(f"✗ 已有认证进程在运行 (PID {pid}), 为避免 Apple 连环弹窗已退出")
                    sys.exit(3)
            except (ValueError, OSError):
                pass
            os.remove(self.path)
        with open(self.path, "w") as f:
            f.write(str(os.getpid()))
        return self

    def __exit__(self, *exc):
        if os.path.exists(self.path):
            try:
                os.remove(self.path)
            except OSError:
                pass


def build_args(cfg, log_level):
    import shutil
    exe = shutil.which("icloudpd") or shutil.which("icloudpd.exe")
    if not exe:
        sys.exit("icloudpd 未安装: python -m pip install icloudpd")
    return [
        exe,
        "-u", cfg.get("APPLE_ID", ""),
        "-p", cfg.get("PASSWORD", ""),
        "--domain", cfg.get("DOMAIN", "com"),
        "-d", cfg.get("ICLOUD_DIR", r"D:\icloud-photos"),
        "--folder-structure", cfg.get("FOLDER_STRUCTURE", "{:%Y/%m/%d}"),
        "--size", "original",
        "--set-exif-datetime",
        "--auth-only",
        "--log-level", log_level,
        "--no-progress-bar",
    ]


def cookie_paths(cfg):
    cdir = os.path.expanduser("~/.pyicloud")
    aid = cfg.get("APPLE_ID", "").replace("@", "").replace(".", "")
    return [os.path.join(cdir, aid), os.path.join(cdir, aid + ".session")]


def newest_mtime(paths):
    ts = []
    for p in paths:
        try:
            ts.append(os.path.getmtime(p))
        except OSError:
            pass
    return max(ts) if ts else 0.0


def main():
    ap = argparse.ArgumentParser(description="iCloud 认证一键脚本")
    ap.add_argument("--code", action="append", default=[],
                    help="6位验证码, 可重复传入应对多轮认证 (非交互模式)")
    ap.add_argument("--log-level", default="info", choices=["debug", "info", "error"])
    args = ap.parse_args()

    cfg = load_conf()
    if not cfg.get("APPLE_ID") or not cfg.get("PASSWORD"):
        sys.exit(f"请先填写 {CONF} 中的 APPLE_ID 和 PASSWORD")
    cmd_args = build_args(cfg, args.log_level)

    lock_path = os.path.join(os.path.dirname(cookie_paths(cfg)[0]), ".auth_lock")
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)

    with SingleInstanceLock(lock_path):
        start_ts = time.time()
        cookies_before = newest_mtime(cookie_paths(cfg))

        log("▶ 触发 Apple 登录请求 (仅一次) …")
        proc = subprocess.Popen(
            cmd_args,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )

        code_queue = list(args.code)
        needs_code = threading.Event()
        failed = {"hit": False}

        def answer(text):
            try:
                proc.stdin.write(text)
                proc.stdin.flush()
            except OSError:
                pass

        def reader():
            # 逐字符读: icloudpd 的输入提示没有换行符, 按行读会永远等不到
            line_buf, scan_buf = "", ""
            while True:
                ch = proc.stdout.read(1)
                if not ch:
                    break
                if ch == "\n":
                    line = line_buf.rstrip()
                    line_buf = ""
                    with open(LOG, "a", encoding="utf-8") as f:
                        f.write(f"[{time.strftime('%H:%M:%S')}]   │ {line}\n")
                    print("  │", line, flush=True)
                    continue
                line_buf += ch
                scan_buf += ch
                print(ch, end="", flush=True)
                if FAIL_RE.search(scan_buf):
                    failed["hit"] = True
                    scan_buf = ""
                elif SUCCESS_RE.search(scan_buf):
                    scan_buf = ""
                elif CODE_PROMPT_RE.search(scan_buf):
                    scan_buf = ""
                    needs_code.set()
                elif OPTION_PROMPT_RE.search(scan_buf):
                    # 选项类提示: 自动选默认项, 不消耗验证码
                    scan_buf = ""
                    answer("\n")
                    print("\n   → 选项提示, 自动回车选默认项", flush=True)
            exit_evt.set()

        exit_evt = threading.Event()
        threading.Thread(target=reader, daemon=True).start()

        while not exit_evt.is_set():
            if needs_code.is_set():
                needs_code.clear()
                if code_queue:
                    code = code_queue.pop(0)
                    print(f"   → 自动填入预置码 {code}", flush=True)
                else:
                    # 注意: 某些 pty/代理环境下 isatty() 为 False 但 input() 仍可用,
                    # 因此不依赖 isatty, 直接尝试 input, EOF 才判定不可交互
                    try:
                        code = input(f"\n📱 {time.strftime('%H:%M:%S')} 验证请求已推送, "
                                     "请查看苹果设备, 输入最新 6 位验证码后回车: ").strip()
                    except EOFError:
                        log("   ! 标准输入不可用 (EOF), 无法输入验证码, 退出")
                        proc.kill()
                        sys.exit(2)
                    if not code:
                        log("   ! 收到空验证码, 退出")
                        proc.kill()
                        sys.exit(2)
                try:
                    proc.stdin.write(code + "\n")
                    proc.stdin.flush()
                except OSError:
                    pass
            if exit_evt.wait(timeout=0.3):
                break

        rc = proc.wait()
        cookies_after = newest_mtime(cookie_paths(cfg))
        ok = (not failed["hit"]) and rc == 0 and cookies_after > max(cookies_before, start_ts - 60)
        if ok:
            log(f"✅ 认证成功! cookie 已写入 ~/.pyicloud, 有效期约 2 个月。")
            log("   下一步: py -3 icloud_sync.py  (单次同步) 或 --watch (常驻)")
        else:
            log(f"❌ 认证失败 (rc={rc}, code_rejected={failed['hit']}).")
            if failed["hit"]:
                log("   验证码错误/过期 → 重新运行本脚本即可 (会重新推送一次请求)。")
            else:
                log("   无推送或网络问题: 等 30 分钟再试 (Apple 对频繁尝试会节流)。")
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
