#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Wrapped 数据层 — 年度总结的唯一数据源
规则见 visual/WRAPPED-SPEC.md:
  - 过夜地点: 2km 网格 → 城市级(20km)二次合并, 只报城市口径
  - 训练/健康/照片: 按年份过滤
  - 心率: 静息心率独立口径
输出: dict (供 HTML 卡片渲染)
用法: py -3 visual/wrapped_data.py [year]  默认 2026
"""
import json
import math
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

DB = os.environ.get("LIFEDB_DB") or os.path.join(
    os.path.expanduser("~"), ".hermes", "life-db", "timeline.db")
CST = timezone(timedelta(hours=8))

# 粗粒度城市表 (用于过夜地点城市级聚合的命名, ~50km 内判同城)
CITIES = [
    ("武汉", 30.59, 114.31), ("北京", 39.90, 116.41), ("上海", 31.23, 121.47),
    ("杭州", 30.27, 120.16), ("南京", 32.06, 118.80), ("苏州", 31.30, 120.58),
    ("常州", 31.81, 119.97), ("广州", 23.13, 113.26), ("深圳", 22.54, 114.06),
    ("长沙", 28.23, 112.94), ("成都", 30.57, 104.07), ("东京", 35.68, 139.69),
    ("大阪", 34.69, 135.50), ("首尔", 37.57, 126.98), ("新加坡", 1.35, 103.82),
    ("悉尼", -33.87, 151.21), ("布里斯班", -27.47, 153.03),
    ("黄金海岸", -28.17, 153.53), ("墨尔本", -37.81, 144.96),
    ("墨尔本", -38.50, 145.10), ("雅加达", -6.21, 106.85),
    ("泗水", -7.26, 112.75), ("巴厘", -8.41, 115.19),
    ("芝加哥", 41.88, -87.63), ("纽约", 40.71, -74.01),
    ("洛杉矶", 34.05, -118.24),
    # 旅行区域/卫星城 (50km 门槛覆盖不到的)
    ("大洋路", -38.71, 143.10), ("奈良", 34.69, 135.81), ("静冈", 34.98, 138.38),
    ("埼玉", 35.86, 139.65), ("咸宁", 29.84, 114.30), ("柳州", 24.32, 109.42),
    ("景德镇", 29.29, 117.18), ("辛辛那提", 39.10, -84.51),
    ("印第安纳", 39.77, -86.16), ("盐城", 33.35, 120.16),
    ("厦门", 24.48, 118.09), ("关西机场", 34.43, 135.24),
]
CITY_R = 50            # km — hav() 返回千米, 50km 内判同城


def hav(a, b):
    R = 6371.0
    la1, lo1, la2, lo2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    h = (math.sin((la2 - la1) / 2) ** 2 +
         math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(h))


def ep(ts):
    d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return d.replace(tzinfo=CST) if d.tzinfo is None else d


def city_name(la, lo):
    best, bd = None, 1e9
    for nm, cla, clo in CITIES:
        d = hav((la, lo), (cla, clo))
        if d < bd:
            best, bd = nm, d
    return best if bd < CITY_R else None


def nights_of_year(year, con):
    """过夜地点: 按 GPS 时区切日 → 夜间优先/末点 fallback → 2km 聚类 → 城市合并"""
    try:
        from tzfpy import get_tz
    except ImportError:
        get_tz = lambda lo, la: None
    fixes = []
    for r in con.execute("SELECT ts_start,ts_end,lat,lon FROM event WHERE lat IS NOT NULL"):
        for ts in (r["ts_start"], r["ts_end"]):
            if ts:
                fixes.append((ep(ts).timestamp(), r["lat"], r["lon"]))
    fixes.sort()
    by_day = defaultdict(list)
    for ts, la, lo in fixes:
        tzname = get_tz(lo, la) or "Asia/Shanghai"
        local = datetime.fromtimestamp(ts, timezone.utc).astimezone(ZoneInfo(tzname))
        if local.year != year:
            continue
        by_day[(tzname, local.date())].append((ts, la, lo))
    raw = []
    for (tzname, dte), pts in sorted(by_day.items()):
        tz = ZoneInfo(tzname)
        n0 = datetime(dte.year, dte.month, dte.day, 0, 0, tzinfo=tz).timestamp()
        n1 = datetime(dte.year, dte.month, dte.day, 5, 0, tzinfo=tz).timestamp()
        night = [p for p in pts if n0 <= p[0] <= n1]
        if night:
            spread = max((hav(night[0][1:], p[1:]) for p in night), default=0)
            if spread > 2.0:
                raw.append((dte, "moving", None, None))
            else:
                la, lo = night[-1][1:]
                raw.append((dte, "night", la, lo))
        else:
            la, lo = pts[-1][1:]
            raw.append((dte, "last-gps", la, lo))
    # 2km 聚类 (据点级)
    sites = []
    for dte, st, la, lo in sorted(raw, key=lambda x: x[0]):
        if st == "moving":
            continue
        for s in sites:
            if hav((la, lo), (s[2], s[3])) < 2.0:
                s[4] += 1
                s[5] += (st == "night")
                break
        else:
            sites.append([city_name(la, lo) or "?", st, la, lo, 1, int(st == "night")])
    # 城市级合并
    cities = defaultdict(lambda: {"nights": 0, "hard": 0, "sites": 0, "coord": None})
    for nm, st, la, lo, n, hard in sites:
        c = cities[nm]
        c["nights"] += n
        c["hard"] += hard
        c["sites"] += 1
        c["coord"] = (round(la, 2), round(lo, 2))
    moving = [d for d, st, *_ in raw if st == "moving"]
    return dict(
        total=len([d for d, st, *_ in raw if st != "moving"]),
        hard=sum(1 for d, st, *_ in raw if st == "night"),
        moving=len(moving),
        moving_days=[str(d) for d in moving],
        cities=[dict(city=k, **v) for k, v in
                sorted(cities.items(), key=lambda x: -x[1]["nights"])],
    )


def workouts_of_year(year, con, meta):
    days, sets, vol = set(), 0, 0.0
    for r in con.execute("SELECT ts_start, meta FROM event WHERE modality='workout'"):
        if not r["ts_start"].startswith(str(year)):
            continue
        days.add(r["ts_start"][:10])
        m = json.loads(r["meta"] or "{}")
        if meta == "xunji":
            pass
        sets += m.get("sets", 0)
        vol += m.get("volume_kg", 0) or m.get("volume", 0) or 0
    # xunji sets 结构不同 → 直接从 xunji meta 拿
    sets2 = 0
    for r in con.execute("SELECT meta FROM event WHERE modality='workout' "
                         "AND source='xunji' AND ts_start >= ? AND ts_start < ?",
                         (f"{year}", f"{year+1}")):
        m = json.loads(r["meta"] or "{}")
        sets2 += m.get("n_sets", m.get("set_count", m.get("sets", 0))) or 0
    routes = con.execute(
        "SELECT COUNT(*), COALESCE(SUM(json_extract(meta,'$.km')),0) FROM event "
        "WHERE modality='workout_route' AND ts_start >= ? AND ts_start < ?",
        (f"{year}", f"{year+1}")).fetchone()
    return dict(days=len(days), sets=sets2 or sets, volume_kg=round(vol),
                routes=routes[0], route_km=round(routes[1]))


def photos_of_year(year, con):
    """照片: 1km 热点 + 城市级旅行版图"""
    clusters = Counter()
    span, raw_pts = {}, defaultdict(list)
    for r in con.execute("SELECT ts_start, lat, lon FROM event "
                         "WHERE modality='photo' AND lat IS NOT NULL"):
        if not r["ts_start"].startswith(str(year)):
            continue
        la, lo = r["lat"], r["lon"]
        if la == 0 and lo == 0:        # EXIF 空坐标 (Null Island), 丢弃
            continue
        k = (round(la, 2), round(lo, 2))
        clusters[k] += 1
        raw_pts[city_name(la, lo) or "?"].append((la, lo, r["ts_start"][:10]))
        if k not in span:
            span[k] = [r["ts_start"][:10]] * 2
        else:
            span[k][0] = min(span[k][0], r["ts_start"][:10])
            span[k][1] = max(span[k][1], r["ts_start"][:10])
    cities = defaultdict(lambda: {"n": 0, "d0": "9999", "d1": ""})
    for c, pts in raw_pts.items():
        cities[c]["n"] += len(pts)
        cities[c]["d0"] = min(cities[c]["d0"], min(p[2] for p in pts))
        cities[c]["d1"] = max(cities[c]["d1"], max(p[2] for p in pts))
    return dict(total=sum(clusters.values()), regions=len(clusters),
                hot=[dict(coord=list(k), n=v, span=span[k])
                     for k, v in clusters.most_common(10)],
                cities=[dict(city=k, **v) for k, v in
                        sorted(cities.items(), key=lambda x: -x[1]["n"]) if v["n"] >= 5])


def health_of_year(year, con):
    """健康: 静息心率独立 + 步数 + 睡眠/心电按年"""
    rest, hr_all, steps = [], [], {}
    for r in con.execute("SELECT ts_start, meta FROM event WHERE modality='health_metric'"):
        if not r["ts_start"].startswith(str(year)):
            continue
        m = json.loads(r["meta"] or "{}")
        if m.get("metric") == "RestingHeartRate":
            rest.append(m["value"])
        elif m.get("metric") == "HeartRate":
            hr_all.append(m["stats"]["avg"])
        elif m.get("metric") == "StepCount":
            steps[r["ts_start"][:10]] = m["value"]
    sleep = con.execute("SELECT COUNT(*) FROM event WHERE modality='sleep' "
                        "AND source='apple_health' AND ts_start >= ? AND ts_start < ?",
                        (f"{year}", f"{year+1}")).fetchone()[0]
    ecg = con.execute("SELECT COUNT(*) FROM event WHERE modality='ecg' "
                      "AND ts_start >= ? AND ts_start < ?",
                      (f"{year}", f"{year+1}")).fetchone()[0]
    best_day = max(steps.items(), key=lambda x: x[1]) if steps else ("-", 0)
    return dict(
        rest_hr=round(sum(rest) / len(rest)) if rest else None,
        rest_hr_days=len(rest),
        hr_days=len(hr_all),
        steps_total=round(sum(steps.values())),
        steps_best_day=best_day[0], steps_best_n=round(best_day[1]),
        sleep_nights=sleep, ecg_n=ecg, metric_days=len(steps),
    )


def main():
    year = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    out = dict(year=year,
               nights=nights_of_year(year, con),
               workout=workouts_of_year(year, con, None),
               photos=photos_of_year(year, con),
               health=health_of_year(year, con))
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    con.close()


if __name__ == "__main__":
    main()
