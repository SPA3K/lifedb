#!/usr/bin/env python
"""gmaps adapter — Google Timeline 导出(Timeline.json) → life-db

新版 Timeline 导出为记录列表, 三类条目:
  1. visit   停留   → event (modality=location, source=gmaps)
  2. activity活动段 → event (modality=transport, source=gmaps)
  3. timelinePath 轨迹点 → geo_point (点带 durationMinutesOffsetFromStartTime,
     可由 record.startTime 推出真实时间戳; 主键(ts,lat,lon)与一生轨迹自动去重互补)

用法: py -3 adapters/gmaps.py <Timeline.json> [--dry-run]
  --dry-run: 事务内跑完即回滚, DB 不变 (avsm -test 语义)
幂等: event 按 payload_hash 去重; geo_point 按主键(ts,lat,lon)去重 → 重复导出安全
"""
import json, os, sqlite3, sys
from datetime import datetime, timedelta, timezone

DB_PATH = os.path.expanduser("~/.hermes/life-db/timeline.db")
SCHEMA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schema.sql")

TYPE_ZH = {
    "walking": "步行", "running": "跑步", "in passenger vehicle": "乘车",
    "in train": "火车", "in subway": "地铁", "in bus": "公交",
    "in ferry": "轮渡", "flying": "飞行", "cycling": "骑行",
    "motorcycling": "摩托", "still": "停留",
}

def parse_iso(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))

def geo_latlon(s):
    """'geo:37.46,126.43' → (lat, lon)"""
    if not s or not s.startswith("geo:"): return None, None
    try:
        lat, lon = s[4:].split(",")[:2]
        return float(lat), float(lon)
    except (ValueError, AttributeError):
        return None, None

def ingest(path, dry=False):
    with open(path, encoding="utf-8") as f:
        recs = json.load(f)
    if not isinstance(recs, list):
        sys.exit("Timeline.json 顶层不是列表, 格式不符")

    con = sqlite3.connect(DB_PATH)
    with open(SCHEMA) as fh:
        con.executescript(fh.read())

    n_visit = n_act = n_path = n_skip = 0
    for i, r in enumerate(recs):
        start, end = r.get("startTime"), r.get("endTime")
        if not start:
            n_skip += 1; continue

        # --- 1) visit → location event ---
        if "visit" in r:
            v = r["visit"]
            tc = v.get("topCandidate") or {}
            lat, lon = geo_latlon(tc.get("placeLocation"))
            stype = tc.get("semanticType") or "Unknown"
            title = f"Google停留-{stype}" if stype != "Unknown" else "Google停留-未知地点"
            meta = {"placeID": tc.get("placeID"), "semanticType": stype,
                    "probability": v.get("probability"), "cand_probability": tc.get("probability"),
                    "hierarchyLevel": v.get("hierarchyLevel")}
            h = f"gm-v-{tc.get('placeID','x')}-{start}"
            cur = con.execute(
                """INSERT OR IGNORE INTO event
                   (ts_start,ts_end,modality,source,title,payload_ref,payload_hash,lat,lon,tags,meta)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (start, end, "location", "gmaps", title, f"timeline[{i}]", h, lat, lon,
                 json.dumps(["出行"], ensure_ascii=False), json.dumps(meta, ensure_ascii=False)))
            n_visit += 1 if cur.rowcount else 0
            continue

        # --- 2) activity → transport event ---
        if "activity" in r:
            a = r["activity"]
            tc = a.get("topCandidate") or {}
            raw_type = (tc.get("type") or "unknown").strip()
            lat, lon = geo_latlon(a.get("start"))
            meta = {"type": raw_type, "probability": a.get("probability"),
                    "cand_probability": tc.get("probability"),
                    "distanceMeters": a.get("distanceMeters"),
                    "start": a.get("start"), "end": a.get("end")}
            h = f"gm-a-{start}-{raw_type}"
            cur = con.execute(
                """INSERT OR IGNORE INTO event
                   (ts_start,ts_end,modality,source,title,payload_ref,payload_hash,lat,lon,tags,meta)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (start, end, "transport", "gmaps",
                 TYPE_ZH.get(raw_type, raw_type), f"timeline[{i}]", h, lat, lon,
                 json.dumps(["出行"], ensure_ascii=False), json.dumps(meta, ensure_ascii=False)))
            n_act += 1 if cur.rowcount else 0
            continue

        # --- 3) timelinePath → geo_point (offset 推时间戳) ---
        if "timelinePath" in r:
            try:
                base = parse_iso(start)
            except ValueError:
                n_skip += 1; continue
            rows = []
            for p in r["timelinePath"]:
                lat, lon = geo_latlon(p.get("point"))
                if lat is None: continue
                try:
                    off_min = float(p.get("durationMinutesOffsetFromStartTime") or 0)
                except (TypeError, ValueError):
                    off_min = 0
                ts = int((base + timedelta(minutes=off_min)).timestamp())
                rows.append((ts, lat, lon, None, None))
            before = con.total_changes
            con.executemany(
                "INSERT OR IGNORE INTO geo_point(ts,lat,lon,alt,speed) VALUES (?,?,?,?,?)", rows)
            n_path += con.total_changes - before
            continue

        n_skip += 1

    if dry:
        con.rollback()
        print(f"[dry-run] visit {n_visit} 新增 / activity {n_act} 新增 / 轨迹点 {n_path} 新增"
              f" / 跳过 {n_skip} —— 已回滚, DB 未变")
    else:
        con.commit()
        print(f"visit 入库 {n_visit} 条, activity 入库 {n_act} 条, "
              f"geo_point 入库 {n_path} 点, 跳过 {n_skip} 条")

if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    if len(args) != 1:
        sys.exit(__doc__)
    ingest(args[0], dry=dry)
