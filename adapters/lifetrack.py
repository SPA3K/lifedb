#!/usr/bin/env python
"""lifetrack adapter — 一生轨迹(backUpData-all.csv) → life-db

两层入库:
  1. geo_point: 全量原始GPS点 (秒级定位)
  2. event:     停留点聚类 (modality=location, source=lifetrack)
     停留定义: 连续点距锚点 <= RADIUS_M 且时长 >= MIN_DUR_S 的最大簇

用法: py -3 adapters/lifetrack.py <csv路径> [--dry-run]
  --dry-run: 完整解析+聚类+入库事务跑通后回滚, DB 不变 (avsm -test 语义)
幂等: INSERT OR IGNORE, 重跑不产生重复
"""
import csv, math, os, sqlite3, sys
from datetime import datetime, timedelta, timezone

DB_PATH = os.path.expanduser("~/.hermes/life-db/timeline.db")
SCHEMA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schema.sql")
CST = timezone(timedelta(hours=8))
RADIUS_M = 150      # 停留判定半径
MIN_DUR_S = 900     # 最短停留15分钟
MAX_GAP_S = 1800    # 点间隔超30分钟视为断开

def dist_m(lat1, lon1, lat2, lon2):
    """haversine 近似(小范围)"""
    dy = (lat2 - lat1) * 111320
    dx = (lon2 - lon1) * 111320 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.sqrt(dx * dx + dy * dy)

def main(csv_path, dry=False):
    con = sqlite3.connect(DB_PATH)
    with open(SCHEMA) as f:
        con.executescript(f.read())

    # 1) 原始点批量入库
    def fnum(v):
        try: return float(v) or None
        except (TypeError, ValueError): return None   # 空串/脏值容忍
    pts = []
    with open(csv_path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            pts.append((int(row["dataTime"]), float(row["latitude"]), float(row["longitude"]),
                        fnum(row.get("altitude")), fnum(row.get("speed"))))
    pts.sort()
    con.executemany("INSERT OR IGNORE INTO geo_point(ts,lat,lon,alt,speed) VALUES (?,?,?,?,?)", pts)
    raw_new = con.total_changes
    con.commit()

    # 2) 停留聚类
    stays = []
    anchor = None   # 锚点(lat,lon)
    last_ts = None
    start_ts = None
    n_in = 0; sum_lat = 0.0; sum_lon = 0.0

    def flush():
        nonlocal anchor, start_ts, n_in, sum_lat, sum_lon
        if anchor and start_ts is not None:
            dur = (last_ts - start_ts) if last_ts else 0
            if dur >= MIN_DUR_S and n_in >= 3:
                stays.append((start_ts, last_ts, sum_lat / n_in, sum_lon / n_in, n_in, dur))
        anchor = None; start_ts = None; n_in = 0; sum_lat = 0.0; sum_lon = 0.0

    for ts, lat, lon, _alt, _sp in pts:
        if anchor is None:
            anchor = (lat, lon); start_ts = ts; last_ts = ts; n_in = 1; sum_lat = lat; sum_lon = lon
            continue
        if ts - last_ts > MAX_GAP_S:
            flush(); anchor = (lat, lon); start_ts = ts; last_ts = ts; n_in = 1; sum_lat = lat; sum_lon = lon
            continue
        if dist_m(anchor[0], anchor[1], lat, lon) <= RADIUS_M:
            n_in += 1; sum_lat += lat; sum_lon += lon; last_ts = ts
        else:
            flush()
            anchor = (lat, lon); start_ts = ts; last_ts = ts; n_in = 1; sum_lat = lat; sum_lon = lon
    flush()

    rows = []
    for st, en, la, lo, np_, dur in stays:
        title = f"停留 {dur//3600}h{dur%3600//60}m ({np_}点)"
        h = f"{st}-{round(la,3)},{round(lo,3)}"
        rows.append((datetime.fromtimestamp(st, CST).isoformat(),
                     datetime.fromtimestamp(en, CST).isoformat(),
                     "location", "lifetrack", title, None, h, "[]",
                     round(la, 5), round(lo, 5)))
    con.executemany(
        """INSERT OR IGNORE INTO event(ts_start,ts_end,modality,source,title,payload_ref,payload_hash,tags,lat,lon)
           VALUES (?,?,?,?,?,?,?,?,?,?)""", rows)
    stay_new = con.total_changes - raw_new
    if dry:
        con.rollback()
        prefix = "[dry-run] "
    else:
        con.commit()
        prefix = ""

    print(f"{prefix}原始点: {len(pts)} 行, 新入库 {raw_new} (其余已存在)")
    print(f"{prefix}停留点: 发现 {len(rows)} 个(>=15min, <=150m半径), 新入库 {stay_new}")
    if dry:
        print("[dry-run] 已回滚, DB 未变")
    if rows:
        d = datetime.fromtimestamp(stays[0][0], CST)
        print(f"最早停留: {d:%Y-%m-%d %H:%M} @({stays[0][2]:.3f},{stays[0][3]:.3f})")

if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    if len(args) != 1:
        sys.exit(__doc__)
    main(args[0], dry=dry)
