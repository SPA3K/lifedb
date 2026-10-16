#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""iCloud 时间窗下载 (带 indexing 状态重试)

背景: Apple 会瞬时返回 "Photo Library has not finished indexing yet",
icloudpd 收到后直接 exit=0 不下载 (github #458, 波动性状态)。
本脚本:
  - 检测 "not finished indexing" → 等 180s 重试 (每窗最多 N 次)
  - 无该消息且 0 下载 → 判定服务端确实无此窗口资产, 记录后继续
  - 每次运行前检查 D 盘剩余空间 (>=5G)
增量安全: icloudpd 跳过已存在文件; 必须带 skip-created 参数防全量!
"""
import shutil
import subprocess
import sys
import time

BASE = __file__.rsplit("\\", 1)[0] if "\\" in __file__ else __file__.rsplit("/", 1)[0]
CONF = BASE + "/icloud.conf"

INDEXING = "not finished indexing"

WINDOWS = [
    ("2025-05-01", "2025-05-12", "巴厘岛"),
    ("2026-02-12", "2026-02-24", "澳洲 悉尼+墨尔本+大洋路"),
]

MAX_RETRY = int(sys.argv[1]) if len(sys.argv) > 1 else 10
SLEEP_SEC = 180


def load_conf():
    cfg = {}
    for line in open(CONF, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip()
    return cfg


def run_window(cfg, exe, before, after, label):
    args = [
        exe, "-u", cfg["APPLE_ID"], "-p", cfg["PASSWORD"],
        "--domain", cfg.get("DOMAIN", "cn"),
        "-d", r"D:\icloud-photos",
        "--folder-structure", "{:%Y/%m/%d}",
        "--size", "original",
        "--skip-created-before", before,
        "--skip-created-after", after,
        "--log-level", "info", "--no-progress-bar",
    ]
    r = subprocess.run(args, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=3600)
    out = (r.stdout or "") + (r.stderr or "")
    indexing = INDEXING in out
    dl = [l for l in out.splitlines() if "Downloaded" in l]
    errs = [l for l in out.splitlines() if "ERROR" in l]
    return r.returncode, indexing, dl, errs


def main():
    cfg = load_conf()
    exe = shutil.which("icloudpd") or shutil.which("icloudpd.exe")
    if not exe:
        sys.exit("icloudpd 未安装")

    results = []
    for before, after, label in WINDOWS:
        print(f"\n=== 窗口 [{before},{after}) {label} ===", flush=True)
        for attempt in range(1, MAX_RETRY + 1):
            free_g = shutil.disk_usage("D:\\").free / 2**30
            if free_g < 5:
                print(f"!! D盘剩 {free_g:.1f}G <5G, 停止", flush=True)
                results.append((label, "磁盘不足", 0))
                return
            print(f"-- 尝试 {attempt}/{MAX_RETRY} (D盘剩 {free_g:.1f}G) "
                  f"{time.strftime('%H:%M:%S')}", flush=True)
            try:
                rc, indexing, dl, errs = run_window(cfg, exe, before, after, label)
            except subprocess.TimeoutExpired:
                print("   超时 3600s", flush=True)
                time.sleep(SLEEP_SEC)
                continue
            if indexing:
                print(f"   Apple 返回 indexing 未完成 (exit={rc}), "
                      f"{SLEEP_SEC}s 后重试", flush=True)
                time.sleep(SLEEP_SEC)
                continue
            for l in dl:
                print("   ", l[:170], flush=True)
            for e in errs[:5]:
                print("   !!", e[:170], flush=True)
            status = f"下载{len(dl)}张" if dl else "服务端无此窗口资产"
            print(f"   ✓ 结束: {status} (exit={rc})", flush=True)
            results.append((label, status, len(dl)))
            break
        else:
            print(f"   ✗ {MAX_RETRY} 次均遇 indexing 状态, 放弃 (可稍后再跑)",
                  flush=True)
            results.append((label, "indexing持续", 0))

    print("\n========== 汇总 ==========", flush=True)
    for label, status, n in results:
        print(f"  {label}: {status} ({n}张)", flush=True)


if __name__ == "__main__":
    main()
