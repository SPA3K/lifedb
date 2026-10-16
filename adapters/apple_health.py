#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""apple_health adapter — Apple 健康导出(export.zip) → life-db

覆盖六类 (54 种 HK 类型的全量策略):
  1. 睡眠分期 HKCategoryTypeIdentifierSleepAnalysis
     → event (modality=sleep, source=apple_health)
     meta.stages_iso=[[起,止,分期]...] (带时区ISO), meta.mins{deep,core,rem,awake}
     会话切法 = 间隙聚类 (相邻记录>3h断开; 按日期分组会把凌晨续段链成24h长串, 踩过)
  2. workout-routes/*.gpx 锻炼轨迹
     → 文件拷入 store/apple_health/routes/ + event (modality=workout_route)
  3. electrocardiograms/*.csv 心电图
     → 文件拷入 store/apple_health/ecg/ + event (modality=ecg)
  4. <Workout> 元素 (271个: 步行/力量/骑行/徒步...)
     → event (modality=workout, source=apple_health) 含时长/距离/卡路里
  5. Quantity 类型 (心率39万/步数35万/活跃能量33万/步行距离/HRV/静息心率/血氧/VO2Max...)
     → 按**本地日期**聚合 event (modality=health_metric)
       meta.stats{sum,avg,min,max,n}, meta.unit — 260万原始点不进 event 表防爆库
  6. 小类 Category (高心率事件/正念/低心肺适能/噪音事件)
     → 原始事件 (modality=health_event)

用法: py -3 adapters/apple_health.py [zip路径] [--dry-run]
  省略路径 → 自动找 ~/.hermes/cache/documents 下最新且含 apple_health_export/ 的 zip
  --dry-run: 事务内跑完即回滚, DB 不变
幂等: ah-sleep-<sha1(首段起|末段止|段数)>; ah-{gpx,ecg}-<sha1(文件名)>;
      ah-wkt-<sha1(类型|起|止)>; ah-hm-<sha1(类型|日期)>; ah-he-<sha1(类型|起)>
      文件落库前检查存在性 → 重复跑零副作用
注意: 导出.xml ~1GB, 流式解析 ~2-7分钟 (只在目标记录处停留, 其余 clear())
"""
import glob
import hashlib
import json
import math
import os
import re
import shutil
import sqlite3
import sys
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from datetime import datetime

DB_PATH = os.path.expanduser("~/.hermes/life-db/timeline.db")
STORE = os.path.expanduser("~/.hermes/life-db/store/apple_health")
SCHEMA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "schema.sql")
FEISHU_CACHE = os.path.expanduser("~/.hermes/cache/documents")

VAL_MAP = {
    "AsleepDeep": "deep", "AsleepREM": "rem", "AsleepCore": "core",
    "AsleepUnspecified": "core", "Awake": "awake",
    "InBed": "inbed",          # 必须映射! 否则 else 分支变 other 混入会话 (踩过: 309 vs 37)
}
TS_FMT = "%Y-%m-%d %H:%M:%S %z"

# Quantity 类型 → (聚合方式, 单位, 最少日采样数)。仅收高信号类型
# sum=当日累计(步数/能量/距离), avg=当日均值(心率/血氧/呼吸)
# 第三项: 高频类型(心率/步数)日采样<3 丢弃防噪声; 低频类型(静息心率/VO2Max/体重
# 本身就是每日一条)门槛=1, 否则全被误杀 (踩过: RestingHeartRate 941条 → 0入库)
QUANTITY = {
    "HeartRate": ("avg", "次/分", 3),
    "RestingHeartRate": ("avg", "次/分", 1),
    "WalkingHeartRateAverage": ("avg", "次/分", 1),
    "HeartRateVariabilitySDNN": ("avg", "ms", 1),
    "HeartRateRecoveryOneMinute": ("avg", "次/分", 1),
    "StepCount": ("sum", "步", 3),
    "FlightsClimbed": ("sum", "层", 3),
    "ActiveEnergyBurned": ("sum", "千卡", 3),
    "BasalEnergyBurned": ("sum", "千卡", 3),
    "DistanceWalkingRunning": ("sum", "km", 3),
    "DistanceCycling": ("sum", "km", 3),
    "AppleExerciseTime": ("sum", "min", 3),
    "AppleStandTime": ("sum", "min", 3),
    "TimeInDaylight": ("sum", "min", 1),
    "OxygenSaturation": ("avg", "%", 3),
    "RespiratoryRate": ("avg", "次/分", 1),
    "VO2Max": ("avg", "ml/kg/min", 1),
    "EnvironmentalAudioExposure": ("avg", "dB", 3),
    "HeadphoneAudioExposure": ("avg", "dB", 3),
    "AppleSleepingWristTemperature": ("avg", "°C", 1),
    "BodyMass": ("avg", "kg", 1),
}

# 小类 Category → 直接存原始事件 (量小, 有告警/会话语义)
EVENT_CATS = {
    "HighHeartRateEvent": "高心率事件",
    "LowCardioFitnessEvent": "低心肺适能事件",
    "MindfulSession": "正念练习",
    "AudioExposureEvent": "环境噪音事件",
}

WKT_CN = {
    "Walking": "步行", "TraditionalStrengthTraining": "力量训练",
    "Cycling": "骑行", "Hiking": "徒步", "Rowing": "划船",
    "Running": "跑步", "HighIntensityIntervalTraining": "HIIT",
    "CrossTraining": "交叉训练", "StairClimbing": "爬楼",
    "FunctionalStrengthTraining": "功能性力量", "Elliptical": "椭圆机",
    "Other": "其他",
}


def find_zip():
    """最新且含 apple_health_export/ 的 zip (缓存目录扫描)"""
    best = None
    for p in glob.glob(os.path.join(FEISHU_CACHE, "*.zip")):
        try:
            with zipfile.ZipFile(p) as z:
                if any(n.startswith("apple_health_export/") for n in z.namelist()[:50]):
                    if best is None or os.path.getmtime(p) > os.path.getmtime(best):
                        best = p
        except Exception:
            continue
    return best


def hav(a, b):
    R = 6371.0
    la1, lo1, la2, lo2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    h = (math.sin((la2 - la1) / 2) ** 2 +
         math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(h))


def parse_scan(z, name):
    """单次流式扫描 1GB XML, 同时收集四类:
    睡眠原始记录 / Quantity 按日聚合 / Workout 元素 / 小类 Category
    Quantity 260万条在流式循环内即时聚合 → 内存只留 {(type,日期): 累加器}
    返回 (recs, hmq, workouts, events)
    """
    recs = []                       # 睡眠原始记录
    hmq = defaultdict(lambda: [0.0, float("inf"), float("-inf"), 0])  # sum,min,max,n
    workouts = []
    events = []
    with z.open(name) as f:
        for _, el in ET.iterparse(f, events=("end",)):
            tag = el.tag
            if tag == "Record":
                typ = el.get("type", "")
                short = typ.rsplit("Identifier", 1)[-1]
                if "SleepAnalysis" in typ:
                    v = el.get("value", "")
                    for k, mv in VAL_MAP.items():
                        if k in v:
                            v = mv
                            break
                    else:
                        v = "other"
                    recs.append((el.get("startDate"), el.get("endDate"), v))
                elif short in QUANTITY:
                    try:
                        val = float(el.get("value"))
                        ds = el.get("startDate", "")[:10]   # YYYY-MM-DD 本地日期
                    except (ValueError, TypeError):
                        pass
                    else:
                        if ds and math.isfinite(val):
                            a = hmq[(short, ds)]
                            a[0] += val
                            a[1] = min(a[1], val)
                            a[2] = max(a[2], val)
                            a[3] += 1
                elif short in EVENT_CATS:
                    events.append((short, el.get("startDate"), el.get("endDate"),
                                   el.get("value", "")))
            elif tag == "Workout":
                workouts.append((el.get("workoutActivityType", ""),
                                 el.get("startDate"), el.get("endDate"),
                                 el.get("duration"), el.get("totalDistance"),
                                 el.get("totalEnergyBurned")))
            el.clear()
    return recs, dict(hmq), workouts, events


def cluster_sleep(recs):
    """睡眠原始记录 → 间隙聚类会话列表"""
    parsed = []
    for s, e, v in recs:
        try:
            ds, de = datetime.strptime(s, TS_FMT), datetime.strptime(e, TS_FMT)
        except (ValueError, TypeError):
            continue
        if v == "inbed":
            continue
        parsed.append((ds, de, v))
    parsed.sort(key=lambda x: x[0])

    sessions, cur = [], []
    for ds, de, v in parsed:
        if cur and (ds - cur[-1][1]).total_seconds() > 3 * 3600:
            sessions.append(cur)
            cur = []
        cur.append((ds, de, v))
    if cur:
        sessions.append(cur)

    out = []
    for ses in sessions:
        tot = defaultdict(float)
        segs = []
        for ds, de, v in ses:
            mins = (de - ds).total_seconds() / 60
            if mins <= 0 or mins > 720:
                continue
            tot[v] += mins
            segs.append((ds, de, v))
        if len(segs) < 3:
            continue
        segs.sort(key=lambda x: x[0])
        out.append(dict(
            segs=segs,
            mins={k: round(v, 1) for k, v in tot.items()},
            total=round(sum(tot.values()), 1),
            span=round((segs[-1][1] - segs[0][0]).total_seconds() / 60, 1),
        ))
    return out


def _insert_event(con, ts0, ts1, modality, title, summary, ref, key,
                  lat, lon, meta):
    return con.execute(
        "insert or ignore into event "
        "(ts_start,ts_end,modality,source,title,summary,payload_ref,"
        " payload_hash,lat,lon,tags,meta) values (?,?,?,?,?,?,?,?,?,?,?,?)",
        (ts0, ts1, modality, "apple_health", title, summary, ref,
         key, lat, lon, "[]", meta)).rowcount


def ingest_sleep(con, sessions):
    n = 0
    for s in sessions:
        segs = s["segs"]
        key = "ah-sleep-" + hashlib.sha1(
            (segs[0][0].isoformat() + "|" + segs[-1][1].isoformat() +
             "|" + str(len(segs))).encode()).hexdigest()[:16]
        meta = json.dumps(dict(
            stages_iso=[[a.isoformat(), b.isoformat(), v] for a, b, v in segs],
            mins=s["mins"], total_min=s["total"], span_min=s["span"]),
            ensure_ascii=False)
        m = s["mins"]
        summary = (f"深{m.get('deep', 0):.0f} 浅{m.get('core', 0):.0f} "
                   f"REM{m.get('rem', 0):.0f} 醒{m.get('awake', 0):.0f}min")
        n += _insert_event(con, segs[0][0].isoformat(), segs[-1][1].isoformat(),
                           "sleep", "睡眠", summary, None, key, None, None, meta)
    return n


def ingest_health_metrics(con, hmq):
    """Quantity 按日聚合 → health_metric 事件 (每天每类型一条)"""
    n = 0
    for (short, ds), (s, mn, mx, cnt) in sorted(hmq.items()):
        agg, unit, min_n = QUANTITY[short]
        if cnt < min_n:                 # 高频类型<3采样丢弃; 低频(静息心率等)门槛=1
            continue
        val = s if agg == "sum" else s / cnt
        key = "ah-hm-" + hashlib.sha1(f"{short}|{ds}".encode()).hexdigest()[:16]
        stats = dict(sum=round(s, 2), avg=round(s / cnt, 2),
                     min=round(mn, 2), max=round(mx, 2), n=cnt)
        title = METRIC_CN.get(short, short)
        n += _insert_event(con, ds + "T00:00:00", ds + "T23:59:59",
                           "health_metric", title,
                           f"{val:.6g} {unit} ({cnt}采样)",
                           None, key, None, None,
                           json.dumps(dict(metric=short, unit=unit,
                                           agg=agg, value=round(val, 2),
                                           stats=stats), ensure_ascii=False))
    return n


METRIC_CN = {
    "HeartRate": "心率", "RestingHeartRate": "静息心率",
    "WalkingHeartRateAverage": "步行平均心率",
    "HeartRateVariabilitySDNN": "HRV(SDNN)", "HeartRateRecoveryOneMinute": "运动后心率恢复",
    "StepCount": "步数", "FlightsClimbed": "爬楼层数",
    "ActiveEnergyBurned": "活跃能量", "BasalEnergyBurned": "基础能量",
    "DistanceWalkingRunning": "步行跑步距离", "DistanceCycling": "骑行距离",
    "AppleExerciseTime": "锻炼时间", "AppleStandTime": "站立时间",
    "TimeInDaylight": "户外时间", "OxygenSaturation": "血氧",
    "RespiratoryRate": "呼吸频率", "VO2Max": "VO2Max",
    "EnvironmentalAudioExposure": "环境噪音", "HeadphoneAudioExposure": "耳机音量",
    "AppleSleepingWristTemperature": "睡眠手腕温度", "BodyMass": "体重",
}


def ingest_workouts(con, workouts):
    """<Workout> 元素 → workout 事件 (apple_health 源, 与训记 xunji 区分)"""
    n = 0
    for wtype, s, e, dur, dist, kcal in workouts:
        try:
            t0 = datetime.strptime(s, TS_FMT)
            t1 = datetime.strptime(e, TS_FMT)
        except (ValueError, TypeError):
            continue
        short = wtype.rsplit("ActivityType", 1)[-1]
        cn = WKT_CN.get(short, short)
        key = "ah-wkt-" + hashlib.sha1(f"{wtype}|{s}|{e}".encode()).hexdigest()[:16]
        fields = [f"{dur}min"] if dur else []
        if dist:
            fields.append(f"{dist}km")
        if kcal:
            fields.append(f"{kcal}千卡")
        n += _insert_event(
            con, t0.isoformat(), t1.isoformat(), "workout", f"Apple锻炼·{cn}",
            " / ".join(fields) or None, None, key, None, None,
            json.dumps(dict(type=short, duration_min=float(dur) if dur else None,
                            km=float(dist) if dist else None,
                            kcal=float(kcal) if kcal else None),
                       ensure_ascii=False))
    return n


def ingest_health_events(con, events):
    """小类 Category → health_event 原始事件"""
    n = 0
    for short, s, e, val in events:
        try:
            t0 = datetime.strptime(s, TS_FMT)
            t1 = datetime.strptime(e, TS_FMT) if e else t0
        except (ValueError, TypeError):
            continue
        key = "ah-he-" + hashlib.sha1(f"{short}|{s}".encode()).hexdigest()[:16]
        n += _insert_event(
            con, t0.isoformat(), t1.isoformat(), "health_event",
            EVENT_CATS[short], val or None, None, key, None, None,
            json.dumps(dict(type=short), ensure_ascii=False))
    return n


def ingest_gpx(con, z):
    n = 0
    rdir = os.path.join(STORE, "routes")
    os.makedirs(rdir, exist_ok=True)
    names = [x for x in z.namelist()
             if x.startswith("apple_health_export/workout-routes/")
             and x.endswith(".gpx")]
    for nm in names:
        base = os.path.basename(nm)
        dst = os.path.join(rdir, base)
        if not os.path.exists(dst):
            with z.open(nm) as src, open(dst, "wb") as fo:
                shutil.copyfileobj(src, fo)
        try:
            txt = open(dst, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        # GPX 实际格式: lon 在 lat 前 + 单行紧凑 (Apple 导出风格), 逐段解析属性
        pts = []
        for attrs, body in re.findall(r"<trkpt ([^>]+)>(.*?)</trkpt>", txt, re.S):
            la = re.search(r'lat="([-\d.]+)"', attrs)
            lo = re.search(r'lon="([-\d.]+)"', attrs)
            tm = re.search(r"<time>(.*?)</time>", body)
            if la and lo and tm:
                pts.append((float(la.group(1)), float(lo.group(1)), tm.group(1)))
        if len(pts) < 2:
            continue
        try:
            t0 = datetime.fromisoformat(pts[0][2].replace("Z", "+00:00"))
            t1 = datetime.fromisoformat(pts[-1][2].replace("Z", "+00:00"))
        except ValueError:
            continue
        km = sum(hav((pts[i][0], pts[i][1]), (pts[i + 1][0], pts[i + 1][1]))
                 for i in range(len(pts) - 1))
        key = "ah-gpx-" + hashlib.sha1(base.encode()).hexdigest()[:16]
        n += _insert_event(
            con, t0.isoformat(), t1.isoformat(), "workout_route", "锻炼轨迹",
            f"{km:.1f}km / {(t1-t0).total_seconds()/60:.0f}min", dst, key,
            pts[0][0], pts[0][1],
            json.dumps(dict(points=len(pts), km=round(km, 2))))
    return n, len(names)


def ingest_ecg(con, z):
    n = 0
    edir = os.path.join(STORE, "ecg")
    os.makedirs(edir, exist_ok=True)
    names = [x for x in z.namelist()
             if "/electrocardiograms/" in x and x.endswith(".csv")]
    for nm in names:
        base = os.path.basename(nm)
        dst = os.path.join(edir, base)
        if not os.path.exists(dst):
            with z.open(nm) as src, open(dst, "wb") as fo:
                shutil.copyfileobj(src, fo)
        m = re.search(r"ecg_(\d{4}-\d{2}-\d{2})", base)
        if not m:
            continue
        key = "ah-ecg-" + hashlib.sha1(base.encode()).hexdigest()[:16]
        n += _insert_event(con, m.group(1) + "T00:00:00",
                           m.group(1) + "T00:01:00", "ecg", "心电图",
                           None, dst, key, None, None, "{}")
    return n, len(names)


def main():
    argv = sys.argv[1:]
    dry = "--dry-run" in argv
    paths = [a for a in argv if not a.startswith("--")]
    zp = paths[0] if paths else find_zip()
    if not zp or not os.path.exists(zp):
        sys.exit("找不到 Apple 健康导出 zip (传路径或放进 ~/.hermes/cache/documents)")
    print("导出包:", zp, f"({os.path.getsize(zp)/1e6:.0f}MB)")

    z = zipfile.ZipFile(zp)
    xml_name = next((n for n in z.namelist()
                     if n.endswith(".xml") and "cda" not in n.lower()), None)
    con = sqlite3.connect(DB_PATH)
    with open(SCHEMA) as fh:
        con.executescript(fh.read())

    n_sleep = 0
    n_hm = n_wkt = n_he = 0
    if xml_name:
        print("解析 export.xml (1GB 流式, ~3-8min) ...", flush=True)
        recs, hmq, workouts, events = parse_scan(z, xml_name)
        sessions = cluster_sleep(recs)
        print(f"  睡眠会话 {len(sessions)} / 指标日聚合 {len(hmq)} / "
              f"锻炼 {len(workouts)} / 健康事件 {len(events)}")
        n_sleep = ingest_sleep(con, sessions)
        n_hm = ingest_health_metrics(con, hmq)
        n_wkt = ingest_workouts(con, workouts)
        n_he = ingest_health_events(con, events)
    n_gpx, tot_gpx = ingest_gpx(con, z)
    n_ecg, tot_ecg = ingest_ecg(con, z)

    if dry:
        con.rollback()
        print(f"[dry-run] 将新增: 睡眠 {n_sleep} / 指标 {n_hm} / 锻炼 {n_wkt} / "
              f"健康事件 {n_he} / 轨迹 {n_gpx}/{tot_gpx} / 心电 {n_ecg}/{tot_ecg} (已回滚)")
    else:
        con.commit()
        print(f"✓ 新增: 睡眠 {n_sleep} / 指标 {n_hm} / 锻炼 {n_wkt} / "
              f"健康事件 {n_he} / 轨迹 {n_gpx}/{tot_gpx} / 心电 {n_ecg}/{tot_ecg}")
    con.close()


if __name__ == "__main__":
    main()
