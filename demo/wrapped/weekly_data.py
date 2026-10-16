#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""周回顾数据层 — 本周卡的唯一数据源
窗口: 指定周一 ~ 周日 (CST), 同时算前一周做环比
  - 通勤: geo_point 晨间轨迹, 家锚点(夜间中位数) → 公司锚点(工作日午后中位数)
  - 节奏: 步数逐日 + 静息心率/HRV 周均 (稀疏采样如实报天数)
  - 在外: 白天离家 >1.5km 的天数 + 走行距离 + 过夜城市
  - 训练: 训记 (xunji) 力量容量/组数/动作
输出: visual/_weekly_YYYYMMDD.json (日期取周一)
用法: py -3 visual/weekly_data.py 2026-08-24
"""
import json
import os
import sqlite3
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta

from wrapped_data import CST, city_name, hav

DB = os.environ.get("LIFEDB_DB") or os.path.join(
    os.path.expanduser("~"), ".hermes", "life-db", "timeline.db")


def day_range(d0, n=7):
    return [d0 + timedelta(days=i) for i in range(n)]


def day_key(dt):
    return dt.strftime("%Y-%m-%d")


def geo_points(con, d0, d1):
    t0, t1 = int(d0.timestamp()), int(d1.timestamp())
    return [(r[0], r[1], r[2]) for r in con.execute(
        "SELECT ts,lat,lon FROM geo_point WHERE ts>=? AND ts<? ORDER BY ts", (t0, t1))]


def anchors(con, w0, w1):
    """家 = 周边夜点(00-05)中位数; 公司 = 工作日 10-17 点、离家>5km 点的两轮中位数"""
    pts = geo_points(con, w0 - timedelta(days=7), w1 + timedelta(days=7))
    night = [(la, lo) for ts, la, lo in pts
             if 0 <= datetime.fromtimestamp(ts, CST).hour < 5]
    home = (statistics.median(p[0] for p in night), statistics.median(p[1] for p in night))
    day = [(la, lo) for ts, la, lo in pts
           if datetime.fromtimestamp(ts, CST).weekday() < 5
           and 10 <= datetime.fromtimestamp(ts, CST).hour < 17
           and hav((la, lo), home) > 5]
    far = [(la, lo) for la, lo in day if hav((la, lo), home) > 5]
    wk = (statistics.median(p[0] for p in far), statistics.median(p[1] for p in far))
    near = [(la, lo) for la, lo in far if hav((la, lo), wk) < 2]
    if len(near) >= 10:
        wk = (statistics.median(p[0] for p in near), statistics.median(p[1] for p in near))
    return home, wk


def commute_of_day(con, dte, home, work):
    """晨间 05-13 时: 最后一个在家点 → 第一个到公司点。返回 dict 或 None"""
    pts = geo_points(con, dte, dte + timedelta(days=1))
    pts = [(ts, la, lo) for ts, la, lo in pts
           if 5 <= datetime.fromtimestamp(ts, CST).hour < 13]
    dep = arr = None
    for ts, la, lo in pts:                      # 离家: 家→>1.5km 的跳变前最后近点
        if hav((la, lo), home) > 1.5:
            break
        if hav((la, lo), home) < 0.5:
            dep = ts
    if dep is None:
        return None
    for ts, la, lo in pts:                      # 到岗: 离家后首个公司近点
        if ts > dep and hav((la, lo), work) < 0.8:
            arr = ts
            break
    if arr is None:
        return None
    dur = (arr - dep) / 60
    if not 10 < dur < 300:
        return None
    return dict(departure=datetime.fromtimestamp(dep, CST).strftime("%H:%M"),
                arrival=datetime.fromtimestamp(arr, CST).strftime("%H:%M"),
                minutes=round(dur), km=round(hav(home, work), 1))


def metrics_of_week(con, d0, d1):
    """health_metric 逐日: StepCount / DistanceWalkingRunning / RHR / HRV / TimeInDaylight"""
    out = dict(steps={}, dist_m={}, rhr=[], hrv=[], daylight_m=defaultdict(float))
    for r in con.execute("SELECT ts_start,meta FROM event WHERE modality='health_metric' "
                         "AND ts_start>=? AND ts_start<?", (d0.strftime("%Y-%m-%d"),
                                                            d1.strftime("%Y-%m-%d"))):
        m = json.loads(r["meta"] or "{}")
        k, d = m.get("metric"), r["ts_start"][:10]
        if k == "StepCount":
            out["steps"][d] = m["value"]
        elif k == "DistanceWalkingRunning":
            out["dist_m"][d] = m["value"]
        elif k == "RestingHeartRate":
            out["rhr"].append(m["value"])
        elif k == "HeartRateVariabilitySDNN":
            out["hrv"].append(m["value"])
        elif k == "TimeInDaylight":
            out["daylight_m"][d] += m["value"]
    return out


def workouts_of_week(con, d0, d1):
    """训记口径 (xunji), 避免 apple_health 重复计"""
    days, sets, vol, detail = 0, 0, 0.0, []
    for r in con.execute("SELECT ts_start,meta FROM event WHERE modality='workout' "
                         "AND source='xunji' AND ts_start>=? AND ts_start<? ORDER BY ts_start",
                         (d0.strftime("%Y-%m-%d"), d1.strftime("%Y-%m-%d"))):
        m = json.loads(r["meta"] or "{}")
        days += 1
        sets += m.get("n_sets", 0)
        vol += m.get("volume_kg", 0) or 0
        detail.append(dict(date=r["ts_start"][:10], sets=m.get("n_sets", 0),
                           volume_kg=round(m.get("volume_kg", 0)),
                           movements=m.get("movements", [])))
    return dict(days=days, sets=sets, volume_kg=round(vol), detail=detail)


def nights_of_week(con, days):
    """每晚: 当日 00-05 最后 GPS 点 → 城市名"""
    out = []
    for dte in days:
        pts = [(ts, la, lo) for ts, la, lo in geo_points(con, dte, dte + timedelta(days=1))
               if 0 <= datetime.fromtimestamp(ts, CST).hour < 5]
        if not pts:
            out.append(None)
            continue
        la, lo = pts[-1][1:]
        out.append(city_name(la, lo) or "?")
    return out


def outdoors_of_week(con, days, home):
    """出门天数: 白天 08-20 有 >1.5km 的点; 另统计最远距离"""
    out = {}
    for dte in days:
        far = [hav((la, lo), home) for ts, la, lo in geo_points(con, dte, dte + timedelta(days=1))
               if 8 <= datetime.fromtimestamp(ts, CST).hour < 20]
        far = [d for d in far if d > 1.5]
        out[day_key(dte)] = round(max(far)) if far else 0
    return out


def build(week_monday):
    d0 = datetime.strptime(week_monday, "%Y-%m-%d").replace(tzinfo=CST)
    days, pdays = day_range(d0), day_range(d0 - timedelta(days=7))
    d1 = d0 + timedelta(days=7)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    home, work = anchors(con, d0, d1)
    cur, prev = metrics_of_week(con, d0, d1), metrics_of_week(con, d0 - timedelta(days=7), d1 - timedelta(days=7))

    commute = {day_key(d): c for d in days if (c := commute_of_day(con, d, home, work))
               and datetime.fromtimestamp(
                   int(datetime.strptime(day_key(d) + " " + c["departure"], "%Y-%m-%d %H:%M").timestamp()),
                   CST).weekday() < 5}
    wos = workouts_of_week(con, d0, d1)
    out = dict(
        week=week_monday,
        days=[day_key(d) for d in days],
        commute=dict(
            n=len(commute),
            avg_minutes=round(statistics.mean(c["minutes"] for c in commute.values())) if commute else None,
            avg_departure=(lambda ms: f"{int(sum(ms)/len(ms)//60):02d}:{round(sum(ms)/len(ms)%60):02d}" if ms else None)(
                [int(h[:2]) * 60 + int(h[3:]) for h in (c["departure"] for c in commute.values())]),
            avg_arrival=(lambda ms: f"{int(sum(ms)/len(ms)//60):02d}:{round(sum(ms)/len(ms)%60):02d}" if ms else None)(
                [int(h[:2]) * 60 + int(h[3:]) for h in (c["arrival"] for c in commute.values())]),
            km=round(hav(home, work), 1),
            earliest=min(commute.items(), key=lambda x: x[1]["departure"]) if commute else None,
            detail=commute,
        ),
        steps=dict(
            per_day={d: cur["steps"].get(d, 0) for d in (day_key(x) for x in days)},
            total=sum(cur["steps"].values()),
            prev_total=sum(prev["steps"].values()),
        ),
        body=dict(
            rhr=round(statistics.mean(cur["rhr"]), 1) if cur["rhr"] else None,
            rhr_n=len(cur["rhr"]),
            rhr_prev=round(statistics.mean(prev["rhr"]), 1) if prev["rhr"] else None,
            hrv=round(statistics.mean(cur["hrv"]), 1) if cur["hrv"] else None,
            hrv_n=len(cur["hrv"]),
            hrv_prev=round(statistics.mean(prev["hrv"]), 1) if prev["hrv"] else None,
        ),
        out=dict(
            away_days=sum(1 for v in outdoors_of_week(con, days, home).values() if v),
            max_km=max(outdoors_of_week(con, days, home).values(), default=0),
            dist_km=round(sum(cur["dist_m"].values()), 1),
            nights=nights_of_week(con, days),
            daylight_min=round(sum(cur["daylight_m"].values())),
            daylight_days=len(cur["daylight_m"]),
        ),
        workout=wos,
    )
    con.close()
    return out


if __name__ == "__main__":
    wk = sys.argv[1] if len(sys.argv) > 1 else "2026-08-24"
    data = build(wk)
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "out", f"_weekly_{wk.replace('-', '')}.json")
    json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    print(json.dumps(data, ensure_ascii=False, indent=1, default=str))
    print("saved:", path)
