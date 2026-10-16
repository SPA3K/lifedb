#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""iCloud 时间窗批量下载 (出国日候选)
窗口覆盖: 澳洲2026-02 / 巴厘2025-05 / 美国2018-08
增量安全: icloudpd 跳过已存在文件; 必须带 skip-created 参数防全量!
"""
import subprocess
import sys
import os
import shutil

CONF = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icloud.conf")


def load_conf():
    cfg = {}
    for line in open(CONF, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip()
    return cfg


WINDOWS = [
    ("2018-08-16", "2018-08-26", "美国 Ohio/Chicago"),
    ("2025-05-01", "2025-05-12", "巴厘岛"),
    ("2026-02-12", "2026-02-24", "澳洲 悉尼+墨尔本"),
]


def main():
    cfg = load_conf()
    exe = shutil.which("icloudpd") or shutil.which("icloudpd.exe")
    if not exe:
        sys.exit("icloudpd 未安装")
    for before, after, label in WINDOWS:
        free_g = shutil.disk_usage("D:\\").free / 2**30
        print(f"\n=== 窗口 [{before},{after}) {label} (D盘剩 {free_g:.1f}G) ===", flush=True)
        if free_g < 5:
            print("!! 磁盘不足5G, 跳过剩余窗口")
            break
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
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                encoding="utf-8", errors="replace", bufsize=1)
        dl, err = [], []
        try:
            for line in proc.stdout:
                line = line.rstrip()
                if not line:
                    continue
                if "Downloaded" in line:
                    dl.append(line)
                    print("  ", line[:160], flush=True)
                elif "ERROR" in line:
                    err.append(line)
                    print("  !!", line[:160], flush=True)
        except subprocess.TimeoutExpired:
            proc.kill()
            err.append("timeout 3600s killed")
        rc = proc.wait(timeout=60)
        print(f"下载 {len(dl)} 个文件, exit={rc}", flush=True)
        for e in err[:5]:
            print("  ", e[:160])
    print("\n全部窗口处理完毕", flush=True)


if __name__ == "__main__":
    main()
