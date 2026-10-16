#!/usr/bin/env python3
"""训记 adapter — 拉取训练+身体数据, 归一为 life-db 事件 JSONL

用法:
  py -3 adapters/xunjii.py trains 2024-01-01 2026-10-12 > data/xunjii_trains.jsonl
  py -3 adapters/xunjii.py body   2024-01-01 2026-10-12 > data/xunjii_body.jsonl

归一化规则:
  训练 -> modality=workout, source=xunjii
    ts_start/ts_end: 训练 start/end (epoch ms -> ISO +08:00)
    title: 前3个动作名 + "等N个动作", 无标题时自动生成
    payload_ref: xunji://train/{localid}@{datestr}  (去重键)
    meta: localid, calorie, movements 全概要(动作名/完成组数/最大重量/总次数)
  身体 -> modality=body, source=xunjii
    ts_start: datestr 当天 12:00 +08:00
    title: "{label} {value}{unit}"
    payload_ref: xunji://body/{type}@{datestr}
"""
import gzip, json, sys, time, urllib.request
from datetime import datetime, timedelta, timezone

CST = timezone(timedelta(hours=8))
TRAIN_KEY = "xjllm_84866d3e3bfefdcbf7b30ef31c172f9e854cebc398b5a1ea"
BODY_KEY = "xjbody_fc09cf92468552bbe40266b48c61e9c2ad999bbf5f969fd0"

def post(url, key, body, retries=3):
    for attempt in range(retries):
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={
            "Authorization": f"Bearer {key}", "Content-Type": "application/json",
            "Accept-Encoding": "gzip"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip" or raw[:2] == b"\x1f\x8b":
                    raw = gzip.decompress(raw)
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            txt = e.read().decode("utf-8", "replace")
            if "too frequent" in txt and attempt < retries - 1:
                wait = 16
                print(f"  [限频] 等 {wait}s 后重试", file=sys.stderr)
                time.sleep(wait)
                continue
            raise RuntimeError(f"HTTP {e.code}: {txt[:200]}")
    raise RuntimeError("retries exhausted")

def daterange(start, end):
    d = datetime.strptime(start, "%Y-%m-%d").date()
    stop = datetime.strptime(end, "%Y-%m-%d").date()
    while d <= stop:
        yield d.strftime("%Y-%m-%d")
        d += timedelta(days=1)

def ms_to_iso(ms):
    if not ms: return None
    return datetime.fromtimestamp(ms / 1000, CST).isoformat()

def movement_summary(mv):
    sets = mv.get("sets", [])
    done = [s for s in sets if s.get("done")]
    weights, reps_total = [], 0
    for s in done:
        try: weights.append(float(s.get("weight") or 0))
        except ValueError: pass
        try: reps_total += int(float(s.get("reps") or 0))
        except ValueError: pass
    return {"name": mv.get("name", "?"), "type": mv.get("type", ""),
            "done_sets": len(done), "total_sets": len(sets),
            "max_weight": max(weights) if weights else None,
            "reps_total": reps_total}

def train_event(t):
    mvs = [movement_summary(m) for m in t.get("movements", [])]
    names = [m["name"] for m in mvs if m["name"]]
    title = "、".join(names[:3]) + (f" 等{len(names)}个动作" if len(names) > 3 else "") if names else "训练"
    cal = None
    note = t.get("note") or ""
    if note.startswith("calorie:"):
        try: cal = int(float(note.split(":")[1]))
        except ValueError: pass
    return {
        "ts_start": ms_to_iso(t.get("start")) or f"{t['datestr']}T12:00:00+08:00",
        "ts_end": ms_to_iso(t.get("end")),
        "modality": "workout", "source": "xunjii",
        "title": title,
        "payload_ref": f"xunji://train/{t['localid']}@{t['datestr']}",
        "meta": {"localid": t.get("localid"), "datestr": t.get("datestr"),
                 "calorie": cal, "movements": mvs},
    }

def body_event(rec):
    ds = rec.get("datestr")
    return {
        "ts_start": f"{ds}T12:00:00+08:00",
        "modality": "body", "source": "xunjii",
        "title": f"{rec.get('label', rec['type'])} {rec.get('value')}{rec.get('unit', '')}",
        "payload_ref": f"xunji://body/{rec['type']}@{ds}",
        "meta": {"type": rec["type"], "value": rec.get("value"), "unit": rec.get("unit")},
    }

def main():
    mode, start, end = sys.argv[1], sys.argv[2], sys.argv[3]
    if mode == "trains":
        n = 0
        for day in daterange(start, end):
            r = post("https://trains.xunjiapp.cn/api_trains_for_llm_v2", TRAIN_KEY,
                     {"schema_version": "train_open_api_v2", "datestr": day,
                      "include_full_data": False})
            for t in r.get("res", {}).get("trains", []):
                print(json.dumps(train_event(t), ensure_ascii=False)); n += 1
            time.sleep(0.15)  # 跨日期无限频, 仍留余量
        print(f"[trains] {n} 条训练事件", file=sys.stderr)
    elif mode == "body":
        n = 0
        # 接口按 limit/offset 分页
        offset = 0
        while True:
            r = post("https://api.xunjiapp.cn/open/body/query_gzip", BODY_KEY,
                     {"start_date": start, "end_date": end,
                      "include_records": True, "limit": 500, "offset": offset})
            recs = r.get("res", {}).get("records", [])
            for rec in recs:
                print(json.dumps(body_event(rec), ensure_ascii=False)); n += 1
            if len(recs) < 500: break
            offset += 500
            time.sleep(1)
        print(f"[body] {n} 条身体事件", file=sys.stderr)
    else:
        sys.exit("mode 必须是 trains 或 body")

if __name__ == "__main__":
    main()
