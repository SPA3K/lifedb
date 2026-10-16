#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""监控 icloud_retry.py 下载进度
- 每 60s 采样: 巴厘窗口收尾 + 澳洲窗口(2026/02)从0到完成
- 关键事件打印带标记行 (watch_patterns 可捕获):
    AU_START  = 澳洲窗口开始有文件落盘
    AU_DONE   = 澳洲窗口连续 3 分钟无新写入且 retry 进程已退出
    RETRY_EXIT= retry 进程退出(无论成败)
"""
import os
import time

import psutil

RETRY_PID = 34020
BASE = "D:" + os.sep + "icloud-photos"
DIR_BALI = os.path.join(BASE, "2025", "05")
DIR_AUS = os.path.join(BASE, "2026", "02")

INTERVAL = 60


def count_files(d):
    n = 0
    if not os.path.isdir(d):
        return 0
    for root, _dirs, files in os.walk(d):
        n += len(files)
    return n


def newest_mtime(d):
    m = 0
    if not os.path.isdir(d):
        return 0
    for root, _dirs, files in os.walk(d):
        for f in files:
            try:
                m = max(m, os.path.getmtime(os.path.join(root, f)))
            except OSError:
                pass
    return m


def retry_alive():
    try:
        return psutil.pid_exists(RETRY_PID) and psutil.Process(RETRY_PID).is_running()
    except Exception:
        return False


def days_under(d):
    if not os.path.isdir(d):
        return []
    out = []
    for m in sorted(os.listdir(d)):
        mp = os.path.join(d, m)
        if not os.path.isdir(mp):
            continue
        for day in sorted(os.listdir(mp)):
            dp = os.path.join(mp, day)
            if os.path.isdir(dp):
                out.append(f"{m}/{day}:{len(os.listdir(dp))}")
    return out


def main():
    au_started = False
    last_au_write = 0
    idle_cnt = 0
    print(f"[{time.strftime('%H:%M:%S')}] monitor start (retry pid={RETRY_PID})",
          flush=True)
    while True:
        alive = retry_alive()
        bali = count_files(DIR_BALI)
        aus = count_files(DIR_AUS)
        nm_newest = newest_mtime(DIR_AUS) if aus else 0
        now = time.time()

        if aus > 0 and not au_started:
            au_started = True
            print(f"[{time.strftime('%H:%M:%S')}] AU_START 澳洲窗口开始落盘 "
                  f"{aus}张", flush=True)

        if au_started:
            if now - nm_newest < 90:
                idle_cnt = 0
            else:
                idle_cnt += 1

        line = (f"[{time.strftime('%H:%M:%S')}] 巴厘2025/05={bali}张 "
                f"{'days=' + ','.join(days_under(DIR_BALI)) if not alive else ''} | "
                f"澳洲2026/02={aus}张 | retry={'运行中' if alive else '已退出'}")
        print(line, flush=True)

        if not alive:
            print(f"[{time.strftime('%H:%M:%S')}] RETRY_EXIT 最终: "
                  f"巴厘={bali}张 澳洲={aus}张", flush=True)
            if aus == 0:
                print("AU_NONE 澳洲窗口0张(服务端无资产或持续indexing)",
                      flush=True)
            elif idle_cnt >= 3 or aus > 0:
                print(f"AU_DONE 澳洲={aus}张 days={','.join(days_under(DIR_AUS))}",
                      flush=True)
            break

        if au_started and idle_cnt >= 5 and aus > 0:
            # retry 还活着但澳洲 5 分钟没新文件 (可能在 indexing 等待重试)
            idle_cnt = 0
            print(f"[{time.strftime('%H:%M:%S')}] AU_IDLE 澳洲5分钟无新写入 "
                  f"({aus}张), retry仍运行", flush=True)

        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
