#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""photo_geolocate — 照片 × 轨迹 融合回填 (T2 测试转正)

把没有 EXIF GPS 的照片, 用其时间戳在 geo_point 轨迹里做最近点回溯,
把得到的坐标 **写回 event 表** (lat/lon + meta.gps_source='trajectory')。
打通后所有下游 (分享卡 / F1 地图 / 查询) 直接读 event.lat/lon, 不用临时 join。

用法:
  py -3 adapters/geolocate.py            # 正式回填 (只更新 lat IS NULL 的行, 幂等)
  py -3 adapters/geolocate.py --dry-run  # 只报告, 事务回滚
"""
import bisect
import datetime
import json
import os
import sqlite3
import sys

DB = os.path.expanduser("~/.hermes/life-db/timeline.db")
WINDOW = 3600 * 6          # 6 小时窗口 = 城市级定位 (T2 实测 30min 窗仅35%, 6h 达 76%+)
REAL_EXTS = (".jpg", ".jpeg", ".heic", ".heif")   # PNG=截图不回填 (没有真实拍摄地意义)


def parse_iso(t):
    try:
        return datetime.datetime.fromisoformat(t).timestamp()
    except Exception:
        return None


def main():
    dry = "--dry-run" in sys.argv
    db = sqlite3.connect(DB)
    db.execute("PRAGMA foreign_keys=ON")
    pts = db.execute("select ts, lat, lon from geo_point order by ts").fetchall()
    if not pts:
        sys.exit("geo_point 为空, 无轨迹可回溯")
    tsl = [p[0] for p in pts]

    rows = db.execute("select id, ts_start, payload_ref, meta from event "
                      "where source='icloud' and lat is null").fetchall()
    todo = [r for r in rows if r[2].lower().endswith(REAL_EXTS)]
    skipped = len(rows) - len(todo)

    hits, misses = 0, 0
    try:
        for pid, ts, ref, meta in todo:
            pt = parse_iso(ts)
            if pt is None:
                misses += 1
                continue
            i = bisect.bisect_left(tsl, pt)
            best, bd = None, 1e18
            for j in (i - 1, i):
                if 0 <= j < len(pts):
                    dd = abs(tsl[j] - pt)
                    if dd < bd:
                        bd, best = dd, pts[j]
            if best is None or bd > WINDOW:
                misses += 1
                continue
            m = json.loads(meta or "{}")
            m["gps_source"] = "trajectory"
            m["gps_offset_s"] = int(bd)
            db.execute("update event set lat=?, lon=?, meta=? where id=?",
                       (best[1], best[2], json.dumps(m, ensure_ascii=False), pid))
            hits += 1
        if dry:
            db.rollback()
            tag = "[dry-run]"
        else:
            db.commit()
            tag = "✓"
        print(f"{tag} 回填 {hits} 张 (截图跳过 {skipped}, 窗口外 {misses}) "
              f"← 待处理 {len(rows)} 行" + (" [已回滚]" if dry else ""))
    except Exception:
        db.rollback()
        raise


if __name__ == "__main__":
    main()
