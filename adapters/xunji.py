#!/usr/bin/env python
"""xunji adapter — 训记训练记录 → life-db

阶段1 fetch: 逐日拉取 API, 原始响应缓存到 adapters/_xunji_cache/<date>.json
  (按skill原则: 按datestr缓存, 已缓存日期不重复请求 → 天然断点续跑)
阶段2 ingest: 缓存 → event表 (modality=workout, source=xunji)

用法: py -3 adapters/xunji.py [start=2025-01-01] [end=今天] [--dry-run]
  --dry-run: 不发API请求(只报将拉取天数) + 入库在事务里跑完即回滚(avsm -test 语义)
"""
import json, os, sqlite3, sys, time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _xunji_api import trains

DB_PATH = os.path.expanduser("~/.hermes/life-db/timeline.db")
SCHEMA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schema.sql")
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_xunji_cache")
CST = timezone(timedelta(hours=8))

def fetch(start, end, dry=False):
    os.makedirs(CACHE, exist_ok=True)
    d = datetime.strptime(start, "%Y-%m-%d").date()
    stop = datetime.strptime(end, "%Y-%m-%d").date()
    cached = fetched = errs = 0
    while d <= stop:
        fp = os.path.join(CACHE, d.isoformat() + ".json")
        if os.path.exists(fp):
            cached += 1
        elif dry:
            fetched += 1   # dry-run: 只统计将拉取的天数, 不发请求
        else:
            try:
                r = trains(d.isoformat())
                with open(fp, "w", encoding="utf-8") as f:
                    json.dump(r, f, ensure_ascii=False)
                fetched += 1
                time.sleep(0.4)   # 温和限速, 防连续600+请求触发限频
            except Exception as e:
                errs += 1
                if errs <= 3: print(f"  ! {d}: {str(e)[:120]}")
        d += timedelta(days=1)
    prefix = "[dry-run] " if dry else ""
    print(f"{prefix}缓存 {cached} 天, {'将拉' if dry else '新拉'} {fetched} 天, 失败 {errs} 天")

def ingest(dry=False):
    con = sqlite3.connect(DB_PATH)
    with open(SCHEMA) as f:
        con.executescript(f.read())
    n_train = n_skip = 0
    for fn in sorted(os.listdir(CACHE)):
        with open(os.path.join(CACHE, fn), encoding="utf-8") as f:
            try: data = json.load(f)
            except Exception: continue
        for t in (data.get("res") or {}).get("trains") or []:
            start_ms = t.get("start") or t.get("started_at")
            end_ms = t.get("end") or t.get("ended_at")
            if not start_ms: 
                n_skip += 1; continue
            ts_start = datetime.fromtimestamp(start_ms/1000, CST).isoformat()
            ts_end = datetime.fromtimestamp(end_ms/1000, CST).isoformat() if end_ms else None
            movs = t.get("movements") or []
            names = [m.get("name","?") for m in movs if m.get("name")]
            # 组数/总容量估算
            n_sets = 0; vol = 0.0
            for m in movs:
                for s in m.get("sets") or []:
                    if not s.get("done"): continue
                    n_sets += 1
                    try: vol += float(s.get("weight") or 0) * float(s.get("reps") or 0)
                    except (TypeError, ValueError): pass
            title = t.get("title") or "、".join(names[:3]) or "训练"
            meta = {"movements": names, "n_movements": len(movs), "n_sets": n_sets,
                    "volume_kg": round(vol, 1), "localid": t.get("localid")}
            h = f"xj-{t.get('localid')}"
            cur = con.execute(
                """INSERT OR IGNORE INTO event
                   (ts_start,ts_end,modality,source,title,payload_ref,payload_hash,tags,lat,lon,meta)
                   VALUES (?,?,?,?,?,?,?,?,NULL,NULL,?)""",
                (ts_start, ts_end, "workout", "xunji", title, fn[:-5], h,
                 json.dumps(["健身"], ensure_ascii=False), json.dumps(meta, ensure_ascii=False)))
            if cur.rowcount: n_train += 1
            else: n_skip += 1
    if dry:
        con.rollback()
        print(f"[dry-run] 将入库训练 {n_train} 次, 已存在/跳过 {n_skip} —— 已回滚, DB 未变")
    else:
        con.commit()
        print(f"入库训练 {n_train} 次, 已存在/跳过 {n_skip}")

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    dry = "--dry-run" in sys.argv
    start = args[0] if len(args) > 0 else "2025-01-01"
    end = args[1] if len(args) > 1 else datetime.now(CST).strftime("%Y-%m-%d")
    print(f"范围: {start} → {end}{' [dry-run]' if dry else ''}")
    fetch(start, end, dry=dry)
    ingest(dry=dry)
